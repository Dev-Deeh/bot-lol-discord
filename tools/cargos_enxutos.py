"""Enxuga os cargos dos times: some "💎 Bloom White" e "🔴 Bloom Red".

Quem é do time agora é quem tem Titular, Reserva, Capitão ou Coach de qualquer um dos dois times.
Os dois times se veem e entram nas salas um do outro; convidados e amigos continuam como estão.
A área da staff continua só pra capitães e coaches.

Uso: python tools/cargos_enxutos.py            (só mostra)
     python tools/cargos_enxutos.py --aplicar"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv(".env")
APPLY = "--aplicar" in sys.argv
G = "1569317259581587517"
API = "https://discord.com/api/v10"
H = {"Authorization": "Bot " + os.environ["DISCORD_TOKEN"], "User-Agent": "DiscordBot (x,1)",
     "Content-Type": "application/json", "X-Audit-Log-Reason": "Cargos enxutos dos times"}
VIEW = 1 << 10


def call(m, p, b=None):
    for _ in range(5):
        r = urllib.request.Request(API + p, method=m, headers=H, data=json.dumps(b).encode() if b is not None else None)
        try:
            with urllib.request.urlopen(r) as x:
                t = x.read()
                return json.loads(t) if t else None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(json.loads(e.read()).get("retry_after", 1) + 0.2)
                continue
            raise RuntimeError(f"{m} {p} {e.code}: {e.read()[:300]}")


def do(desc, m, p, b=None):
    print(("FAZENDO: " if APPLY else "vai: ") + desc)
    if APPLY:
        res = call(m, p, b)
        time.sleep(0.35)
        return res


R = {r["name"]: r["id"] for r in call("GET", f"/guilds/{G}/roles")}
OLD = {R["💎 Bloom White"], R["🔴 Bloom Red"]}
PLAYERS = {R[n] for n in ("🛡️ Titular Bloom White", "🔁 Reserva Bloom White",
                          "🛡️ Titular Bloom Red", "🔁 Reserva Bloom Red")}
STAFF = {R[n] for n in ("👑 Capitão Bloom White", "🎓 Coach Bloom White",
                        "👑 Capitão Bloom Red", "🎓 Coach Bloom Red")}
TEAM = PLAYERS | STAFF
PAIR = {R["👑 Capitão Bloom White"]: R["👑 Capitão Bloom Red"], R["👑 Capitão Bloom Red"]: R["👑 Capitão Bloom White"],
        R["🎓 Coach Bloom White"]: R["🎓 Coach Bloom Red"], R["🎓 Coach Bloom Red"]: R["🎓 Coach Bloom White"]}

# ------------------------------------------------------------------ 1) cargos da Bloom Red que faltam
members = call("GET", f"/guilds/{G}/members?limit=1000")
name = lambda m: m.get("nick") or m["user"].get("global_name") or m["user"]["username"]  # noqa: E731
for m in members:
    if name(m) in ("ratinho", "Andrezin_dz7") and R["🛡️ Titular Bloom Red"] not in m["roles"]:
        do(f"dar Titular Bloom Red pra {name(m)}", "PUT",
           f"/guilds/{G}/members/{m['user']['id']}/roles/{R['🛡️ Titular Bloom Red']}")

# quem só tinha Bloom White/Red e nenhum outro cargo de time perde o acesso: avisa antes
for m in members:
    roles = set(m["roles"])
    if roles & OLD and not roles & TEAM:
        print(f"ATENÇÃO: {name(m)} só tem o cargo antigo do time e vai perder o acesso às áreas dos times")

# ------------------------------------------------------------------ 2) permissões: os dois times juntos
for c in call("GET", f"/guilds/{G}/channels"):
    ows = c["permission_overwrites"]
    roles_here = {o["id"]: o for o in ows if o["type"] == 0}
    touched = set(roles_here) & (TEAM | OLD)
    if not touched:
        continue
    is_staff = any(int(roles_here[r]["deny"]) & VIEW for r in set(roles_here) & OLD)
    # modelo: a permissão positiva que um jogador do time tinha aqui
    model = next((roles_here[r] for r in list(OLD) + sorted(PLAYERS) if r in roles_here
                  and not int(roles_here[r]["deny"]) & VIEW), None)
    staff_model = next((roles_here[r] for r in sorted(STAFF) if r in roles_here), model)
    new = [o for o in ows if o["id"] not in (TEAM | OLD)]
    if is_staff:
        for r in PLAYERS:
            new.append({"id": r, "type": 0, "allow": "0", "deny": str(VIEW)})
        for r in STAFF:
            new.append({**staff_model, "id": r})
    else:
        if model is None:
            continue
        for r in PLAYERS:
            new.append({"id": r, "type": 0, "allow": model["allow"], "deny": model["deny"]})
        for r in STAFF:   # capitão/coach mantêm o que já tinham (ou o do outro time); senão, igual aos jogadores
            twin = PAIR[r]
            src = roles_here.get(r) or roles_here.get(twin) or model
            new.append({"id": r, "type": 0, "allow": src["allow"], "deny": src["deny"]})
    key = lambda o: (o["id"], o["allow"], o["deny"])  # noqa: E731
    if sorted(map(key, new)) != sorted(map(key, ows)):
        kind = "staff" if is_staff else "dois times"
        do(f"permissões ({kind}): {c['name']}", "PATCH", f"/channels/{c['id']}", {"permission_overwrites": new})

# ------------------------------------------------------------------ 3) apaga os cargos antigos
for n in ("💎 Bloom White", "🔴 Bloom Red"):
    do(f"apagar cargo {n}", "DELETE", f"/guilds/{G}/roles/{R[n]}")
print("pronto" if APPLY else "fim da prévia")
