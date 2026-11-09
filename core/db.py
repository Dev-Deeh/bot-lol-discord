"""Banco de dados SQLite do bot (um arquivo só, sem precisar instalar nada)."""
import time

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (guild_id, key));

CREATE TABLE IF NOT EXISTS accounts (
    guild_id INTEGER, user_id INTEGER, puuid TEXT, riot_id TEXT,
    tier TEXT, rank TEXT, lp INTEGER, wins INTEGER, losses INTEGER,
    last_match TEXT, PRIMARY KEY (guild_id, user_id));

CREATE TABLE IF NOT EXISTS scrims (
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER,
    message_id INTEGER, opponent TEXT, start_ts INTEGER, reminded INTEGER DEFAULT 0,
    result TEXT, score TEXT, created_by INTEGER);

CREATE TABLE IF NOT EXISTS scrim_rsvp (
    scrim_id INTEGER, user_id INTEGER, status TEXT, PRIMARY KEY (scrim_id, user_id));

CREATE TABLE IF NOT EXISTS lineup (
    guild_id INTEGER, user_id INTEGER, role TEXT, is_sub INTEGER,
    PRIMARY KEY (guild_id, user_id));

CREATE TABLE IF NOT EXISTS vods (
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, url TEXT, tags TEXT,
    description TEXT, author_id INTEGER, created_ts INTEGER);

CREATE TABLE IF NOT EXISTS pools (
    guild_id INTEGER, user_id INTEGER, champion TEXT, role TEXT,
    PRIMARY KEY (guild_id, user_id, champion));

CREATE TABLE IF NOT EXISTS profiles (
    guild_id INTEGER, user_id INTEGER, xp INTEGER DEFAULT 0, coins INTEGER DEFAULT 500,
    last_xp_ts INTEGER DEFAULT 0, last_daily_ts INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id));

CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, title TEXT,
    option_a TEXT, option_b TEXT, status TEXT DEFAULT 'aberta', winner TEXT,
    channel_id INTEGER, message_id INTEGER);

CREATE TABLE IF NOT EXISTS wagers (
    bet_id INTEGER, user_id INTEGER, option TEXT, amount INTEGER,
    PRIMARY KEY (bet_id, user_id));

CREATE TABLE IF NOT EXISTS temp_voice (channel_id INTEGER PRIMARY KEY, guild_id INTEGER);

CREATE TABLE IF NOT EXISTS private_rooms (channel_id INTEGER PRIMARY KEY, guild_id INTEGER, owner_id INTEGER);

CREATE TABLE IF NOT EXISTS personal_rooms (channel_id INTEGER PRIMARY KEY, guild_id INTEGER, owner_id INTEGER);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def execute(self, sql: str, params=()):
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur.lastrowid

    async def fetchone(self, sql: str, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    # ---------- configuração por servidor ----------
    async def get_config(self, guild_id: int, key: str):
        row = await self.fetchone(
            "SELECT value FROM guild_config WHERE guild_id=? AND key=?", (guild_id, key))
        return row["value"] if row else None

    async def set_config(self, guild_id: int, key: str, value):
        if value is None:
            await self.execute("DELETE FROM guild_config WHERE guild_id=? AND key=?", (guild_id, key))
        else:
            await self.execute(
                "INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?,?,?)",
                (guild_id, key, str(value)))

    async def config_prefix(self, guild_id: int, prefix: str):
        return await self.fetchall(
            "SELECT key, value FROM guild_config WHERE guild_id=? AND key LIKE ?",
            (guild_id, prefix + "%"))

    # ---------- meta global ----------
    async def get_meta(self, key: str):
        row = await self.fetchone("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else None

    async def set_meta(self, key: str, value: str):
        await self.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))

    # ---------- perfil (XP e moedas) ----------
    async def profile(self, guild_id: int, user_id: int):
        await self.execute(
            "INSERT OR IGNORE INTO profiles (guild_id, user_id) VALUES (?,?)", (guild_id, user_id))
        return await self.fetchone(
            "SELECT * FROM profiles WHERE guild_id=? AND user_id=?", (guild_id, user_id))

    async def add_profile(self, guild_id: int, user_id: int, xp: int = 0, coins: int = 0):
        await self.profile(guild_id, user_id)
        await self.execute(
            "UPDATE profiles SET xp = xp + ?, coins = coins + ? WHERE guild_id=? AND user_id=?",
            (xp, coins, guild_id, user_id))
        return await self.profile(guild_id, user_id)

    async def touch(self, guild_id: int, user_id: int, column: str):
        assert column in ("last_xp_ts", "last_daily_ts")
        await self.execute(
            f"UPDATE profiles SET {column}=? WHERE guild_id=? AND user_id=?",
            (int(time.time()), guild_id, user_id))
