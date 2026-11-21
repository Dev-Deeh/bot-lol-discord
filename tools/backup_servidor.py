"""Backup do servidor do Discord pelo bot (só lê, não muda nada).

Guarda em backups/AAAA-MM-DD_HHMM/:
- servidor.json: cargos (nome, cor, permissões, posição), categorias e canais com as permissões de cada um,
  quem tem cada cargo e os webhooks (sem o token);
- bot.db: cópia do banco do bot (configuração dos times, vínculos, etc.).
A pasta backups/ não vai para o GitHub (tem IDs de membros).

Uso: python tools/backup_servidor.py"""
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(".env")
G = "1569317259581587517"
API = "https://discord.com/api/v10"
H = {"Authorization": "Bot " + os.environ["DISCORD_TOKEN"], "User-Agent": "DiscordBot (x,1)"}


def call(p):
    for _ in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(API + p, headers=H)) as x:
                return json.loads(x.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(json.loads(e.read()).get("retry_after", 1) + 0.2)
                continue
            raise RuntimeError(f"GET {p} {e.code}: {e.read()[:300]}")


def members():
    out, after = [], "0"
    while True:
        page = call(f"/guilds/{G}/members?limit=1000&after={after}")
        out += page
        if len(page) < 1000:
            return out
        after = page[-1]["user"]["id"]


guild = call(f"/guilds/{G}")
data = {
    "salvo_em": datetime.now().isoformat(timespec="seconds"),
    "servidor": {"id": G, "nome": guild["name"]},
    "cargos": call(f"/guilds/{G}/roles"),
    "canais": call(f"/guilds/{G}/channels"),
    "membros": [{"id": m["user"]["id"], "nome": m["user"]["username"], "apelido": m.get("nick"), "cargos": m["roles"]}
                for m in members()],
    "webhooks": [{k: w.get(k) for k in ("id", "name", "channel_id")} for w in call(f"/guilds/{G}/webhooks")],
}
pasta = os.path.join("backups", datetime.now().strftime("%Y-%m-%d_%H%M"))
os.makedirs(pasta, exist_ok=True)
with open(os.path.join(pasta, "servidor.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)
if os.path.exists("bot.db"):
    shutil.copy2("bot.db", os.path.join(pasta, "bot.db"))
print(f"backup em {pasta}: {len(data['cargos'])} cargos, {len(data['canais'])} canais, "
      f"{len(data['membros'])} membros, {len(data['webhooks'])} webhooks")
