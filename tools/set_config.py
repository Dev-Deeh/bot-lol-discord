"""Grava configurações de um servidor direto no banco do bot.

Uso:  python tools/set_config.py <bot.db> <ID do servidor> chave=valor [chave=valor ...]
Ex.:  python tools/set_config.py bot.db 123 canal:alertas=456 canal:partidas=789
"""
import sqlite3
import sys

db, guild, *pairs = sys.argv[1:]
conn = sqlite3.connect(db)
for pair in pairs:
    key, value = pair.split("=", 1)
    conn.execute("INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?,?,?)", (int(guild), key, value))
conn.commit()
print("ok:", ", ".join(pairs))
