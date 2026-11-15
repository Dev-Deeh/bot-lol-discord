"""Vincula uma conta da Riot a um membro do Discord direto no banco, sem a verificação do ícone.

Uso (na VM, como o usuário do bot):
    .venv/bin/python tools/vincular_conta.py "Nick#TAG" <id_do_discord> [id_do_servidor]

Guarda o elo atual e a última ranqueada, pra não postar partida antiga nem aviso de "terminou as MDs".
O cargo de elo é ajustado pelo bot (ou no próximo /perfil)."""
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv(".env")
riot_id, user_id = sys.argv[1], int(sys.argv[2])
guild_id = int(sys.argv[3]) if len(sys.argv) > 3 else 1569317259581587517
name, _, tag = riot_id.rpartition("#")
KEY = os.environ["RIOT_API_KEY"]
REGION = os.getenv("RIOT_REGION", "americas")
PLATFORM = os.getenv("RIOT_PLATFORM", "br1")


def get(host, path):
    req = urllib.request.Request(f"https://{host}.api.riotgames.com/{path}", headers={"X-Riot-Token": KEY})
    return json.load(urllib.request.urlopen(req))


acc = get(REGION, f"riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}")
puuid = acc["puuid"]
solo = next((e for e in get(PLATFORM, f"lol/league/v4/entries/by-puuid/{puuid}")
             if e["queueType"] == "RANKED_SOLO_5x5"), {})
ids = get(REGION, f"lol/match/v5/matches/by-puuid/{puuid}/ids?count=1&type=ranked")
db = sqlite3.connect(os.getenv("DATABASE_PATH", "bot.db"))
db.execute("INSERT OR REPLACE INTO accounts (guild_id, user_id, puuid, riot_id, tier, rank, lp, wins, losses,"
           " last_match) VALUES (?,?,?,?,?,?,?,?,?,?)",
           (guild_id, user_id, puuid, f"{acc['gameName']}#{acc['tagLine']}", solo.get("tier"), solo.get("rank"),
            solo.get("leaguePoints"), solo.get("wins"), solo.get("losses"), ids[0] if ids else ""))
db.commit()
print("vinculado:", f"{acc['gameName']}#{acc['tagLine']}", "->", user_id, "|", solo.get("tier"), solo.get("rank"),
      solo.get("leaguePoints"))
