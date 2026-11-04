"""Utilidades do servidor: LFG (procurando duo), canais de voz temporários e configuração."""
import discord
from discord import app_commands
from discord.ext import commands

from core import util

CHANNEL_KINDS = [
    app_commands.Choice(name="Alertas de elo (subiu/caiu)", value="alertas"),
    app_commands.Choice(name="Resumo pós-partida", value="partidas"),
    app_commands.Choice(name="Patch notes", value="patch"),
    app_commands.Choice(name="Scrims", value="scrims"),
    app_commands.Choice(name="VOD review", value="vod"),
    app_commands.Choice(name="Avisos de nível", value="niveis"),
]


class LfgView(util.BaseView):
    def __init__(self, owner: discord.Member, mode: str, slots: int, note: str | None):
        super().__init__(timeout=2 * 3600)
        self.owner, self.mode, self.slots, self.note = owner, mode, slots, note
        self.players: list[discord.abc.User] = []
        self.message: discord.Message | None = None

    def embed(self) -> discord.Embed:
        full = len(self.players) >= self.slots
        e = discord.Embed(title=f"🔎 {self.owner.display_name} procura gente pra {self.mode}",
                          description=self.note or "", color=0x95A5A6 if full else 0x2ECC71)
        lines = [f"👑 {self.owner.mention}"] + [f"• {p.mention}" for p in self.players]
        e.add_field(name=f"Grupo ({len(self.players)}/{self.slots} vagas preenchidas)", value="\n".join(lines))
        if full:
            e.set_footer(text="Grupo completo! GLHF")
        return e

    @discord.ui.button(label="Entrar", emoji="🙋", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.owner.id or interaction.user in self.players:
            return await interaction.response.send_message("Você já está no grupo.", ephemeral=True)
        if len(self.players) >= self.slots:
            return await interaction.response.send_message("Grupo cheio!", ephemeral=True)
        self.players.append(interaction.user)
        full = len(self.players) >= self.slots
        if full:
            for item in self.children:
                item.disabled = True
            self.stop()
        await interaction.response.edit_message(embed=self.embed(), view=self)
        if full:
            mentions = " ".join(p.mention for p in [self.owner, *self.players])
            await interaction.followup.send(f"✅ Grupo fechado! {mentions} — bora pro jogo!")

    @discord.ui.button(label="Sair", emoji="🚪", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.players:
            return await interaction.response.send_message("Você não está no grupo.", ephemeral=True)
        self.players.remove(interaction.user)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Utilidades(commands.Cog):
    config = app_commands.Group(name="config", description="Configurações do bot (admins)", guild_only=True,
                                default_permissions=discord.Permissions(manage_guild=True))

    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------ /lfg
    @app_commands.command(name="lfg", description="Procura gente pra jogar (duo, flex, 5x5...)")
    @app_commands.describe(modo="Ex.: Duo Solo/Duo, Flex, ARAM, Clash", vagas="Quantas pessoas faltam",
                           descricao="Ex.: preciso de um sup, sou ouro")
    @app_commands.guild_only()
    async def lfg(self, interaction: discord.Interaction, modo: str, vagas: app_commands.Range[int, 1, 9] = 1,
                  descricao: str | None = None):
        view = LfgView(interaction.user, modo, vagas, descricao)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()

    # ------------------------------------------------------------ voz temporária
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState):
        if after.channel and after.channel != before.channel:
            creator = await self.bot.db.get_config(member.guild.id, "voz_criador")
            if creator and int(creator) == after.channel.id:
                try:
                    new = await member.guild.create_voice_channel(
                        f"🎮 Sala de {member.display_name}"[:100], category=after.channel.category,
                        reason="Canal de voz temporário")
                    await self.bot.db.execute("INSERT INTO temp_voice (channel_id, guild_id) VALUES (?,?)",
                                              (new.id, member.guild.id))
                    await member.move_to(new)
                except discord.HTTPException:
                    pass
        if before.channel and before.channel != after.channel and not before.channel.members:
            row = await self.bot.db.fetchone("SELECT 1 FROM temp_voice WHERE channel_id=?", (before.channel.id,))
            if row:
                await self.bot.db.execute("DELETE FROM temp_voice WHERE channel_id=?", (before.channel.id,))
                try:
                    await before.channel.delete(reason="Canal temporário vazio")
                except discord.HTTPException:
                    pass

    # ------------------------------------------------------------ /config
    @config.command(name="canal", description="Escolhe o canal de um tipo de aviso")
    @app_commands.choices(tipo=CHANNEL_KINDS)
    @app_commands.describe(canal="Deixe vazio para desativar")
    async def config_canal(self, interaction: discord.Interaction, tipo: app_commands.Choice[str],
                           canal: discord.TextChannel | None = None):
        await self.bot.db.set_config(interaction.guild_id, f"canal:{tipo.value}", canal.id if canal else None)
        text = f"em {canal.mention}" if canal else "**desativado**"
        await interaction.response.send_message(f"✅ {tipo.name}: {text}", ephemeral=True)

    @config.command(name="voz", description="Canal 'Criar sala': quem entrar ganha uma call temporária")
    @app_commands.describe(canal="Deixe vazio para desativar")
    async def config_voz(self, interaction: discord.Interaction, canal: discord.VoiceChannel | None = None):
        await self.bot.db.set_config(interaction.guild_id, "voz_criador", canal.id if canal else None)
        text = f"Quem entrar em {canal.mention} ganha uma sala própria." if canal else "Salas temporárias desativadas."
        await interaction.response.send_message(f"✅ {text}", ephemeral=True)

    @config.command(name="cargo-nivel", description="Dá um cargo automaticamente ao chegar num nível")
    @app_commands.describe(cargo="Deixe vazio para remover a recompensa desse nível")
    async def config_cargo_nivel(self, interaction: discord.Interaction, nivel: app_commands.Range[int, 1, 100],
                                 cargo: discord.Role | None = None):
        await self.bot.db.set_config(interaction.guild_id, f"cargo_nivel:{nivel}", cargo.id if cargo else None)
        text = f"nível {nivel} → {cargo.mention}" if cargo else f"recompensa do nível {nivel} removida"
        await interaction.response.send_message(f"✅ {text}", ephemeral=True)

    @config.command(name="ver", description="Mostra a configuração atual")
    async def config_ver(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetchall("SELECT key, value FROM guild_config WHERE guild_id=?",
                                          (interaction.guild_id,))
        cfg = {r["key"]: r["value"] for r in rows}
        lines = [f"**{c.name}:** " + (f"<#{cfg['canal:' + c.value]}>" if f"canal:{c.value}" in cfg else "—")
                 for c in CHANNEL_KINDS]
        lines.append("**Criar sala de voz:** " + (f"<#{cfg['voz_criador']}>" if "voz_criador" in cfg else "—"))
        levels = sorted((int(k.split(":")[1]), v) for k, v in cfg.items() if k.startswith("cargo_nivel:"))
        lines.append("**Cargos por nível:** " + (", ".join(f"{n} → <@&{v}>" for n, v in levels) or "—"))
        await interaction.response.send_message(
            embed=discord.Embed(title="⚙️ Configuração", description="\n".join(lines), color=0x95A5A6),
            ephemeral=True)


async def setup(bot):
    await bot.add_cog(Utilidades(bot))
