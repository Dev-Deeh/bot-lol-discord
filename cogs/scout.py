"""/scout: analisa os jogadores de um time adversário (todos que vierem no link, até 10) e sugere bans.

Aceita o link da multibusca do OP.GG, o texto copiado do saguão ou nicks separados por vírgula.
Os dados vêm da API oficial da Riot (o OP.GG é usado só pra ler os nicks do link):
  - elo Solo/Duo, últimas ranqueadas (campeão, vitória, KDA, rota) e maiores maestrias.
Sugestão de ban: campeão que o jogador joga muito nas últimas partidas e/ou com taxa de vitória alta.
"""
import asyncio
import logging
import re
import time
from collections import Counter, defaultdict
from urllib.parse import parse_qs, unquote, urlparse

import discord
from discord import app_commands
from discord.ext import commands

from core import util
from core.cards_scout import render_scout
from core.riot import RiotError
from core.util import UserError

log = logging.getLogger("bot.scout")
RECENT = 15                      # ranqueadas analisadas por jogador
CACHE_TTL = 20 * 60              # resultado de cada jogador vale 20 min (a chave da Riot permite ~100 consultas/2 min)
MAX_PLAYERS = 10                 # a multibusca do OP.GG aceita até 10
ROLE_PT = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Suporte"}


# ------------------------------------------------------------------ leitura dos nicks
def parse_players(text: str) -> list[tuple[str, str]]:
    """Devolve [(nome, tag)] a partir do link da multibusca, do texto do saguão ou de uma lista."""
    text = text.strip()
    raw = []
    if "op.gg" in text.lower() or text.lower().startswith("http"):
        q = parse_qs(urlparse(text).query)
        for key in ("summoners", "summoner", "names", "query"):
            for v in q.get(key, []):
                raw += unquote(v).split(",")
    if not raw:
        # texto do saguão: "Nome #TAG entrou no saguão" / uma pessoa por linha / vírgulas
        for line in re.split(r"[\n,]+", text):
            line = re.sub(r"\s+(entrou|joined|saiu|left).*$", "", line.strip(), flags=re.I)
            if line:
                raw.append(line)
    players, seen = [], set()
    for item in raw:
        item = unquote(item).strip().strip("+").replace("+", " ")
        if not item:
            continue
        if "#" in item:
            name, tag = item.rsplit("#", 1)
        elif re.search(r"-[A-Za-z0-9]{2,5}$", item):
            name, tag = item.rsplit("-", 1)
        else:
            name, tag = item, "BR1"
        name, tag = name.strip(), tag.strip()
        key = (name.lower(), tag.lower())
        if name and key not in seen:
            seen.add(key)
            players.append((name, tag))
    return players[:MAX_PLAYERS]


# ------------------------------------------------------------------ análise
async def analyze_player(riot, name: str, tag: str) -> dict:
    acc = await riot.account_by_riot_id(name, tag)
    if not acc:
        return {"riot_id": f"{name}#{tag}", "error": "conta não encontrada"}
    puuid = acc["puuid"]
    solo, masteries, ids = await asyncio.gather(riot.solo_entry(puuid), riot.top_masteries(puuid, 3),
                                                riot.match_ids(puuid, count=RECENT, queue=420))
    matches = [m for m in await asyncio.gather(*(riot.match(i) for i in ids)) if m]
    champs = defaultdict(lambda: {"games": 0, "wins": 0, "k": 0, "d": 0, "a": 0})
    roles = Counter()
    form = []                                   # vitórias/derrotas, da mais recente pra mais antiga
    kp = cs = dmg = vision = 0.0
    for m in matches:
        info = m["info"]
        p = next((x for x in info["participants"] if x["puuid"] == puuid), None)
        if not p or info.get("gameDuration", 0) < 300:   # ignora remake
            continue
        c = champs[p["championId"]]
        c["games"] += 1
        c["wins"] += int(p["win"])
        c["k"] += p["kills"]; c["d"] += p["deaths"]; c["a"] += p["assists"]
        form.append(bool(p["win"]))
        if p.get("teamPosition"):
            roles[p["teamPosition"]] += 1
        ch = p.get("challenges", {})
        team_kills = sum(x["kills"] for x in info["participants"] if x["teamId"] == p["teamId"])
        kp += ch.get("killParticipation", (p["kills"] + p["assists"]) / max(team_kills, 1))
        cs += (p["totalMinionsKilled"] + p["neutralMinionsKilled"]) / (info["gameDuration"] / 60)
        dmg += ch.get("teamDamagePercentage", 0)
        vision += ch.get("visionScorePerMinute", p.get("visionScore", 0) / (info["gameDuration"] / 60))
    n = len(form)
    k = sum(c["k"] for c in champs.values()); d = sum(c["d"] for c in champs.values())
    a = sum(c["a"] for c in champs.values())
    return {"riot_id": f"{acc['gameName']}#{acc['tagLine']}", "solo": solo, "masteries": masteries,
            "champs": dict(champs), "games": n, "roles": dict(roles), "form": form,
            "stats": {"kp": kp / n, "cs": cs / n, "dmg": dmg / n, "vision": vision / n,
                      "kda": (k + a) / max(d, 1), "wr": sum(form) / n} if n else None,
            "role": ROLE_PT.get(roles.most_common(1)[0][0]) if roles else None}


