"""Divide o servidor em dois times: Bloom White (atual) e Bloom Red (novo).

- Área comum (todos os times): 📌 BLOOM (regras, avisos), 🌍 LEAGUE, 🎁 JOGOS & PROMOS, 🔊 BLOOM · VOZ (música, AFK),
  🤝 CONVIDADOS e 🎓 STAFF (capitães e coaches dos dois times).
- Cada time só vê a própria área: TIME, COMPETITIVO, TIER LIST, VOZ e PRIVADOS.
- Cria os cargos 🔴 Bloom Red, 👑 Capitão Red e 🎓 Coach Red; Capitão e Coach atuais viram "White".

Uso:  python tools/dois_times.py            (só mostra o que vai fazer)
      python tools/dois_times.py --aplicar  (aplica)
"""
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_bloom_white import Api  # noqa: E402

IDS_FILE = Path(__file__).resolve().parent / "bloom_white_ids.json"
APPLY = "--aplicar" in sys.argv
RED = 0xE84057

# categoria do White -> (novo nome White, nome Red, canais a copiar pro Red)
TEAM_CATS = {
    "💬 TIME": ("💎 WHITE · TIME", "🔴 RED · TIME", True),
    "🏆 COMPETITIVO": ("💎 WHITE · COMPETITIVO", "🔴 RED · COMPETITIVO", True),
    "📝 TIER LIST": ("💎 WHITE · TIER LIST", "🔴 RED · TIER LIST", False),
    "🔊 VOZ": ("💎 WHITE · VOZ", "🔴 RED · VOZ", True),
    "🔒 PRIVADOS": ("💎 WHITE · PRIVADOS", "🔴 RED · PRIVADOS", False),
}
SHARED_CATS = ["💎 BLOOM WHITE", "🌍 LEAGUE", "🎁 JOGOS & PROMOS", "🤝 CONVIDADOS", "🎓 STAFF"]
SHARED_VOICE = "🔊 BLOOM · VOZ"
# canais que saem da área do White e vão pra voz comum
TO_SHARED_VOICE = ("musica", "v_musica", "v_afk")
# canais do app (avisos/agenda automáticos) que passam a ser só do White
TO_WHITE_TIME = ("noticias", "agenda")


def log(*a):
    print(("  " if APPLY else "  [prévia] ") + " ".join(str(x) for x in a))


