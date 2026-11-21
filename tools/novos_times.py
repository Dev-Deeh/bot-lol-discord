"""Troca os times do servidor Bloom - WR (dez/2026):

- Bloom White  -> Sem Raage!         (roxo)
- Bloom (roxa) -> Ministério do Feed (dourado)
- Bloom Red    -> continua
- Time A1      -> time novo (turquesa), espelhando a Bloom Red

Cargos e categorias são RENOMEADOS (o ID não muda, então a config "times" do bot continua valendo).
Os canais dentro das categorias da Sem Raage! e do Ministério do Feed são recriados limpos (as mensagens antigas
somem); as tier lists dos jogadores antigos são apagadas (o bot cria a de cada jogador novo). Os webhooks do app
que estavam em #notícias e #agenda passam para os canais novos (mesmo link, continuam funcionando).
Membros: quem tinha cargo da Bloom White ou da Bloom roxa perde o cargo de time e fica como Convidado;
raage vira capitão da Sem Raage!, Deeh titular do Ministério do Feed, Laxus e Tsukuyomi titulares do A1
(Tsukuyomi continua capitão da Bloom Red).

Faça antes: python tools/backup_servidor.py
Uso: python tools/novos_times.py            (prévia, não muda nada)
     python tools/novos_times.py --aplicar"""
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
     "Content-Type": "application/json", "X-Audit-Log-Reason": "Novos times: Sem Raage!, Ministerio do Feed, Time A1"}

# time antigo -> time novo: (nome, emoji das categorias, cores de capitão, coach, titular, reserva)
TEAMS = {
    "Bloom White": ("Sem Raage!", "💜", "💎 BLOOM WHITE", (0xC79BFF, 0xE2CCFF, 0x9B6BFF, 0x7552C4)),
    "Bloom": ("Ministério do Feed", "🏛️", "🟣 BLOOM", (0xFFD15C, 0xFBE3A0, 0xE8A33D, 0xB07A2A)),
}
A1 = ("Time A1", "🔷", (0x3DF2D6, 0xA8F5EA, 0x1FB5A3, 0x157F73))
KINDS = [("👑 Capitão", 0), ("🎓 Coach", 1), ("🛡️ Titular", 2), ("🔁 Reserva", 3)]
CAT_PARTS = ["━━━━ {e} {N} ━━━━", "{e} {N} · TIME", "{e} {N} · COMPETITIVO", "{e} {N} · VOZ", "{e} {N} · TIER LIST"]
RED_CATS = [p.format(e="🔴", N="BLOOM RED") for p in CAT_PARTS]
# membros (nome de usuário do Discord)
SAEM = ["naoi1502", "elementy7727", "deeeeeeeeeeeeeeeeeeeeh", "niete9702", "19ziul", "pedrojaime.", "vinigol22998",
        "mycrescent", "bruno_o_rafa"]
ENTRAM = {"raage": [("Sem Raage!", "👑 Capitão"), ("Sem Raage!", "🛡️ Titular")],
          "deeeeeeeeeeeeeeeeeeeeh": [("Ministério do Feed", "🛡️ Titular")],
          "laxusss1": [("Time A1", "🛡️ Titular")],
          ".proudmoon": [("Time A1", "🛡️ Titular")]}


def call(m, p, b=None):
    for _ in range(8):
        r = urllib.request.Request(API + p, method=m, headers=H, data=json.dumps(b).encode() if b is not None else None)
        try:
            with urllib.request.urlopen(r) as x:
                t = x.read()
                return json.loads(t) if t else None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(json.loads(e.read()).get("retry_after", 1) + 0.3)
                continue
            raise RuntimeError(f"{m} {p} {e.code}: {e.read()[:300]}")


feitos = 0


def do(desc, m, p, b=None, fake=None):
    global feitos
    print(("FAZENDO: " if APPLY else "vai: ") + desc, flush=True)
    feitos += 1
    if APPLY:
        res = call(m, p, b)
        time.sleep(0.3)
        return res
    return fake


roles = {r["name"]: r for r in call("GET", f"/guilds/{G}/roles")}
chans = call("GET", f"/guilds/{G}/channels")
hooks = call("GET", f"/guilds/{G}/webhooks")
members = call("GET", f"/guilds/{G}/members?limit=1000")
byname = {m["user"]["username"]: m for m in members}
cats = {c["name"]: c for c in chans if c["type"] == 4}
convidado = roles["🤝 Convidado"]["id"]

