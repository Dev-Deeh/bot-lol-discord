"""Diversão: sorteio de times balanceado, roleta, quiz, XP/níveis, moedas e apostas."""
import itertools
import random
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

from core import util
from core.util import UserError

COIN = "🪙"


# ================================================================= QUIZ
class QuizView(util.BaseView):
    def __init__(self, cog, answer: str, options: list[str], reveal: discord.Embed):
        super().__init__(timeout=30)
        self.cog, self.answer, self.reveal = cog, answer, reveal
        self.tried: set[int] = set()
        self.winner: discord.abc.User | None = None
        self.message: discord.Message | None = None
        for opt in options:
            btn = discord.ui.Button(label=opt, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_callback(opt, btn)
            self.add_item(btn)

    def _make_callback(self, option: str, button: discord.ui.Button):
        async def callback(interaction: discord.Interaction):
            if self.winner:
                return await interaction.response.send_message("Alguém já acertou!", ephemeral=True)
            if interaction.user.id in self.tried:
                return await interaction.response.send_message("Você já chutou nessa rodada 😅", ephemeral=True)
            self.tried.add(interaction.user.id)
            if option != self.answer:
                return await interaction.response.send_message(f"❌ Não é **{option}**!", ephemeral=True)
            self.winner = interaction.user
            self._finish()
            self.reveal.description = f"🏆 {interaction.user.mention} acertou: **{self.answer}**! (+30 XP, +20 {COIN})"
            await interaction.response.edit_message(embed=self.reveal, view=self)
            await util.give_xp(self.cog.bot, interaction.guild, interaction.user, 30, 20, interaction.channel)
            self.stop()
        return callback

    def _finish(self):
        for item in self.children:
            item.disabled = True
            if item.label == self.answer:
                item.style = discord.ButtonStyle.success

    async def on_timeout(self):
        if self.winner or not self.message:
            return
        self._finish()
        self.reveal.description = f"⌛ Tempo esgotado! Era **{self.answer}**."
        try:
            await self.message.edit(embed=self.reveal, view=self)
        except discord.HTTPException:
            pass


# ================================================================= APOSTAS
async def bet_embed(bot, bet) -> discord.Embed:
    rows = await bot.db.fetchall("SELECT option, SUM(amount) AS total, COUNT(*) AS n FROM wagers "
                                 "WHERE bet_id=? GROUP BY option", (bet["id"],))
    totals = {r["option"]: (r["total"], r["n"]) for r in rows}
    pot = sum(t for t, _ in totals.values()) or 0
    status = {"aberta": "🟢 Apostas abertas", "fechada": "🔒 Apostas fechadas", "encerrada": "🏁 Encerrada",
              "cancelada": "🚫 Cancelada"}[bet["status"]]
    embed = discord.Embed(title=f"🎲 {bet['title']}", description=f"{status} · Pote: **{pot} {COIN}**",
                          color=0xF1C40F)
    for key, name in (("a", bet["option_a"]), ("b", bet["option_b"])):
        total, n = totals.get(key, (0, 0))
        odds = f" · paga {pot / total:.2f}x" if total else ""
        winner = " 🏆" if bet["winner"] == key else ""
        embed.add_field(name=f"{name}{winner}", value=f"{total} {COIN} ({n} apostas){odds}", inline=True)
    embed.set_footer(text=f"Aposta #{bet['id']} · moeda fictícia, só por diversão")
    return embed


class WagerModal(discord.ui.Modal, title="Fazer aposta"):
    amount = discord.ui.TextInput(label="Quantas moedas?", placeholder="ex.: 100", max_length=7)

    def __init__(self, bet_id: int, option: str):
        super().__init__()
        self.bet_id, self.option = bet_id, option

    async def on_submit(self, interaction: discord.Interaction):
        bot = interaction.client
        if not self.amount.value.isdigit() or int(self.amount.value) <= 0:
            return await interaction.response.send_message("Digite um número inteiro positivo.", ephemeral=True)
        value = int(self.amount.value)
        bet = await bot.db.fetchone("SELECT * FROM bets WHERE id=?", (self.bet_id,))
        if not bet or bet["status"] != "aberta":
            return await interaction.response.send_message("As apostas estão fechadas.", ephemeral=True)
        prev = await bot.db.fetchone("SELECT * FROM wagers WHERE bet_id=? AND user_id=?",
                                     (self.bet_id, interaction.user.id))
        if prev and prev["option"] != self.option:
            return await interaction.response.send_message("Você já apostou no outro lado! 😏", ephemeral=True)
        prof = await bot.db.profile(interaction.guild_id, interaction.user.id)
        if prof["coins"] < value:
            return await interaction.response.send_message(
                f"Você só tem **{prof['coins']} {COIN}**. Pegue mais com `/diario`.", ephemeral=True)
        await bot.db.add_profile(interaction.guild_id, interaction.user.id, coins=-value)
        await bot.db.execute(
            "INSERT INTO wagers (bet_id, user_id, option, amount) VALUES (?,?,?,?) "
            "ON CONFLICT(bet_id, user_id) DO UPDATE SET amount = amount + excluded.amount",
            (self.bet_id, interaction.user.id, self.option, value))
        await interaction.response.edit_message(embed=await bet_embed(bot, bet))
        name = bet["option_a"] if self.option == "a" else bet["option_b"]
        await interaction.followup.send(f"✅ Você apostou **{value} {COIN}** em **{name}**.", ephemeral=True)


class BetView(util.BaseView):
    def __init__(self):
        super().__init__(timeout=None)

    async def _bet(self, interaction: discord.Interaction, option: str):
        bet = await interaction.client.db.fetchone("SELECT * FROM bets WHERE message_id=?", (interaction.message.id,))
        if not bet or bet["status"] != "aberta":
            return await interaction.response.send_message("As apostas estão fechadas.", ephemeral=True)
        await interaction.response.send_modal(WagerModal(bet["id"], option))

    @discord.ui.button(label="Apostar no 1º", emoji="🅰️", style=discord.ButtonStyle.primary, custom_id="bet:a")
    async def bet_a(self, interaction, button):
        await self._bet(interaction, "a")

    @discord.ui.button(label="Apostar no 2º", emoji="🅱️", style=discord.ButtonStyle.danger, custom_id="bet:b")
    async def bet_b(self, interaction, button):
        await self._bet(interaction, "b")


# ================================================================= COG
class Diversao(commands.Cog):
    aposta = app_commands.Group(name="aposta", description="Apostas com moeda fictícia (CBLOL, Mundial...)",
                                guild_only=True)

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(BetView())

    # ------------------------------------------------------------ XP por mensagem
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        prof = await self.bot.db.profile(message.guild.id, message.author.id)
        if time.time() - prof["last_xp_ts"] < 60:
            return
        await self.bot.db.touch(message.guild.id, message.author.id, "last_xp_ts")
        await util.give_xp(self.bot, message.guild, message.author, random.randint(15, 25), 0, message.channel)

    # ------------------------------------------------------------ /times
    @app_commands.command(name="times", description="Sorteia 2 times balanceados por elo (personalizada)")
    @app_commands.describe(jogadores="Mencione os jogadores (vazio = quem está na sua call)",
                           rotas="Também sortear rotas (times de 5)")
    @app_commands.guild_only()
    async def times(self, interaction: discord.Interaction, jogadores: str | None = None, rotas: bool = True):
        guild = interaction.guild
        if jogadores:
            ids = list(dict.fromkeys(int(x) for x in re.findall(r"<@!?(\d+)>", jogadores)))
            members = []
            for uid in ids:
                try:
                    members.append(guild.get_member(uid) or await guild.fetch_member(uid))
                except discord.NotFound:
                    pass
        elif isinstance(interaction.user, discord.Member) and interaction.user.voice and interaction.user.voice.channel:
            members = [m for m in interaction.user.voice.channel.members if not m.bot]
        else:
            raise UserError("Entre numa call ou mencione os jogadores no comando.")
        if len(members) < 2 or len(members) % 2 or len(members) > 10:
            raise UserError(f"Preciso de um número par de jogadores entre 2 e 10 (tenho {len(members)}).")

        rows = await self.bot.db.fetchall("SELECT * FROM accounts WHERE guild_id=?", (guild.id,))
        acc = {r["user_id"]: r for r in rows}

        def score(m):
            r = acc.get(m.id)
            return (r and util.elo_score(r["tier"], r["rank"], r["lp"])) or util.DEFAULT_SCORE

        total = sum(score(m) for m in members)
        half = len(members) // 2
        splits = []
        for combo in itertools.combinations(range(len(members)), half):
            a = sum(score(members[i]) for i in combo)
            splits.append((abs(total - 2 * a), combo))
        best = min(d for d, _ in splits)
        _, combo = random.choice([s for s in splits if s[0] <= best + 50])
        team_a = [members[i] for i in combo]
        team_b = [m for i, m in enumerate(members) if i not in combo]

        def fmt(team):
            lanes = [v for _, v in util.LANES]
            random.shuffle(lanes)
            lines = []
            for i, m in enumerate(team):
                r = acc.get(m.id)
                elo = util.elo_str(r["tier"], r["rank"], r["lp"]) if r and r["tier"] else "sem elo"
                lane = f"{util.LANE_EMOJI[lanes[i]]} " if rotas and len(team) == 5 else ""
                lines.append(f"{lane}{m.mention} · {elo}")
            avg = sum(score(m) for m in team) / len(team)
            return "\n".join(lines), avg

        a_txt, a_avg = fmt(team_a)
        b_txt, b_avg = fmt(team_b)
        embed = discord.Embed(title="⚖️ Times sorteados", color=0x5865F2)
        embed.add_field(name=f"🔵 Time Azul (média {a_avg:.0f})", value=a_txt, inline=True)
        embed.add_field(name=f"🔴 Time Vermelho (média {b_avg:.0f})", value=b_txt, inline=True)
        embed.set_footer(text="Quem não tem conta vinculada conta como Prata III")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------ /roleta
    @app_commands.command(name="roleta", description="Sorteia campeão, rota ou uma build troll")
    @app_commands.choices(tipo=[app_commands.Choice(name="Campeão", value="campeao"),
                                app_commands.Choice(name="Rota", value="rota"),
                                app_commands.Choice(name="Build troll", value="build"),
                                app_commands.Choice(name="Tudo (desafio completo)", value="tudo")])
    async def roleta(self, interaction: discord.Interaction, tipo: app_commands.Choice[str]):
        await interaction.response.defer()
        dd = self.bot.ddragon
        await dd.ensure()
        embed = discord.Embed(title="🎰 Roleta", color=0xE67E22)
        if tipo.value in ("campeao", "tudo"):
            champ = random.choice(list(dd.champions.values()))
            embed.add_field(name="Campeão", value=f"**{champ['name']}**", inline=True)
            embed.set_thumbnail(url=dd.champ_icon(champ["id"]))
        if tipo.value in ("rota", "tudo"):
            name, lane = random.choice(util.LANES)
            embed.add_field(name="Rota", value=f"{util.LANE_EMOJI[lane]} **{name}**", inline=True)
        if tipo.value in ("build", "tudo"):
            items = await dd.items()
            sr = [i for i in items.values() if i.get("maps", {}).get("11") and i["gold"]["purchasable"]
                  and not i.get("into") and not i.get("requiredChampion") and not i.get("consumed")
                  and not i.get("requiredAlly")]
            boots = [i for i in sr if "Boots" in i.get("tags", []) and i["gold"]["total"] >= 900]
            legend = [i for i in sr if "Boots" not in i.get("tags", []) and i["gold"]["total"] >= 2200]
            picks = random.sample(legend, 5) + ([random.choice(boots)] if boots else [])
            embed.add_field(name="Build", value="\n".join(f"• {i['name']}" for i in picks), inline=False)
            embed.add_field(name="Runa principal", value=random.choice(dd.keystones or ["?"]), inline=True)
        embed.set_footer(text="Sem chorar, a roleta decidiu 😈")
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------ /quiz
    @app_commands.command(name="quiz", description="Quiz de LoL: adivinhe o campeão!")
    @app_commands.choices(modo=[app_commands.Choice(name="Habilidade", value="habilidade"),
                                app_commands.Choice(name="Splash art", value="splash"),
                                app_commands.Choice(name="Título", value="titulo"),
                                app_commands.Choice(name="Aleatório", value="aleatorio")])
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.channel_id)
    async def quiz(self, interaction: discord.Interaction, modo: app_commands.Choice[str] | None = None):
        await interaction.response.defer()
        dd = self.bot.ddragon
        await dd.ensure()
        mode = modo.value if modo else "aleatorio"
        if mode == "aleatorio":
            mode = random.choice(["habilidade", "splash", "titulo"])
        champs = list(dd.champions.values())
        champ = random.choice(champs)
        detail = await dd.champion_detail(champ["id"])
        others = random.sample([c["name"] for c in champs if c["id"] != champ["id"]], 3)
        options = others + [champ["name"]]
        random.shuffle(options)

        embed = discord.Embed(title="❓ Quem é esse campeão?", color=0x9B59B6)
        if mode == "habilidade":
            idx = random.randrange(5)
            if idx == 4:
                spell, key = detail["passive"], "Passiva"
                icon = f"https://ddragon.leagueoflegends.com/cdn/{dd.version}/img/passive/{spell['image']['full']}"
            else:
                spell, key = detail["spells"][idx], "QWER"[idx]
                icon = dd.spell_icon(spell["image"]["full"])
            desc = re.sub(r"<[^>]+>", "", spell["description"])
            desc = re.sub(re.escape(champ["name"]), "???", desc, flags=re.I)
            embed.add_field(name=f"Habilidade ({key}): {spell['name']}", value=desc[:500] or "—")
            embed.set_thumbnail(url=icon)
        elif mode == "splash":
            skin = random.choice(detail["skins"])
            embed.description = "De quem é essa splash art?"
            embed.set_image(url=dd.splash(champ["id"], skin["num"]))
        else:
            embed.description = f"Qual campeão é conhecido como **\"{champ['title']}\"**?"
        embed.set_footer(text="30 segundos · cada um só pode chutar uma vez")

        reveal = discord.Embed(title=f"✅ Era {champ['name']}!", color=0x2ECC71)
        reveal.set_thumbnail(url=dd.champ_icon(champ["id"]))
        view = QuizView(self, champ["name"], options, reveal)
        view.message = await interaction.followup.send(embed=embed, view=view, wait=True)

    # ------------------------------------------------------------ níveis e moedas
    @app_commands.command(name="nivel", description="Seu nível, XP e moedas")
    @app_commands.guild_only()
    async def nivel(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        membro = membro or interaction.user
        prof = await self.bot.db.profile(interaction.guild_id, membro.id)
        lvl = util.level_from_xp(prof["xp"])
        cur, nxt = util.xp_for_level(lvl), util.xp_for_level(lvl + 1)
        filled = int((prof["xp"] - cur) / (nxt - cur) * 10)
        bar = "🟩" * filled + "⬛" * (10 - filled)
        embed = discord.Embed(title=f"⭐ {membro.display_name}", color=0x2ECC71)
        embed.set_thumbnail(url=membro.display_avatar.url)
        embed.add_field(name="Nível", value=str(lvl))
        embed.add_field(name="XP", value=f"{prof['xp']}/{nxt}")
        embed.add_field(name="Moedas", value=f"{prof['coins']} {COIN}")
        embed.add_field(name="Progresso", value=bar, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="top", description="Ranking de XP ou moedas do servidor")
    @app_commands.choices(tipo=[app_commands.Choice(name="XP", value="xp"),
                                app_commands.Choice(name="Moedas", value="coins")])
    @app_commands.guild_only()
    async def top(self, interaction: discord.Interaction, tipo: app_commands.Choice[str] | None = None):
        col = tipo.value if tipo else "xp"
        rows = await self.bot.db.fetchall(
            f"SELECT user_id, xp, coins FROM profiles WHERE guild_id=? ORDER BY {col} DESC LIMIT 10",
            (interaction.guild_id,))
        if not rows:
            raise UserError("Ninguém tem XP ainda. Bora conversar!")
        lines = [f"`{i + 1:>2}.` <@{r['user_id']}> — " +
                 (f"nível {util.level_from_xp(r['xp'])} ({r['xp']} XP)" if col == "xp" else f"{r['coins']} {COIN}")
                 for i, r in enumerate(rows)]
        await interaction.response.send_message(
            embed=discord.Embed(title=f"🏅 Top {'XP' if col == 'xp' else 'moedas'}",
                                description="\n".join(lines), color=0x2ECC71),
            allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="diario", description=f"Pega suas moedas diárias")
    @app_commands.guild_only()
    async def diario(self, interaction: discord.Interaction):
        prof = await self.bot.db.profile(interaction.guild_id, interaction.user.id)
        wait = prof["last_daily_ts"] + 20 * 3600 - time.time()
        if wait > 0:
            raise UserError(f"Você já pegou hoje. Volte <t:{int(time.time() + wait)}:R>.")
        await self.bot.db.touch(interaction.guild_id, interaction.user.id, "last_daily_ts")
        await util.give_xp(self.bot, interaction.guild, interaction.user, 20, 200, interaction.channel)
        await interaction.response.send_message(f"🎁 Você ganhou **200 {COIN}** e 20 XP!")

    # ------------------------------------------------------------ apostas
    async def get_bet(self, guild_id: int, bet_id: int):
        bet = await self.bot.db.fetchone("SELECT * FROM bets WHERE id=? AND guild_id=?", (bet_id, guild_id))
        if not bet:
            raise UserError(f"Aposta #{bet_id} não encontrada.")
        return bet

    async def refresh_bet_message(self, guild: discord.Guild, bet, view_enabled: bool):
        channel = guild.get_channel(bet["channel_id"])
        if not channel:
            return
        try:
            msg = await channel.fetch_message(bet["message_id"])
            await msg.edit(embed=await bet_embed(self.bot, bet), view=BetView() if view_enabled else None)
        except discord.HTTPException:
            pass

    @aposta.command(name="criar", description="Cria uma aposta (ex.: LOUD x paiN)")
    @app_commands.describe(titulo="Ex.: Final do CBLOL", opcao_1="Ex.: LOUD", opcao_2="Ex.: paiN")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def aposta_criar(self, interaction: discord.Interaction, titulo: str, opcao_1: str, opcao_2: str):
        bet_id = await self.bot.db.execute(
            "INSERT INTO bets (guild_id, title, option_a, option_b, channel_id) VALUES (?,?,?,?,?)",
            (interaction.guild_id, titulo, opcao_1, opcao_2, interaction.channel_id))
        bet = await self.get_bet(interaction.guild_id, bet_id)
        await interaction.response.send_message(embed=await bet_embed(self.bot, bet), view=BetView())
        msg = await interaction.original_response()
        await self.bot.db.execute("UPDATE bets SET message_id=? WHERE id=?", (msg.id, bet_id))

    @aposta.command(name="fechar", description="Fecha para novas apostas (quando o jogo começar)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def aposta_fechar(self, interaction: discord.Interaction, id: int):
        await self.get_bet(interaction.guild_id, id)
        await self.bot.db.execute("UPDATE bets SET status='fechada' WHERE id=?", (id,))
        bet = await self.get_bet(interaction.guild_id, id)
        await self.refresh_bet_message(interaction.guild, bet, False)
        await interaction.response.send_message(f"🔒 Apostas da #{id} fechadas!")

    @aposta.command(name="encerrar", description="Define o vencedor e paga as apostas")
    @app_commands.choices(vencedor=[app_commands.Choice(name="1ª opção", value="a"),
                                    app_commands.Choice(name="2ª opção", value="b")])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def aposta_encerrar(self, interaction: discord.Interaction, id: int, vencedor: app_commands.Choice[str]):
        bet = await self.get_bet(interaction.guild_id, id)
        if bet["status"] in ("encerrada", "cancelada"):
            raise UserError("Essa aposta já foi finalizada.")
        wagers = await self.bot.db.fetchall("SELECT * FROM wagers WHERE bet_id=?", (id,))
        pot = sum(w["amount"] for w in wagers)
        winners = [w for w in wagers if w["option"] == vencedor.value]
        win_total = sum(w["amount"] for w in winners)
        payouts = []
        if winners:
            for w in winners:
                prize = w["amount"] * pot // win_total
                await self.bot.db.add_profile(interaction.guild_id, w["user_id"], coins=prize)
                payouts.append((prize, w["user_id"]))
        else:  # ninguém acertou: devolve tudo
            for w in wagers:
                await self.bot.db.add_profile(interaction.guild_id, w["user_id"], coins=w["amount"])
        await self.bot.db.execute("UPDATE bets SET status='encerrada', winner=? WHERE id=?", (vencedor.value, id))
        bet = await self.get_bet(interaction.guild_id, id)
        await self.refresh_bet_message(interaction.guild, bet, False)
        name = bet["option_a"] if vencedor.value == "a" else bet["option_b"]
        if payouts:
            top = "\n".join(f"• <@{u}> +{p} {COIN}" for p, u in sorted(payouts, reverse=True)[:10])
            text = f"🏁 **{name}** venceu! Pote de {pot} {COIN} dividido:\n{top}"
        else:
            text = f"🏁 **{name}** venceu! Ninguém apostou nele, então todo mundo recebeu o dinheiro de volta."
        await interaction.response.send_message(text)

    @aposta.command(name="cancelar", description="Cancela a aposta e devolve as moedas")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def aposta_cancelar(self, interaction: discord.Interaction, id: int):
        bet = await self.get_bet(interaction.guild_id, id)
        if bet["status"] in ("encerrada", "cancelada"):
            raise UserError("Essa aposta já foi finalizada.")
        for w in await self.bot.db.fetchall("SELECT * FROM wagers WHERE bet_id=?", (id,)):
            await self.bot.db.add_profile(interaction.guild_id, w["user_id"], coins=w["amount"])
        await self.bot.db.execute("UPDATE bets SET status='cancelada' WHERE id=?", (id,))
        await self.refresh_bet_message(interaction.guild, await self.get_bet(interaction.guild_id, id), False)
        await interaction.response.send_message(f"🚫 Aposta #{id} cancelada, moedas devolvidas.")


async def setup(bot):
    await bot.add_cog(Diversao(bot))
