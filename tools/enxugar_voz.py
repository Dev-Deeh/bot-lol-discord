"""Enxuga as salas de voz do servidor Bloom e cria a área aberta da resenha.

Cada time fica com: 🎧 Geral, ⚔️ Scrim / Coach e ➕ Criar sala (sala privada sob demanda).
A área 🎮 RESENHA (os dois times, convidados e amigos) junta a antiga área de convidados e a de música:
💬 resenha, 🍻 Resenha, Duo 1-2, Flex 1-2, Música e AFK.
As categorias de privados fixos somem (as salas são apagadas só se estiverem vazias).

Uso: python tools/enxugar_voz.py            (só mostra o que vai fazer)
     python tools/enxugar_voz.py --aplicar  (aplica)"""
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
     "Content-Type": "application/json", "X-Audit-Log-Reason": "Enxugar salas de voz"}
VIEW, CONNECT = 1 << 10, 1 << 20


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
        time.sleep(0.4)
        return res


roles = {r["name"]: r["id"] for r in call("GET", f"/guilds/{G}/roles")}
chans = call("GET", f"/guilds/{G}/channels")
cats = {c["name"]: c for c in chans if c["type"] == 4}
kids = lambda cat: [c for c in chans if c.get("parent_id") == cat["id"]]  # noqa: E731
def strip_bots(ows):
    return [o for o in ows if o["id"] != roles["🤖 Bots"]]


def with_bots(ows):
    return strip_bots(ows) + [{"id": roles["🤖 Bots"], "type": 0, "allow": str(VIEW | CONNECT), "deny": "0"}]


# ------------------------------------------------------------------ áreas dos times
for team in ("💎 BLOOM WHITE", "🔴 BLOOM RED"):
    voz = cats[f"{team} · VOZ"]
    for c in kids(voz):
        n = c["name"]
        if n.startswith(("🎮 Duo", "👥 Flex")):
            do(f"{team}: apagar {n}", "DELETE", f"/channels/{c['id']}")
        elif n == "🎓 Coach":
            do(f"{team}: renomear {n} -> ⚔️ Scrim / Coach (até 8)", "PATCH", f"/channels/{c['id']}",
               {"name": "⚔️ Scrim / Coach", "user_limit": 8})
    if not any(c["name"].startswith("➕") for c in kids(voz)):
        do(f"{team}: criar ➕ Criar sala", "POST", f"/guilds/{G}/channels",
           {"name": "➕ Criar sala", "type": 2, "parent_id": voz["id"],
            "permission_overwrites": voz["permission_overwrites"]})
    priv = cats.get(f"{team} · PRIVADOS")
    if priv:
        for c in kids(priv):
            do(f"{team}: apagar sala fixa {c['name']}", "DELETE", f"/channels/{c['id']}")
        do(f"{team}: apagar categoria {priv['name']}", "DELETE", f"/channels/{priv['id']}")

# ------------------------------------------------------------------ resenha (todo mundo)
conv = cats.get("🤝 CONVIDADOS") or cats.get("🎮 RESENHA")
old_voz = cats.get("🔊 BLOOM · VOZ")
open_ows = conv["permission_overwrites"]
if conv["name"] != "🎮 RESENHA":
    do("renomear categoria 🤝 CONVIDADOS -> 🎮 RESENHA", "PATCH", f"/channels/{conv['id']}", {"name": "🎮 RESENHA"})
for c in kids(conv):
    if c["name"] == "💬・convidados":
        do("renomear 💬・convidados -> 💬・resenha", "PATCH", f"/channels/{c['id']}",
           {"name": "💬・resenha", "permission_overwrites": open_ows})
    elif c["name"] == "🤝 Sala dos Convidados":
        do("renomear 🤝 Sala dos Convidados -> 🍻 Resenha", "PATCH", f"/channels/{c['id']}",
           {"name": "🍻 Resenha", "permission_overwrites": with_bots(open_ows)})