# ------------------------------------------------------------------ 1) cargos: renomeia e pinta
newrole = {}  # (time novo, tipo) -> id
for old, (new, _e, _cat, colors) in TEAMS.items():
    for kind, k in KINDS:
        src = roles.get(f"{kind} {old}")
        name = f"{kind} {new}"
        if src is None and name in roles:
            newrole[(new, kind)] = roles[name]["id"]
            continue
        newrole[(new, kind)] = src["id"]
        do(f"cargo '{src['name']}' -> '{name}'", "PATCH", f"/guilds/{G}/roles/{src['id']}", {"name": name, "color": colors[k]})

# ------------------------------------------------------------------ 2) cargos do Time A1 (iguais aos da Red)
a1map = {}  # id do cargo da Red -> id do cargo do A1
for kind, k in KINDS:
    red = roles[f"{kind} Bloom Red"]
    name = f"{kind} {A1[0]}"
    if name in roles:
        rid = roles[name]["id"]
    else:
        rid = do(f"criar cargo {name}", "POST", f"/guilds/{G}/roles",
                 {"name": name, "permissions": red["permissions"], "color": A1[2][k], "hoist": red["hoist"],
                  "mentionable": red["mentionable"]}, fake={"id": f"<{name}>"})["id"]
    a1map[red["id"]] = rid
    newrole[(A1[0], kind)] = rid


def mirrored(ows):
    have = {o["id"] for o in ows}
    return ows + [{**o, "id": a1map[o["id"]]} for o in ows if o["id"] in a1map and a1map[o["id"]] not in have]


# canais que vão ser apagados (filhos das categorias da Sem Raage! e do Ministério do Feed)
old_cat_ids = set()
for (_n, _e, base, _c) in TEAMS.values():
    be, bn = base.split(" ", 1)
    old_cat_ids |= {cats[p.format(e=be, N=bn)]["id"] for p in CAT_PARTS}
gone = {c["id"] for c in chans if c.get("parent_id") in old_cat_ids}

# ------------------------------------------------------------------ 3) A1 ganha as mesmas permissões da Red em todo canal
for c in chans:
    if c["id"] in gone:
        continue
    ows = c["permission_overwrites"]
    if mirrored(ows) != ows:
        do(f"permissões do A1 em {c['name']}", "PATCH", f"/channels/{c['id']}", {"permission_overwrites": mirrored(ows)})
        c["permission_overwrites"] = mirrored(ows)


def clone(ch, parent, ows, swap):
    body = {"name": ch["name"], "type": ch["type"], "parent_id": parent, "permission_overwrites": ows}
    if ch.get("topic"):
        t = ch["topic"]
        for a, b in swap:
            t = t.replace(a, b)
        body["topic"] = t
    if ch.get("rate_limit_per_user"):
        body["rate_limit_per_user"] = ch["rate_limit_per_user"]
    if ch["type"] == 2:
        body["user_limit"] = ch.get("user_limit", 0)
        body["bitrate"] = min(ch.get("bitrate", 64000), 96000)
    return body


def kids(cat_id):
    return sorted([x for x in chans if x.get("parent_id") == cat_id], key=lambda x: (x["type"] == 2, x["position"]))


# ------------------------------------------------------------------ 4) Sem Raage! e Ministério do Feed: categorias renomeadas, canais limpos
for old, (new, emoji, base, _c) in TEAMS.items():
    be, bn = base.split(" ", 1)
    for part in CAT_PARTS:
        cat = cats[part.format(e=be, N=bn)]
        cname = part.format(e=emoji, N=new.upper())
        do(f"categoria '{cat['name']}' -> '{cname}'", "PATCH", f"/channels/{cat['id']}", {"name": cname})
        for ch in kids(cat["id"]):
            if ch["name"].startswith("🔒"):
                continue  # sala privada de alguém agora: o bot apaga quando esvaziar
            if "TIER LIST" in part:
                do(f"  apagar tier list antiga #{ch['name']}", "DELETE", f"/channels/{ch['id']}")
                continue
            body = clone(ch, cat["id"], ch["permission_overwrites"], [(old, new), (old.upper(), new.upper())])
            res = do(f"  recriar limpo {('🔊 ' if ch['type'] == 2 else '#')}{ch['name']}", "POST", f"/guilds/{G}/channels", body,
                     fake={"id": "<novo>"})
            for h in [h for h in hooks if h["channel_id"] == ch["id"]]:
                do(f"    webhook '{h['name']}' -> canal novo", "PATCH", f"/webhooks/{h['id']}", {"channel_id": res["id"]})
            do(f"  apagar o antigo {ch['name']}", "DELETE", f"/channels/{ch['id']}")

