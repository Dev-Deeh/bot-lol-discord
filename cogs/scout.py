"""/scout: analisa os 5 jogadores de um time adversário e sugere bans.

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
RECENT = 10                      # ranqueadas analisadas por jogador
CACHE_TTL = 20 * 60              # resultado de cada jogador vale 20 min (a chave da Riot permite ~100 consultas/2 min)
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
    return players[:5]


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
    for m in matches:
        p = next((x for x in m["info"]["participants"] if x["puuid"] == puuid), None)
        if not p:
            continue
        c = champs[p["championId"]]
        c["games"] += 1
        c["wins"] += int(p["win"])
        c["k"] += p["kills"]; c["d"] += p["deaths"]; c["a"] += p["assists"]
        if p.get("teamPosition"):
            roles[p["teamPosition"]] += 1
    return {"riot_id": f"{acc['gameName']}#{acc['tagLine']}", "solo": solo, "masteries": masteries,
            "champs": dict(champs), "games": sum(c["games"] for c in champs.values()),
            "role": ROLE_PT.get(roles.most_common(1)[0][0]) if roles else None}


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
        head = f"{pl['riot_id']}" + (f" · {pl['role']}" if pl["role"] else "")
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
        cands = ban_suggestions(results, self.bot.ddragon)
        must, extra = split_bans(cands)
        try:
            img = await render_scout(self.bot.cards, results, must, extra, RECENT)
        except Exception:
            log.exception("Falha ao desenhar o card do scout; mandando em texto")
            await interaction.edit_original_response(content=None, embed=scout_embed(results, self.bot.ddragon))
            return
        await interaction.edit_original_response(content=None, attachments=[discord.File(img, filename="scout.jpg")])


async def setup(bot):
    await bot.add_cog(Scout(bot))
