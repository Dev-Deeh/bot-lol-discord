"""Reorganiza o servidor do Bloom White para um servidor profissional, só do time.

Uso:  python tools/restructure_bloom_white.py
Lê e atualiza tools/bloom_white_ids.json (criado pelo setup_bloom_white.py).
"""
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_bloom_white import BASE, Api, ow, perms  # noqa: E402

IDS = Path(__file__).resolve().parent / "bloom_white_ids.json"
TEXT, VOICE, CAT = 0, 2, 4
READ_ONLY = ("send", "add_reactions", "public_threads", "send_threads")


async def main():
    ids = json.loads(IDS.read_text(encoding="utf-8"))
    G, R, C = ids["guild"], ids["roles"], ids["channels"]
    async with aiohttp.ClientSession() as s:
        api = Api(s, G)
        everyone = G

        # ---------------------------------------------------------------- cargos
        print("CARGOS")
        await api.req("PATCH", f"/guilds/{G}/roles/{R['🤝 Amigos']}", json={"name": "🤝 Convidado"})
        R["🤝 Convidado"] = R.pop("🤝 Amigos")
        print("  ~ 🤝 Amigos -> 🤝 Convidado")
        if "📊 Analista" not in R:
            r = await api.req("POST", f"/guilds/{G}/roles", json={
                "name": "📊 Analista", "color": 0xB8C9DE, "hoist": True, "mentionable": True,
                "permissions": perms(*BASE, "manage_messages")})
            R["📊 Analista"] = r["id"]
            print("  + 📊 Analista")
        roles = await api.req("GET", f"/guilds/{G}/roles")
        bot_role = next(r["id"] for r in roles if r["managed"] and r["name"] == "Bot Deeh LOL")
        order = [bot_role, R["👑 Capitão"], R["🎓 Coach"], R["📊 Analista"], R["🛡️ Titular"], R["🔁 Reserva"],
                 R["🤝 Convidado"], R["🤖 Bots"]]
        await api.req("PATCH", f"/guilds/{G}/roles", json=[{"id": rid, "position": len(order) - i}
                                                           for i, rid in enumerate(order)])
        cap, coach, ana, tit, res, guest, bots = (R[n] for n in ("👑 Capitão", "🎓 Coach", "📊 Analista",
                                                                 "🛡️ Titular", "🔁 Reserva", "🤝 Convidado",
                                                                 "🤖 Bots"))
        team = (cap, coach, ana, tit, res)
        staff_roles = (cap, coach, ana)

        # ---------------------------------------------------------------- permissões
        TEAM_ONLY = [ow(everyone, deny=("view",)), ow(guest, deny=("view", "connect"))] + \
                    [ow(r, allow=("view", "connect")) for r in team]
        OFFICIAL = [ow(everyone, deny=("view",)), ow(guest, allow=("view",), deny=READ_ONLY)] + \
                   [ow(r, allow=("view",), deny=READ_ONLY) for r in (ana, tit, res)] + \
                   [ow(r, allow=("view", "send", "mention_everyone")) for r in (cap, coach)]
        LEAGUE_RO = [ow(everyone, deny=("view",)), ow(guest, allow=("view",), deny=READ_ONLY)] + \
                    [ow(r, allow=("view",), deny=READ_ONLY) for r in team] + [ow(bots, allow=("send", "embed"))]
        LEAGUE_CMD = [ow(everyone, deny=("view",)), ow(guest, allow=("view", "send"))] + \
                     [ow(r, allow=("view", "send")) for r in team]
        STAFF = [ow(everyone, deny=("view",)), ow(guest, deny=("view", "connect")),
                 ow(tit, deny=("view", "connect")), ow(res, deny=("view", "connect"))] + \
                [ow(r, allow=("view", "connect")) for r in staff_roles]
        RULES = [ow(everyone, allow=("view", "history"), deny=READ_ONLY)]
        OPPONENT = TEAM_ONLY[:1] + [ow(guest, allow=("view", "connect", "speak", "stream"))] + TEAM_ONLY[2:]

        chans = {c["id"]: c for c in await api.req("GET", f"/guilds/{G}/channels")}
        cat_of = {c["name"]: c["id"] for c in chans.values() if c["type"] == CAT}

        async def edit(cid, **body):
            await api.req("PATCH", f"/channels/{cid}", json=body)

        async def delete(key):
            cid = C.pop(key, None)
            if cid and cid in chans:
                await api.req("DELETE", f"/channels/{cid}")
                print("  - removido:", chans[cid]["name"])

        # ---------------------------------------------------------------- remove o que não é do time
        print("LIMPEZA")
        for key in ("memes", "duo", "v_duo1", "v_duo2", "v_flex", "boas_vindas", "criar_sala"):
            await delete(key)
        await api.req("PATCH", f"/guilds/{G}", json={"system_channel_id": None})

        # ---------------------------------------------------------------- categorias
        print("CATEGORIAS")
        official = cat_of["📢 INFORMAÇÕES"]
        competitive = cat_of["💎 BLOOM WHITE"]
        team_cat = cat_of["💬 COMUNIDADE"]
        league = cat_of["🎮 LEAGUE"]
        voice = cat_of["🔊 VOZ"]
        staff = cat_of["🎓 STAFF"]
        layout = [(official, "💎 BLOOM WHITE", OFFICIAL), (competitive, "🏆 COMPETITIVO", TEAM_ONLY),
                  (team_cat, "💬 TIME", TEAM_ONLY), (league, "🌍 LEAGUE", LEAGUE_CMD),
                  (voice, "🔊 VOZ", TEAM_ONLY), (staff, "🎓 STAFF", STAFF)]
        for pos, (cid, name, owr) in enumerate(layout):
            await edit(cid, name=name, permission_overwrites=owr, position=pos)
            print("  ~", name)

        # ---------------------------------------------------------------- canais existentes
        print("CANAIS")

        async def place(key, name, parent, owr, pos, **extra):
            await edit(C[key], name=name, parent_id=parent, permission_overwrites=owr, position=pos, **extra)
            print("  ~", name)

        async def create(key, name, type_, parent, owr, pos, **extra):
            C[key] = await api.channel(name, type_, parent, owr, position=pos, **extra)

        # 💎 BLOOM WHITE (oficial)
        await place("regras", "📜・regras", official, RULES, 0)
        await place("avisos", "📢・avisos", official, OFFICIAL, 1)
        await place("noticias", "📰・notícias", official, OFFICIAL, 2,
                    topic="Agenda, scrims e jogos oficiais direto do app do Bloom White")
        await place("agenda", "📅・agenda", official, OFFICIAL, 3, topic="Calendário de treinos, scrims e campeonatos")

        # 🏆 COMPETITIVO
        await place("scrims", "⚔️・scrims", competitive, TEAM_ONLY, 0, topic="Marcação, adversários e combinados das scrims")
        await place("conquistas", "🏆・resultados", competitive, TEAM_ONLY, 1,
                    topic="Placar, MVP e observações de cada jogo")
        C["resultados"] = C.pop("conquistas")
        if "scout" not in C:
            await create("scout", "🔍・scout", TEXT, competitive, TEAM_ONLY, 2,
                         topic="Adversários: Riot IDs, mains, tendências e links do OP.GG")
        await place("draft", "📋・draft", competitive, TEAM_ONLY, 3, topic="Picks, bans e planos por adversário")
        await place("estrategia", "🧠・estratégia", competitive, TEAM_ONLY, 4,
                    topic="Composições, macro, rotas e calls")
        await place("vods", "🎥・vod-review", competitive, TEAM_ONLY, 5,
                    topic="Replays com o minuto e o que analisar")
        await place("camp", "🏕️・bootcamp", competitive, TEAM_ONLY, 6, topic="Planejamento e cronograma do bootcamp")

        # 💬 TIME
        await place("geral", "💬・geral", team_cat, TEAM_ONLY, 0, topic="Papo do time")
        await place("clipes", "🎬・clipes", team_cat, TEAM_ONLY, 1, topic="Jogadas, highlights e momentos do time")

        # 🌍 LEAGUE
        if "lolnews" not in C:
            await create("lolnews", "🗞️・lol-news", TEXT, league, LEAGUE_RO, 0,
                         topic="Notícias oficiais do League of Legends e do cenário competitivo")
        if "patch" not in C:
            await create("patch", "🛠️・patch-notes", TEXT, league, LEAGUE_RO, 1,
                         topic="Notas de atualização oficiais assim que saem")
        await place("elo", "📈・elo", league, LEAGUE_RO, 2, topic="Quem subiu e quem caiu de elo (automático)")
        await place("partidas", "🎯・partidas", league, LEAGUE_RO, 3, topic="Resumo de cada ranked do time (automático)")
        await place("comandos", "🤖・comandos", league, LEAGUE_CMD, 4, topic="/perfil, /partida, /ranking, /vincular")

        # 🔊 VOZ
        await place("v_treino", "🎙️ Treino", voice, TEAM_ONLY, 0)
        await place("v_scrim1", "⚔️ Scrim", voice, TEAM_ONLY, 1)
        await place("v_scrim2", "🤝 Sala do Adversário", voice, OPPONENT, 2)
        C["v_adversario"] = C.pop("v_scrim2")
        await place("v_camp", "🏕️ Bootcamp", voice, TEAM_ONLY, 3)
        await place("v_geral", "🎧 Lounge", voice, TEAM_ONLY, 4)
        await place("v_afk", "💤 AFK", voice, TEAM_ONLY, 5)

        # 🎓 STAFF
        await place("staff", "🔒・staff", staff, STAFF, 0, topic="Capitão, Coach e Analista")
        await place("v_reuniao", "🔒 Reunião", staff, STAFF, 1)

        # categorias que ficaram vazias
        for name in ("💎 BEM-VINDO", "🔒 SALAS PRIVADAS"):
            if name in cat_of:
                await api.req("DELETE", f"/channels/{cat_of[name]}")
                print("  - categoria removida:", name)
        C.pop("cat_salas", None)

        ids["roles"], ids["channels"] = R, C
        IDS.write_text(json.dumps(ids, indent=2, ensure_ascii=False), encoding="utf-8")
        print("OK")


if __name__ == "__main__":
    asyncio.run(main())