# ------------------------------------------------------------------ 5) Time A1: cópia da área da Red
a1cats = {}
for red_name, part in zip(RED_CATS, CAT_PARTS):
    cname = part.format(e=A1[1], N=A1[0].upper())
    src = cats[red_name]
    if cname in cats:
        a1cats[part] = cats[cname]["id"]
        continue
    a1cats[part] = do(f"criar categoria {cname}", "POST", f"/guilds/{G}/channels",
                      {"name": cname, "type": 4, "permission_overwrites": mirrored(src["permission_overwrites"])},
                      fake={"id": f"<{cname}>"})["id"]
    if "TIER LIST" in part:
        continue  # o bot cria a tier list de cada jogador
    for ch in kids(src["id"]):
        if ch["name"].startswith("🔒"):
            continue
        do(f"  criar {('🔊 ' if ch['type'] == 2 else '#')}{ch['name']} em {cname}", "POST", f"/guilds/{G}/channels",
           clone(ch, a1cats[part], mirrored(ch["permission_overwrites"]), [("Bloom Red", A1[0]), ("BLOOM RED", A1[0].upper())]))

# ------------------------------------------------------------------ 6) membros
team_ids = {rid for rid in newrole.values()}
for u in SAEM:
    m = byname.get(u)
    if not m:
        print(f"(não achei {u})")
        continue
    for rid in [r for r in m["roles"] if r in team_ids and not r.startswith("<")]:
        do(f"tirar cargo de time de {u}", "DELETE", f"/guilds/{G}/members/{m['user']['id']}/roles/{rid}")
    if convidado not in m["roles"]:
        do(f"dar Convidado a {u}", "PUT", f"/guilds/{G}/members/{m['user']['id']}/roles/{convidado}")
for u, give in ENTRAM.items():
    m = byname.get(u)
    if not m:
        print(f"(não achei {u})")
        continue
    for team, kind in give:
        do(f"dar '{kind} {team}' a {u}", "PUT", f"/guilds/{G}/members/{m['user']['id']}/roles/{newrole[(team, kind)]}")

# ------------------------------------------------------------------ 7) ordem das categorias e dos cargos
if APPLY:
    chans = call("GET", f"/guilds/{G}/channels")
    cs = sorted([c for c in chans if c["type"] == 4], key=lambda c: c["position"])
    block = lambda tag: [c for c in cs if tag in c["name"]]  # noqa: E731
    first = [c for c in cs if c["name"] in ("📌 BLOOM", "🌍 LEAGUE", "🎁 JOGOS & PROMOS")]
    order = first + block("SEM RAAGE!") + block("MINISTÉRIO DO FEED") + block("TIME A1") + block("BLOOM RED") + \
        [c for c in cs if "RESENHA" in c["name"]] + [c for c in cs if c["name"] == "🎓 STAFF"]
    call("PATCH", f"/guilds/{G}/channels", [{"id": c["id"], "position": i} for i, c in enumerate(order + [c for c in cs if c not in order])])
    roles = {r["name"]: r for r in call("GET", f"/guilds/{G}/roles")}
    teams = ["Sem Raage!", "Ministério do Feed", "Time A1", "Bloom Red"]
    stack = [roles[f"{kind} {t}"] for kind, _ in KINDS for t in teams]  # capitães, coaches, titulares, reservas
    top = roles["Bot Deeh LOL"]["position"] - 1
    call("PATCH", f"/guilds/{G}/roles", [{"id": r["id"], "position": top - i} for i, r in enumerate(stack)])
    tl = lambda t: f"{roles[f'🛡️ Titular {t}']['id']},{roles[f'🔁 Reserva {t}']['id']}"  # noqa: E731
    print("\nconfig 'times' do Time A1 (acrescentar na VM):", f"{tl('Time A1')}:{a1cats[CAT_PARTS[3]]}:{a1cats[CAT_PARTS[4]]}")
print(f"\n{feitos} ações" + (" feitas" if APPLY else " na prévia (nada foi mudado)"))