existing = {c["name"] for c in kids(conv)}
for name, lim in (("🎮 Duo 1", 2), ("🎮 Duo 2", 2), ("👥 Flex 1", 5), ("👥 Flex 2", 5)):
    if name not in existing:
        do(f"resenha: criar {name} (até {lim})", "POST", f"/guilds/{G}/channels",
           {"name": name, "type": 2, "parent_id": conv["id"], "user_limit": lim,
            "permission_overwrites": with_bots(open_ows)})
if old_voz:
    for c in kids(old_voz):
        do(f"mover {c['name']} pra resenha (aberto a todos)", "PATCH", f"/channels/{c['id']}",
           {"parent_id": conv["id"], "permission_overwrites": with_bots(open_ows)})
    do("apagar categoria 🔊 BLOOM · VOZ (vazia)", "DELETE", f"/channels/{old_voz['id']}")

# ------------------------------------------------------------------ divisória e ordem
div = next((c for c in cats.values() if "RESENHA ━" in c["name"]), None)
div_id = div["id"] if div else None
if not div:
    res = do("criar divisória ━━━━ 🎮 RESENHA ━━━━", "POST", f"/guilds/{G}/channels",
             {"name": "━━━━ 🎮 RESENHA ━━━━", "type": 4, "permission_overwrites": open_ows})
    div_id = res["id"] if res else "NOVO"

order = ["📌 BLOOM", "🌍 LEAGUE", "🎁 JOGOS & PROMOS",
         "━━━━ 💎 BLOOM WHITE ━━━━", "💎 BLOOM WHITE · TIME", "💎 BLOOM WHITE · COMPETITIVO",
         "💎 BLOOM WHITE · VOZ", "💎 BLOOM WHITE · TIER LIST",
         "━━━━ 🔴 BLOOM RED ━━━━", "🔴 BLOOM RED · TIME", "🔴 BLOOM RED · COMPETITIVO",
         "🔴 BLOOM RED · VOZ", "🔴 BLOOM RED · TIER LIST",
         "DIV", "RESENHA", "🎓 STAFF"]
ids = []
for n in order:
    if n == "DIV":
        ids.append(div_id)
    elif n == "RESENHA":
        ids.append(conv["id"])
    elif n in cats:
        ids.append(cats[n]["id"])
print("ordem das categorias:", " > ".join(n for n in order if n in cats or n in ("DIV", "RESENHA")))
if APPLY:
    call("PATCH", f"/guilds/{G}/channels", [{"id": cid, "position": i} for i, cid in enumerate(ids)])
    # dentro da resenha: texto, Resenha, Duo, Flex, Música, AFK
    fresh = call("GET", f"/guilds/{G}/channels")
    want = ["💬・resenha", "🎵・música", "🍻 Resenha", "🎮 Duo 1", "🎮 Duo 2", "👥 Flex 1", "👥 Flex 2", "🎵 Música", "💤 AFK"]
    inside = {c["name"]: c["id"] for c in fresh if c.get("parent_id") == conv["id"]}
    call("PATCH", f"/guilds/{G}/channels",
         [{"id": inside[n], "position": i} for i, n in enumerate(want) if n in inside])
    for team in ("💎 BLOOM WHITE", "🔴 BLOOM RED"):
        voz = cats[f"{team} · VOZ"]
        inside = {c["name"]: c["id"] for c in fresh if c.get("parent_id") == voz["id"]}
        call("PATCH", f"/guilds/{G}/channels",
             [{"id": inside[n], "position": i} for i, n in enumerate(["🎧 Geral", "⚔️ Scrim / Coach", "➕ Criar sala"])
              if n in inside])
    print("pronto")
print("categorias de voz dos times (pra config times):",
      cats["💎 BLOOM WHITE · VOZ"]["id"], cats["🔴 BLOOM RED · VOZ"]["id"])
