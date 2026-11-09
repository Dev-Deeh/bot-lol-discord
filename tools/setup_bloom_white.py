"""Monta o servidor do time Bloom White (rodar uma vez): cargos, categorias, canais, permissões e regras.

Uso:  python tools/setup_bloom_white.py <ID do servidor>
Salva os IDs criados em tools/bloom_white_ids.json.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
API = "https://discord.com/api/v10"
H = {"Authorization": "Bot " + os.environ["DISCORD_TOKEN"], "User-Agent": "DiscordBot (bot-lol-discord, 1.0)"}

# ---------------------------------------------------------------- permissões (bits)
P = {name: 1 << bit for name, bit in {
    "kick": 1, "add_reactions": 6, "priority": 8, "stream": 9, "view": 10, "send": 11, "manage_messages": 13,
    "embed": 14, "attach": 15, "history": 16, "mention_everyone": 17, "ext_emoji": 18, "connect": 20,
    "speak": 21, "mute": 22, "deafen": 23, "move": 24, "vad": 25, "change_nick": 26, "manage_nick": 27,
    "manage_roles": 28, "app_cmds": 31, "manage_threads": 34, "public_threads": 35, "ext_stickers": 37,
    "send_threads": 38, "activities": 39, "soundboard": 42}.items()}


def perms(*names):
    v = 0
    for n in names:
        v |= P[n]
    return str(v)


BASE = ("view", "send", "send_threads", "public_threads", "embed", "attach", "add_reactions", "ext_emoji",
        "ext_stickers", "history", "app_cmds", "connect", "speak", "stream", "vad", "activities", "soundboard",
        "change_nick")
ROLES = [  # do mais alto pro mais baixo (cor em hex)
    ("🌸 Capitão", 0xF4A6C8, BASE + ("priority", "manage_messages", "mention_everyone", "mute", "deafen", "move",
                                     "manage_nick", "manage_roles", "manage_threads", "kick")),
    ("🎓 Coach", 0xB79CF2, BASE + ("priority", "manage_messages", "mention_everyone", "mute", "deafen", "move")),
    ("🛡️ Titular", 0xEDE7FF, BASE),
    ("🔁 Reserva", 0x9FB4FF, BASE),
    ("🤝 Amigos", 0x7DE3C3, BASE),
    ("🤖 Bots", 0x5865F2, ()),
]

RULES = """**1.** Respeito acima de tudo — nada de ofensas, preconceito ou assédio.
**2.** Sem spam, flood ou divulgação sem permissão.
**3.** Nada de conteúdo +18, gore ou ilegal.
**4.** Tóxico na ranked é uma coisa, aqui não 😄 — zoeira saudável sim, ataque pessoal não.
**5.** Assuntos do time (estratégia, draft, scrims) ficam nos canais do time.
**6.** Respeite a staff (Capitão e Coach) e as decisões do time.
**7.** Siga os [Termos de Serviço](https://discord.com/terms) e as [Diretrizes](https://discord.com/guidelines) do Discord."""


class Api:
    def __init__(self, session, guild):
        self.s, self.g = session, guild

    async def req(self, method, path, **kw):
        for _ in range(5):
            async with self.s.request(method, API + path, headers=H, **kw) as r:
                if r.status == 429:
                    await asyncio.sleep((await r.json()).get("retry_after", 1) + 0.2)
                    continue
                if r.status >= 400:
                    raise RuntimeError(f"{method} {path} -> {r.status}: {await r.text()}")
                return await r.json() if r.status != 204 else None
        raise RuntimeError("rate limit")

    async def channel(self, name, type_, parent=None, overwrites=(), **extra):
        body = {"name": name, "type": type_, "permission_overwrites": list(overwrites), **extra}
        if parent:
            body["parent_id"] = parent
        c = await self.req("POST", f"/guilds/{self.g}/channels", json=body)
        print("  +", name)
        return c["id"]


def ow(target_id, allow=(), deny=(), member=False):
    return {"id": target_id, "type": 1 if member else 0, "allow": perms(*allow), "deny": perms(*deny)}


async def main(guild_id):
    async with aiohttp.ClientSession() as s:
        api = Api(s, guild_id)
        guild = await api.req("GET", f"/guilds/{guild_id}")
        me = await api.req("GET", "/users/@me")
        owner = guild["owner_id"]
        everyone = guild_id  # o @everyone tem o mesmo ID do servidor

        # ---------- limpa os canais padrão do Discord (servidor novo)
        for c in await api.req("GET", f"/guilds/{guild_id}/channels"):
            if c["name"] in ("geral", "Geral", "Canais de Texto", "Canais de Voz", "general", "General",
                             "Text Channels", "Voice Channels"):
                await api.req("DELETE", f"/channels/{c['id']}")
                print("  - padrão:", c["name"])

        # ---------- cargos
        print("CARGOS")
        await api.req("PATCH", f"/guilds/{guild_id}/roles/{everyone}", json={"permissions": "0"})
        R = {}
        for name, color, ps in ROLES:
            r = await api.req("POST", f"/guilds/{guild_id}/roles",
                              json={"name": name, "color": color, "hoist": name != "🤖 Bots", "mentionable": True,
                                    "permissions": perms(*ps)})
            R[name] = r["id"]
            print("  +", name)
        cap, coach, tit, res, ami, bots = (R[n] for n, _, _ in ROLES)
        team = (cap, coach, tit, res)
        await api.req("PUT", f"/guilds/{guild_id}/members/{me['id']}/roles/{bots}")
        for role in (cap, ami):
            await api.req("PUT", f"/guilds/{guild_id}/members/{owner}/roles/{role}")

        # ---------- canais
        print("CANAIS")
        C = {}
        read_only = ("send", "add_reactions", "public_threads", "send_threads")

        cat = await api.channel("🌸 BEM-VINDO", 4, overwrites=[
            ow(everyone, allow=("view", "history"), deny=read_only)])
        C["regras"] = await api.channel("📜・regras", 0, cat, [ow(everyone, allow=("view", "history"), deny=read_only)],
                                        topic="Leia e clique no botão para liberar o servidor 🌸")
        C["boas_vindas"] = await api.channel("👋・boas-vindas", 0, cat,
                                             [ow(everyone, allow=("view", "history"), deny=read_only)])

        staff_post = [ow(ami, deny=read_only), ow(tit, deny=read_only), ow(res, deny=read_only),
                      ow(cap, allow=("send", "mention_everyone")), ow(coach, allow=("send", "mention_everyone"))]
        cat = await api.channel("📢 INFORMAÇÕES", 4, overwrites=staff_post)
        for key, name, topic in (("avisos", "📢・avisos", "Avisos oficiais do Bloom White"),
                                 ("agenda", "📅・agenda", "Treinos, scrims e campeonatos"),
                                 ("conquistas", "🏆・conquistas", "Vitórias, títulos e momentos épicos do time")):
            C[key] = await api.channel(name, 0, cat, staff_post, topic=topic)

        cat = await api.channel("💬 COMUNIDADE", 4)
        for key, name, topic in (("geral", "💬・geral", "Papo livre 🌸"), ("memes", "😂・memes", None),
                                 ("clipes", "🎬・clipes", "Jogadas, pentas e fails"),
                                 ("duo", "🔎・procurando-duo", "Procure gente pra jogar — use /lfg ou mande aqui")):
            C[key] = await api.channel(name, 0, cat, (), **({"topic": topic} if topic else {}))

        bot_only = [ow(ami, deny=read_only), ow(tit, deny=read_only), ow(res, deny=read_only),
                    ow(coach, deny=read_only), ow(bots, allow=("send", "embed", "attach"))]
        cat = await api.channel("🎮 LEAGUE", 4)
        C["comandos"] = await api.channel("🤖・comandos", 0, cat, (), topic="Use /perfil, /partida, /ranking, /vincular")
        C["elo"] = await api.channel("📈・elo", 0, cat, bot_only, topic="Alertas automáticos: quem subiu e quem caiu")
        C["partidas"] = await api.channel("🎯・partidas", 0, cat, bot_only, topic="Resumo automático de cada ranked")

        team_only = [ow(everyone, deny=("view",)), ow(ami, deny=("view", "connect"))] + \
                    [ow(r, allow=("view", "connect")) for r in team]
        cat = await api.channel("🌸 BLOOM WHITE", 4, overwrites=team_only)
        for key, name, topic in (("estrategia", "🧠・estratégia", "Composições, rotas, macro"),
                                 ("draft", "📋・draft", "Picks, bans e preparação contra adversários"),
                                 ("vods", "🎥・vods", "Replays e review — mande o link com o que analisar"),
                                 ("scrims", "⚔️・scrims", "Marcação e resultado das scrims"),
                                 ("camp", "🏕️・camp", "Planejamento do bootcamp")):
            C[key] = await api.channel(name, 0, cat, team_only, topic=topic)
        for key, name in (("v_treino", "🎙️ Treino"), ("v_scrim1", "⚔️ Scrim 1"), ("v_scrim2", "⚔️ Scrim 2"),
                          ("v_camp", "🏕️ Camp")):
            C[key] = await api.channel(name, 2, cat, team_only)

        staff = [ow(everyone, deny=("view",)), ow(ami, deny=("view", "connect")), ow(tit, deny=("view", "connect")),
                 ow(res, deny=("view", "connect")), ow(cap, allow=("view", "connect")),
                 ow(coach, allow=("view", "connect"))]
        cat = await api.channel("🎓 STAFF", 4, overwrites=staff)
        C["staff"] = await api.channel("🔒・staff", 0, cat, staff, topic="Só Capitão e Coach")
        C["v_reuniao"] = await api.channel("🔒 Reunião", 2, cat, staff)

        cat = await api.channel("🔊 VOZ", 4)
        for key, name, limit in (("v_geral", "🎧 Geral", 0), ("v_duo1", "🎮 Duo 1", 2), ("v_duo2", "🎮 Duo 2", 2),
                                 ("v_flex", "🎮 Flex 5v5", 5), ("v_afk", "💤 AFK", 0)):
            C[key] = await api.channel(name, 2, cat, (), user_limit=limit)

        cat = await api.channel("🔒 SALAS PRIVADAS", 4)
        C["criar_sala"] = await api.channel("➕ Criar sala privada", 2, cat, ())
        C["cat_salas"] = cat

        # ---------- configurações do servidor
        await api.req("PATCH", f"/guilds/{guild_id}", json={
            "afk_channel_id": C["v_afk"], "afk_timeout": 900, "system_channel_id": C["boas_vindas"],
            "default_message_notifications": 1, "explicit_content_filter": 2, "verification_level": 1})

        # ---------- mensagens
        embed = {"title": "🌸 Bem-vindo(a) ao Bloom White!", "color": 0xF4A6C8,
                 "description": "Servidor oficial do time **Bloom White** de League of Legends.\n"
                                "Antes de entrar, leia as regras:\n\n" + RULES +
                                "\n\nClique no botão abaixo para **liberar o servidor**. ✨",
                 "footer": {"text": "Bloom White • League of Legends"}}
        await api.req("POST", f"/channels/{C['regras']}/messages", json={
            "embeds": [embed],
            "components": [{"type": 1, "components": [{"type": 2, "style": 3, "label": "Li e aceito as regras",
                                                       "emoji": {"name": "✅"}, "custom_id": f"verify:{ami}"}]}]})
        await api.req("POST", f"/channels/{C['comandos']}/messages", json={"embeds": [{
            "title": "🤖 Comandos do bot", "color": 0xB79CF2,
            "description": "**/vincular** `Nick#TAG` — liga sua conta da Riot e ganha o cargo do seu elo\n"
                           "**/perfil** — seu card com elo e últimas partidas\n"
                           "**/partida** — partida ao vivo (scout!)\n"
                           "**/ranking** — ranking de elo do servidor\n\n"
                           "🔒 **Sala privada:** entre em **➕ Criar sala privada** e use "
                           "`/sala convidar @amigo`, `/sala trancar`, `/sala limite`."}]})
        await api.req("POST", f"/channels/{C['avisos']}/messages", json={"embeds": [{
            "title": "📢 O servidor do Bloom White está no ar!", "color": 0xF4A6C8,
            "description": "Aqui saem os avisos oficiais do time: line-up, scrims, campeonatos e conquistas. 🌸\n"
                           "Fiquem de olho também em **📅・agenda**."}]})

        out = {"guild": guild_id, "roles": R, "channels": C}
        (ROOT / "tools" / "bloom_white_ids.json").write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                                             encoding="utf-8")
        print("OK — IDs salvos em tools/bloom_white_ids.json")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