async def main():
    ids = json.loads(IDS_FILE.read_text(encoding="utf-8"))
    g = ids["guild"]
    async with aiohttp.ClientSession() as s:
        api = Api(s, g)
        roles = {r["name"]: r for r in await api.req("GET", f"/guilds/{g}/roles")}
        chans = await api.req("GET", f"/guilds/{g}/channels")
        by_id = {c["id"]: c for c in chans}
        cats = {c["name"]: c for c in chans if c["type"] == 4}

        async def call(method, path, **kw):
            if APPLY:
                return await api.req(method, path, **kw)
            return {"id": f"novo:{path}"}

        # ------------------------------------------------ cargos
        print("Cargos")
        cap, coach, bw = roles.get("👑 Capitão") or roles["👑 Capitão White"], \
            roles.get("🎓 Coach") or roles["🎓 Coach White"], roles["💎 Bloom White"]
        for r, new in ((cap, "👑 Capitão White"), (coach, "🎓 Coach White")):
            if r["name"] != new:
                log("renomear", r["name"], "->", new)
                await call("PATCH", f"/guilds/{g}/roles/{r['id']}", json={"name": new})

        async def make_role(name, like, color):
            if name in roles:
                return roles[name]["id"]
            log("criar cargo", name, "(mesmas permissões de", like["name"] + ")")
            r = await call("POST", f"/guilds/{g}/roles", json={"name": name, "permissions": like["permissions"],
                                                               "color": color, "hoist": like["hoist"],
                                                               "mentionable": like["mentionable"]})
            return r["id"]

        br = await make_role("🔴 Bloom Red", bw, RED)
        cap_r = await make_role("👑 Capitão Red", cap, RED)
        coach_r = await make_role("🎓 Coach Red", coach, 0xF2A3AE)
        mapping = {bw["id"]: br, cap["id"]: cap_r, coach["id"]: coach_r}

        if APPLY:  # ordem: bot, capitães, coaches, times, resto como estava
            allr = sorted(await api.req("GET", f"/guilds/{g}/roles"), key=lambda r: r["position"])
            top = [cap["id"], cap_r, coach["id"], coach_r, bw["id"], br]
            rest = [r["id"] for r in allr if r["id"] not in top and not r["managed"] and r["id"] != g]
            bot_pos = max(r["position"] for r in allr if r["managed"] and r["tags"].get("bot_id") and
                          r["name"].startswith("Bot Deeh"))
            order = rest + top[::-1]
            await api.req("PATCH", f"/guilds/{g}/roles",
                          json=[{"id": rid, "position": i + 1} for i, rid in enumerate(order) if i + 1 < bot_pos])

        def red_overwrites(ows):
            """Copia as permissões do White trocando os cargos do White pelos do Red (sem permissões de pessoas)."""
            out = []
            for o in ows:
                if o["type"] == 1:
                    continue
                out.append({**o, "id": mapping.get(o["id"], o["id"])})
            return out

        def with_red(ows):
            """Área comum: quem do White tem acesso, o equivalente do Red também tem."""
            have = {o["id"] for o in ows}
            extra = [{**o, "id": mapping[o["id"]]} for o in ows if o["id"] in mapping and mapping[o["id"]] not in have]
            return ows + extra

        async def share(ch):
            ows = with_red(ch.get("permission_overwrites", []))
            if len(ows) != len(ch.get("permission_overwrites", [])):
                log("liberar pro Red:", ch["name"])
                await call("PATCH", f"/channels/{ch['id']}", json={"permission_overwrites": ows})

        # ------------------------------------------------ área comum
        print("Área comum")
        top_cat = cats.get("💎 BLOOM WHITE") or cats.get("📌 BLOOM")
        if top_cat["name"] != "📌 BLOOM":
            log("renomear categoria", top_cat["name"], "-> 📌 BLOOM")
            await call("PATCH", f"/channels/{top_cat['id']}", json={"name": "📌 BLOOM"})
        for name in SHARED_CATS:
            cat = cats.get(name) or (top_cat if name == "💎 BLOOM WHITE" else None)
            if not cat:
                continue
            await share(cat)
            for ch in chans:
                if ch.get("parent_id") == cat["id"] and ch["id"] not in {ids["channels"][k] for k in TO_WHITE_TIME}:
                    await share(ch)

        white_voice = cats.get("🔊 VOZ") or cats.get("💎 WHITE · VOZ")
        sv = cats.get(SHARED_VOICE)
        if sv:
            sv_id = sv["id"]
        else:
            log("criar categoria", SHARED_VOICE)
            sv_id = (await call("POST", f"/guilds/{g}/channels", json={
                "name": SHARED_VOICE, "type": 4,
                "permission_overwrites": with_red(white_voice["permission_overwrites"])}))["id"]
        for key in TO_SHARED_VOICE:
            ch = by_id[ids["channels"][key]]
            if ch.get("parent_id") != sv_id:
                log("mover", ch["name"], "->", SHARED_VOICE)
                await call("PATCH", f"/channels/{ch['id']}", json={
                    "parent_id": sv_id, "permission_overwrites": with_red(ch["permission_overwrites"])})

        # ------------------------------------------------ área de cada time
        print("Área de cada time")
        order = [top_cat["id"]]
        red_order = []
        for old, (white_name, red_name, copy) in TEAM_CATS.items():
            wc = cats.get(old) or cats[white_name]
            if wc["name"] != white_name:
                log("renomear categoria", wc["name"], "->", white_name)
                await call("PATCH", f"/channels/{wc['id']}", json={"name": white_name})
            order.append(wc["id"])
            if old == "💬 TIME":
                for key in TO_WHITE_TIME:
                    ch = by_id[ids["channels"][key]]
                    if ch.get("parent_id") != wc["id"]:
                        log("mover", ch["name"], "->", white_name, "(só o White vê: vem do app do White)")
                        await call("PATCH", f"/channels/{ch['id']}", json={"parent_id": wc["id"]})
            rc = cats.get(red_name)
            if rc:
                red_order.append(rc["id"])
                continue
            log("criar categoria", red_name)
            rc_id = (await call("POST", f"/guilds/{g}/channels", json={
                "name": red_name, "type": 4, "permission_overwrites": red_overwrites(wc["permission_overwrites"])}))["id"]
            red_order.append(rc_id)
            if not copy:
                continue
            kids = sorted([c for c in chans if c.get("parent_id") == wc["id"]
                           and c["id"] not in {ids["channels"][k] for k in TO_SHARED_VOICE}],
                          key=lambda c: (c["type"] == 2, c["position"]))
            for ch in kids:
                body = {"name": ch["name"], "type": ch["type"], "parent_id": rc_id,
                        "permission_overwrites": red_overwrites(ch["permission_overwrites"])}
                for k in ("topic", "user_limit", "bitrate", "rate_limit_per_user", "nsfw"):
                    if ch.get(k) is not None:
                        body[k] = ch[k]
                log("  criar", ch["name"], "em", red_name)
                await call("POST", f"/guilds/{g}/channels", json=body)

        # ------------------------------------------------ ordem das categorias
        rest = [cats[n]["id"] for n in ("🌍 LEAGUE", "🎁 JOGOS & PROMOS") if n in cats] + [sv_id] + \
               [cats[n]["id"] for n in ("🤝 CONVIDADOS", "🎓 STAFF") if n in cats]
        final = order + red_order + rest
        log("ordem das categorias:", len(final), "categorias")
        if APPLY:
            await api.req("PATCH", f"/guilds/{g}/channels",
                          json=[{"id": cid, "position": i} for i, cid in enumerate(final)])
            ids["roles"].update({"🔴 Bloom Red": br, "👑 Capitão Red": cap_r, "🎓 Coach Red": coach_r})
            fresh = {c["name"]: c["id"] for c in await api.req("GET", f"/guilds/{g}/channels") if c["type"] == 4}
            ids["channels"].update({"cat_privados_red": fresh["🔴 RED · PRIVADOS"],
                                    "cat_tierlist_red": fresh["🔴 RED · TIER LIST"], "cat_voz_comum": sv_id})
            IDS_FILE.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Pronto. IDs salvos em", IDS_FILE.name)


asyncio.run(main())
