"""Salas de voz enxutas + privados por jogador + espaço dos convidados (Bloom White).

Uso:  python tools/voz_bloom_white.py
Depois, grave no bot as configs que o script imprime (privados:cat, privados:roles, autorole).
"""
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_bloom_white import Api, ow  # noqa: E402

IDS = Path(__file__).resolve().parent / "bloom_white_ids.json"
TEXT, VOICE, CAT = 0, 2, 4


async def main():
    ids = json.loads(IDS.read_text(encoding="utf-8"))
    G, R, C = ids["guild"], ids["roles"], ids["channels"]
    cap, coach, ana, tit, res, guest = (R[n] for n in ("👑 Capitão", "🎓 Coach", "📊 Analista", "🛡️ Titular",
                                                       "🔁 Reserva", "🤝 Convidado"))
    team = (cap, coach, ana, tit, res)
    TEAM_ONLY = [ow(G, deny=("view",)), ow(guest, deny=("view", "connect"))] + \
                [ow(r, allow=("view", "connect")) for r in team]
    WITH_GUESTS = [ow(G, deny=("view",)), ow(guest, allow=("view", "connect", "speak", "stream", "send"))] + \
                  [ow(r, allow=("view", "connect", "speak", "stream", "send")) for r in team]

    async with aiohttp.ClientSession() as s:
        api = Api(s, G)
        chans = {c["id"]: c for c in await api.req("GET", f"/guilds/{G}/channels")}
        cats = {c["name"]: c for c in chans.values() if c["type"] == CAT}
        voice = cats["🔊 VOZ"]["id"]

        async def edit(cid, **body):
            await api.req("PATCH", f"/channels/{cid}", json=body)

        # ---------------- VOZ: só o que o time usa
        print("VOZ")
        for key in ("v_adversario", "v_camp", "v_geral"):
            cid = C.pop(key, None)
            if cid and cid in chans:
                await api.req("DELETE", f"/channels/{cid}")
                print("  - removido:", chans[cid]["name"])
        await edit(C["v_treino"], name="🎮 Ranked 5 · Flex", user_limit=0, position=0, parent_id=voice,
                   permission_overwrites=TEAM_ONLY)
        await edit(C["v_scrim1"], name="🎓 Coach 1:1", user_limit=2, position=1, parent_id=voice,
                   permission_overwrites=TEAM_ONLY)
        await edit(C["v_afk"], position=2, parent_id=voice, permission_overwrites=TEAM_ONLY)
        C["v_time"], C["v_coach"] = C.pop("v_treino"), C.pop("v_scrim1")
        print("  ~ 🎮 Ranked 5 · Flex  ~ 🎓 Coach 1:1 (2 pessoas)  ~ 💤 AFK")

        # ---------------- PRIVADOS: uma sala por jogador (o bot cria e apaga sozinho)
        print("PRIVADOS")
        if "🔒 PRIVADOS" in cats:
            priv = cats["🔒 PRIVADOS"]["id"]
        else:
            priv = await api.channel("🔒 PRIVADOS", CAT, overwrites=TEAM_ONLY)
        C["cat_privados"] = priv

        # ---------------- CONVIDADOS: espaço deles, com o time
        print("CONVIDADOS")
        if "🤝 CONVIDADOS" in cats:
            gcat = cats["🤝 CONVIDADOS"]["id"]
        else:
            gcat = await api.channel("🤝 CONVIDADOS", CAT, overwrites=WITH_GUESTS)
            C["convidados"] = await api.channel("💬・convidados", TEXT, gcat, WITH_GUESTS,
                                                topic="Papo com parceiros de scrim, amigos e visitantes")
            C["v_convidados"] = await api.channel("🤝 Sala dos Convidados", VOICE, gcat, WITH_GUESTS)
        C["cat_convidados"] = gcat

        # ---------------- ordem das categorias
        order = ["💎 BLOOM WHITE", "🏆 COMPETITIVO", "💬 TIME", "🌍 LEAGUE", "🔊 VOZ", "🔒 PRIVADOS",
                 "🤝 CONVIDADOS", "🎓 STAFF"]
        chans = {c["id"]: c for c in await api.req("GET", f"/guilds/{G}/channels")}
        by_name = {c["name"]: c["id"] for c in chans.values() if c["type"] == CAT}
        await api.req("PATCH", f"/guilds/{G}/channels",
                      json=[{"id": by_name[n], "position": i} for i, n in enumerate(order) if n in by_name])

        ids["channels"] = C
        IDS.write_text(json.dumps(ids, indent=2, ensure_ascii=False), encoding="utf-8")
        print("OK")
        print(f"CONFIG privados:cat={priv} privados:roles={','.join(team)} autorole={guest}")


if __name__ == "__main__":
    asyncio.run(main())