def team_read(players: list[dict], must: list[dict]) -> list[tuple[str, str]]:
    """Leitura do time em frases curtas: (título, texto)."""
    ok = [p for p in players if not p.get("error") and p.get("stats")]
    if not ok:
        return []
    name = lambda p: p["riot_id"].split("#")[0]  # noqa: E731
    elo = lambda p: util.elo_score(p["solo"]["tier"], p["solo"]["rank"], p["solo"]["leaguePoints"]) \
        if p.get("solo") else 0  # noqa: E731

    def threat(p):
        s = p["stats"]
        return (elo(p) or 0) / 400 * 0.6 + s["wr"] * 6 + min(s["kda"], 6) + s["dmg"] * 6

    out = []
    strong = max(ok, key=threat)
    s = strong["stats"]
    solo = strong.get("solo")
    tier = (util.TIER_PT.get(solo["tier"], solo["tier"]) + ("" if util.TIERS.index(solo["tier"]) >= 7
            else f" {solo['rank']}")) if solo else "sem elo"
    out.append(("MAIOR AMEAÇA", f"{name(strong)} ({tier}): {s['wr'] * 100:.0f}% de vitória nas últimas, "
                                f"KDA {s['kda']:.1f} e {s['dmg'] * 100:.0f}% do dano do time."))
    weak = min(ok, key=threat)
    if weak is not strong:
        w = weak["stats"]
        out.append(("PONTO FRACO", f"{name(weak)}: {w['wr'] * 100:.0f}% de vitória e KDA {w['kda']:.1f} "
                                   f"nas últimas. É o alvo mais fácil."))
    for p in ok:
        streak = 0
        for won in p["form"]:
            if won != p["form"][0]:
                break
            streak += 1
        if streak >= 4:
            kind = "vitórias" if p["form"][0] else "derrotas"
            out.append(("SEQUÊNCIA", f"{name(p)} está em {streak} {kind} seguidas."))
    for p in ok:
        top_cid, top = max(p["champs"].items(), key=lambda kv: kv[1]["games"])
        if top["games"] / p["games"] >= 0.6 and not any(c["id"] == top_cid and c["player"] == name(p) for c in must):
            out.append(("MONO", f"{name(p)} joga quase só um campeão ({top['games']} de {p['games']}): "
                                f"vale o ban se sobrar."))
    return out[:5]


def ban_suggestions(players: list[dict], dd) -> list[dict]:
    """Pontua cada campeão: quanto o jogador joga dele (recente) e quanto ganha; maestria alta reforça."""
    cands = []
    for pl in players:
        if pl.get("error") or not pl["games"]:
            continue
        top_mastery = {m["championId"]: m["championPoints"] for m in pl["masteries"]}
        for cid, c in pl["champs"].items():
            share = c["games"] / pl["games"]
            wr = (c["wins"] + 1) / (c["games"] + 2)          # suavizado: 1 jogo não vira 100%
            score = share * 100 * (0.5 + wr) + (10 if top_mastery.get(cid, 0) > 200_000 else 0)
            reasons = [f"jogou {c['games']} das últimas {pl['games']}"]
            if c["games"] >= 2:
                reasons.append(f"{c['wins'] / c['games'] * 100:.0f}% de vitória")
            if top_mastery.get(cid, 0) > 200_000:
                reasons.append(f"{top_mastery[cid] // 1000} mil de maestria")
            kda = (c["k"] + c["a"]) / max(c["d"], 1)
            cands.append({"champ": dd.champ_name(cid), "id": cid, "player": pl["riot_id"].split("#")[0],
                          "score": score, "games": c["games"], "total": pl["games"], "share": share, "kda": kda,
                          "wr": c["wins"] / c["games"],
                          "reasons": ", ".join(reasons),
                          "must": c["games"] >= 3 and (share >= 0.4 or c["wins"] / c["games"] >= 0.6)})
    cands.sort(key=lambda x: -x["score"])
    return cands


def split_bans(cands: list[dict]) -> tuple[list[dict], list[dict]]:
    """Bans obrigatórios (até 3) e, se houver, até 2 extras em que o jogador está ganhando."""
    must = [c for c in cands if c["must"]][:3]
    extra = [c for c in cands if not c["must"] and c["wr"] >= 0.5][:2] if must else []
    return must, extra


