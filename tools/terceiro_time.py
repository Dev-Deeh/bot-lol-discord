"""Cria o terceiro time (Bloom, roxo) espelhando tudo da Bloom Red.

- Cargos: Capitão, Coach, Titular e Reserva Bloom (mesmas permissões dos da Red, cor roxa).
- Em todo canal onde um cargo da Red aparece, o cargo equivalente da Bloom ganha a mesma permissão
  (os três times se veem; a staff continua só pra capitães e coaches).
- Área própria: divisória, TIME, COMPETITIVO, VOZ e TIER LIST, com os mesmos canais da Red.
- Webhooks "Bloom App" no #notícias e no #agenda, gravados num arquivo local (sem imprimir).

Uso: python tools/terceiro_time.py [pasta_do_robo_de_avisos]           (prévia)
     python tools/terceiro_time.py [pasta_do_robo_de_avisos] --aplicar"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv(".env")
APPLY = "--aplicar" in sys.argv
AVISOS = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
G = "1569317259581587517"
API = "https://discord.com/api/v10"
H = {"Authorization": "Bot " + os.environ["DISCORD_TOKEN"], "User-Agent": "DiscordBot (x,1)",
     "Content-Type": "application/json", "X-Audit-Log-Reason": "Terceiro time: Bloom"}
PURPLE = 0x9B6BFF
NEW = "🟣 BLOOM"
ROLE_MAP = {"👑 Capitão Bloom Red": "👑 Capitão Bloom", "🎓 Coach Bloom Red": "🎓 Coach Bloom",
            "🛡️ Titular Bloom Red": "🛡️ Titular Bloom", "🔁 Reserva Bloom Red": "🔁 Reserva Bloom"}


def call(m, p, b=None):
    for _ in range(6):
        r = urllib.request.Request(API + p, method=m, headers=H, data=json.dumps(b).encode() if b is not None else None)
        try:
            with urllib.request.urlopen(r) as x:
                t = x.read()
                return json.loads(t) if t else None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(json.loads(e.read()).get("retry_after", 1) + 0.2)
                continue
            if e.code == 404 and m == "PATCH":
                return None
            raise RuntimeError(f"{m} {p} {e.code}: {e.read()[:300]}")


def do(desc, m, p, b=None, fake=None):
    print(("FAZENDO: " if APPLY else "vai: ") + desc)
    if APPLY:
        res = call(m, p, b)
        time.sleep(0.35)
        return res
    return fake


# ------------------------------------------------------------------ 1) cargos
roles = {r["name"]: r for r in call("GET", f"/guilds/{G}/roles")}
rid = {}
for red, new in ROLE_MAP.items():
    if new in roles:
        rid[roles[red]["id"]] = roles[new]["id"]
        continue
    src = roles[red]
    res = do(f"criar cargo {new}", "POST", f"/guilds/{G}/roles",
             {"name": new, "permissions": src["permissions"], "color": PURPLE, "hoist": src["hoist"],
              "mentionable": src["mentionable"]}, fake={"id": f"<{new}>"})
    rid[src["id"]] = res["id"]

# ------------------------------------------------------------------ 2) espelha as permissões da Red
chans = call("GET", f"/guilds/{G}/channels")
for c in chans:
    ows = c["permission_overwrites"]
    have = {o["id"] for o in ows}
    add = [{**o, "id": rid[o["id"]]} for o in ows if o["id"] in rid and rid[o["id"]] not in have]
    if add:
        do(f"permissões: {c['name']}", "PATCH", f"/channels/{c['id']}", {"permission_overwrites": ows + add})
        if APPLY:
            c["permission_overwrites"] = ows + add


def mirrored(ows):
    have = {o["id"] for o in ows}
    return ows + [{**o, "id": rid[o["id"]]} for o in ows if o["id"] in rid and rid[o["id"]] not in have]


# ------------------------------------------------------------------ 3) área da Bloom (cópia da Red)
cats = {c["name"]: c for c in chans if c["type"] == 4}
made = {}
for red_name in ("━━━━ 🔴 BLOOM RED ━━━━", "🔴 BLOOM RED · TIME", "🔴 BLOOM RED · COMPETITIVO",
                 "🔴 BLOOM RED · VOZ", "🔴 BLOOM RED · TIER LIST"):
    new_name = red_name.replace("🔴 BLOOM RED", NEW)
    src = cats[red_name]
    if new_name in cats:
        made[red_name] = cats[new_name]["id"]
        continue
    res = do(f"criar categoria {new_name}", "POST", f"/guilds/{G}/channels",
             {"name": new_name, "type": 4, "permission_overwrites": mirrored(src["permission_overwrites"])},
             fake={"id": f"<{new_name}>"})
    made[red_name] = res["id"]
    if "TIER LIST" in red_name:
        continue  # os canais de tier list são de cada jogador: o bot cria
    for ch in sorted([x for x in chans if x.get("parent_id") == src["id"]], key=lambda x: (x["type"], x["position"])):
        if ch["name"].startswith("🔒"):
            continue  # sala privada temporária de alguém
        body = {"name": ch["name"], "type": ch["type"], "parent_id": made[red_name],
                "permission_overwrites": mirrored(ch["permission_overwrites"])}
        if ch.get("topic"):
            body["topic"] = ch["topic"].replace("Bloom Red", "Bloom")
        if ch["type"] == 2:
            body["user_limit"] = ch.get("user_limit", 0)
            body["bitrate"] = ch.get("bitrate", 64000)
        res = do(f"  criar {ch['name']} em {new_name}", "POST", f"/guilds/{G}/channels", body,
                 fake={"id": "<novo>", "name": ch["name"]})
        if ch["name"] in ("📰・notícias", "📅・agenda") and APPLY and AVISOS:
            hook = call("POST", f"/channels/{res['id']}/webhooks", {"name": "Bloom App"})
            secret = "BLM_DISCORD_WEBHOOK" if "notícias" in ch["name"] else "BLM_DISCORD_AGENDA_WEBHOOK"
            with open(os.path.join(AVISOS, ".blm-webhooks.local"), "a", encoding="utf-8") as f:
                f.write(f"{secret}=https://discord.com/api/webhooks/{hook['id']}/{hook['token']}\n")
            print(f"  {secret} guardado no arquivo local")

# ------------------------------------------------------------------ 4) ordem: Bloom, White, Red, Resenha, Staff
if APPLY:
    chans = call("GET", f"/guilds/{G}/channels")
    cats = sorted([c for c in chans if c["type"] == 4], key=lambda c: c["position"])
    first = [c for c in cats if "BLOOM ·" not in c["name"] and "━" not in c["name"]
             and c["name"] in ("📌 BLOOM", "🌍 LEAGUE", "🎁 JOGOS & PROMOS")]
    block = lambda tag: [c for c in cats if tag in c["name"]]  # noqa: E731
    order = first + block("🟣 BLOOM") + block("💎 BLOOM WHITE") + block("🔴 BLOOM RED") + \
        [c for c in cats if "RESENHA" in c["name"]] + [c for c in cats if c["name"] == "🎓 STAFF"]
    rest = [c for c in cats if c not in order]
    call("PATCH", f"/guilds/{G}/channels", [{"id": c["id"], "position": i} for i, c in enumerate(order + rest)])
    roles = {r["name"]: r for r in call("GET", f"/guilds/{G}/roles")}
    print("config times (Bloom):",
          f"{roles['🛡️ Titular Bloom']['id']},{roles['🔁 Reserva Bloom']['id']}:"
          f"{made['🔴 BLOOM RED · VOZ']}:{made['🔴 BLOOM RED · TIER LIST']}")
    print("cargos pra marcar nos avisos:", f"{roles['🛡️ Titular Bloom']['id']},{roles['🔁 Reserva Bloom']['id']}")
print("pronto" if APPLY else "fim da prévia")
