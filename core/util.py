"""Funções auxiliares usadas por vários módulos."""
import datetime as dt
import logging
import math
import re
import unicodedata
from zoneinfo import ZoneInfo

import discord

log = logging.getLogger("bot.util")
TZ = ZoneInfo("America/Sao_Paulo")


class UserError(Exception):
    """Erro com mensagem amigável que é mostrada direto para quem usou o comando."""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


# ---------------------------------------------------------------- elo
TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
         "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
TIER_PT = {"IRON": "Ferro", "BRONZE": "Bronze", "SILVER": "Prata", "GOLD": "Ouro",
           "PLATINUM": "Platina", "EMERALD": "Esmeralda", "DIAMOND": "Diamante",
           "MASTER": "Mestre", "GRANDMASTER": "Grão-Mestre", "CHALLENGER": "Desafiante"}
RANKS = ["IV", "III", "II", "I"]
DEFAULT_SCORE = 900  # usado para quem não tem elo vinculado (≈ Prata III)


def elo_score(tier, rank, lp) -> int | None:
    if not tier or tier not in TIERS:
        return None
    ti = TIERS.index(tier)
    if ti >= 7:
        return ti * 400 + (lp or 0)
    return ti * 400 + RANKS.index(rank) * 100 + (lp or 0)


def elo_str(tier, rank, lp) -> str:
    if not tier:
        return "Sem elo"
    name = TIER_PT.get(tier, tier.title())
    if TIERS.index(tier) >= 7:
        return f"{name} ({lp} PDL)"
    return f"{name} {rank} ({lp} PDL)"


def winrate_str(wins, losses) -> str:
    total = (wins or 0) + (losses or 0)
    if not total:
        return "—"
    return f"{wins}V {losses}D ({wins / total * 100:.0f}%)"


def parse_riot_id(text: str):
    if not text or "#" not in text:
        return None
    name, tag = text.rsplit("#", 1)
    name, tag = name.strip(), tag.strip()
    if not name or not tag:
        return None
    return name, tag


# ---------------------------------------------------------------- rotas
LANES = [("Top", "top"), ("Jungle", "jungle"), ("Mid", "mid"), ("ADC", "adc"), ("Suporte", "suporte")]
LANE_NAME = {v: n for n, v in LANES}
LANE_EMOJI = {"top": "🛡️", "jungle": "🌲", "mid": "✨", "adc": "🏹", "suporte": "💖"}


# ---------------------------------------------------------------- datas
WEEKDAYS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}


def parse_when(data: str, hora: str) -> dt.datetime:
    """Aceita data: hoje, amanhã, sexta, sexta-feira, 25/12, 25/12/2026 — e hora: 20h, 20:30, 20h30."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*(?:[:h]\s*(\d{2})?)?\s*h?\s*", hora.lower())
    if not m:
        raise UserError("Hora inválida. Use algo como `20h`, `20:30` ou `20h30`.")
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        raise UserError("Hora inválida.")

    now = dt.datetime.now(TZ)
    d = normalize(data).replace("feira", "")
    if d == "hoje":
        day = now.date()
    elif d == "amanha":
        day = now.date() + dt.timedelta(days=1)
    elif d in WEEKDAYS:
        delta = (WEEKDAYS[d] - now.weekday()) % 7
        day = now.date() + dt.timedelta(days=delta)
        if delta == 0 and dt.time(h, mi) <= now.time():
            day += dt.timedelta(days=7)
    else:
        m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*", data)
        if not m:
            raise UserError("Data inválida. Use `hoje`, `amanhã`, `sexta` ou `25/12`.")
        dd, mm = int(m.group(1)), int(m.group(2))
        yy = int(m.group(3)) if m.group(3) else now.year
        if yy < 100:
            yy += 2000
        try:
            day = dt.date(yy, mm, dd)
        except ValueError:
            raise UserError("Essa data não existe.")
        if not m.group(3) and dt.datetime.combine(day, dt.time(h, mi), TZ) < now:
            day = day.replace(year=yy + 1)

    when = dt.datetime.combine(day, dt.time(h, mi), TZ)
    if when < now:
        raise UserError("Essa data/hora já passou.")
    return when


# ---------------------------------------------------------------- XP
def level_from_xp(xp: int) -> int:
    return int(math.sqrt(max(xp, 0) / 100))


def xp_for_level(level: int) -> int:
    return 100 * level * level


async def get_channel(bot, guild: discord.Guild, kind: str):
    value = await bot.db.get_config(guild.id, f"canal:{kind}")
    return guild.get_channel(int(value)) if value else None


async def give_xp(bot, guild: discord.Guild, member: discord.abc.User, xp: int, coins: int = 0,
                  channel: discord.abc.Messageable | None = None):
    before = await bot.db.profile(guild.id, member.id)
    after = await bot.db.add_profile(guild.id, member.id, xp, coins)
    old, new = level_from_xp(before["xp"]), level_from_xp(after["xp"])
    if new <= old:
        return
    target = await get_channel(bot, guild, "niveis") or channel
    if target:
        try:
            await target.send(f"⬆️ {member.mention} subiu para o **nível {new}**!")
        except discord.HTTPException:
            pass
    # cargos por nível
    if isinstance(member, discord.Member):
        for row in await bot.db.config_prefix(guild.id, "cargo_nivel:"):
            level = int(row["key"].split(":")[1])
            role = guild.get_role(int(row["value"]))
            if role and level <= new and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Nível {new}")
                except discord.HTTPException:
                    log.warning("Sem permissão para dar o cargo %s", role)


async def update_elo_role(guild: discord.Guild, member: discord.Member, tier: str | None):
    """Dá o cargo do elo (ex.: 'Ouro') e tira os outros. Cria os cargos se não existirem."""
    try:
        wanted = TIER_PT.get(tier) if tier else None
        tier_names = set(TIER_PT.values())
        to_remove = [r for r in member.roles if r.name in tier_names and r.name != wanted]
        if to_remove:
            await member.remove_roles(*to_remove, reason="Atualização de elo")
        if wanted:
            role = discord.utils.get(guild.roles, name=wanted)
            if role is None:
                role = await guild.create_role(name=wanted, reason="Cargo de elo automático")
            if role not in member.roles:
                await member.add_roles(role, reason="Atualização de elo")
    except discord.HTTPException as e:
        log.warning("Não consegui atualizar o cargo de elo (%s). O bot tem 'Gerenciar Cargos'?", e)


class BaseView(discord.ui.View):
    """View que mostra mensagens de erro amigáveis em vez de falhar em silêncio."""

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        from core.riot import RiotError
        if isinstance(error, (UserError,)):
            msg = f"⚠️ {error}"
        elif isinstance(error, RiotError):
            msg = f"⚠️ Riot API: {error.message}"
        else:
            log.exception("Erro em botão", exc_info=error)
            msg = "❌ Deu algum erro aqui. Tenta de novo."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