def scout_embed(players: list[dict], dd) -> discord.Embed:
    e = discord.Embed(title="🔍 Scout do time adversário", color=0xE84057,
                      description=f"Últimas {RECENT} ranqueadas Solo/Duo de cada jogador (API oficial da Riot).")
    for pl in players:
        if pl.get("error"):
            e.add_field(name=f"❓ {pl['riot_id']}", value=pl["error"], inline=False)
            continue
        solo = pl["solo"]
        elo = util.elo_str(solo["tier"], solo["rank"], solo["leaguePoints"]) if solo else "Sem elo"
        wr = f" · {util.winrate_str(solo['wins'], solo['losses'])}" if solo else ""
        head = pl["riot_id"]
        top = sorted(pl["champs"].items(), key=lambda kv: -kv[1]["games"])[:3]
        lines = [f"**{dd.champ_name(cid)}** {c['games']}j {c['wins']}V · KDA {(c['k'] + c['a']) / max(c['d'], 1):.1f}"
                 for cid, c in top] or ["sem ranqueadas recentes"]
        if pl["masteries"]:
            lines.append("Maestria: " + ", ".join(dd.champ_name(m["championId"]) for m in pl["masteries"]))
        e.add_field(name=head, value=f"{elo}{wr}\n" + "\n".join(lines), inline=False)

    cands = ban_suggestions(players, dd)
    must = [c for c in cands if c["must"]][:3]
    if must:
        txt = "\n".join(f"🚫 **{c['champ']}** ({c['player']}): {c['reasons']}" for c in must)
        e.add_field(name="✅ BANIR", value=txt, inline=False)
        # não sugere banir campeão em que a pessoa está perdendo
        rest = [c for c in cands if not c["must"] and c["wr"] >= 0.5][:2]
        if rest:
            e.add_field(name="Se sobrar ban", value="\n".join(f"• **{c['champ']}** ({c['player']}): {c['reasons']}"
                                                              for c in rest), inline=False)
        top_id = dd.by_key.get(must[0]["id"])
        if top_id:
            e.set_thumbnail(url=dd.champ_icon(top_id["id"]))
    else:
        txt = "Ninguém tem um campeão dominante nas últimas partidas. **Não precisa gastar ban em jogador** — " \
              "use os bans nos counters do seu time ou no meta."
        winning = [c for c in cands if c["wr"] >= 0.5]
        if winning:
            txt += "\nMais perigosos: " + ", ".join(f"{c['champ']} ({c['player']})" for c in winning[:3])
        e.add_field(name="🤷 Sem ban obrigatório", value=txt, inline=False)
    e.set_footer(text="Dica: quem joga muito um campeão e ganha bastante com ele é o melhor ban")
    return e


class Scout(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()       # um scout por vez: dois juntos estouram o limite da chave e travam os dois
        self.cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self.waiting = 0

    async def player(self, name: str, tag: str) -> dict:
        key = (name.lower(), tag.lower())
        hit = self.cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1]
        try:
            res = await analyze_player(self.bot.riot, name, tag)
        except RiotError as e:
            if e.status in (0, 401, 403):
                raise
            return {"riot_id": f"{name}#{tag}", "error": f"erro da Riot ({e.status})"}
        if not res.get("error"):
            self.cache[key] = (time.monotonic(), res)
            if len(self.cache) > 100:
                self.cache.pop(next(iter(self.cache)))
        return res

    @app_commands.command(name="scout", description="Analisa um time adversário (link da multibusca do OP.GG) e sugere bans")
    @app_commands.describe(jogadores="Link da multibusca do OP.GG, texto do saguão ou nicks (Nick#TAG) separados por vírgula")
    async def scout(self, interaction: discord.Interaction, jogadores: str):
        players = parse_players(jogadores)
        if not players:
            raise UserError("Não achei nenhum jogador. Cole o link da multibusca do OP.GG ou os nicks no formato Nick#TAG.")
        await interaction.response.defer(thinking=True)

        async def status(text):
            try:
                await interaction.edit_original_response(content=text)
            except discord.HTTPException:
                pass

        if self.lock.locked():
            self.waiting += 1
            await status(f"⏳ Na fila: tem outro scout rodando ({self.waiting} esperando). Já começo o seu.")
        async with self.lock:
            if self.waiting:
                self.waiting -= 1
            await self.bot.ddragon.ensure()
            results = []
            for i, (name, tag) in enumerate(players, 1):  # um por vez: respeita o limite da API
                await status(f"🔎 Analisando {name} ({i}/{len(players)})...")
                results.append(await self.player(name, tag))
        await status("🎨 Montando o card...")
        results = [dict(r) for r in results]   # cópia: o desenho anota coisas no dicionário
        cands = ban_suggestions(results, self.bot.ddragon)
        must, extra = split_bans(cands)
        notes = team_read(results, must)
        try:
            img = await render_scout(self.bot.cards, results, must, extra, RECENT, notes)
        except Exception:
            log.exception("Falha ao desenhar o card do scout; mandando em texto")
            await interaction.edit_original_response(content=None, embed=scout_embed(results, self.bot.ddragon))
            return
        # um embed por imagem: o Discord mostra cada card na largura toda (no máximo 10 por mensagem)
        files = [discord.File(buf, filename=f"scout{i}.jpg") for i, buf in enumerate(img)]
        embeds = []
        for f in files:
            e = discord.Embed(color=0xE84057)
            e.set_image(url=f"attachment://{f.filename}")
            embeds.append(e)
        await interaction.edit_original_response(content=None, embeds=embeds[:10], attachments=files[:10])
        for i in range(10, len(files), 10):
            await interaction.followup.send(embeds=embeds[i:i + 10], files=files[i:i + 10])


async def setup(bot):
    await bot.add_cog(Scout(bot))
