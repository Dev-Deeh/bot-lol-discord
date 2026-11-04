"""Cliente da Riot API com controle de limite de requisições."""
import asyncio
import time
from collections import deque
from urllib.parse import quote

import aiohttp


class RiotError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"[{status}] {message}")
        self.status = status
        self.message = message


class RateLimiter:
    """Respeita vários limites ao mesmo tempo, ex.: 20/s e 100/2min (chave de desenvolvimento)."""

    def __init__(self, limits):
        self.limits = [(count, secs, deque()) for count, secs in limits]
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            while True:
                now = time.monotonic()
                wait = 0.0
                for count, secs, q in self.limits:
                    while q and now - q[0] >= secs:
                        q.popleft()
                    if len(q) >= count:
                        wait = max(wait, secs - (now - q[0]))
                if wait <= 0:
                    for _, _, q in self.limits:
                        q.append(now)
                    return
                await asyncio.sleep(wait)


class RiotAPI:
    def __init__(self, session: aiohttp.ClientSession, key: str, platform="br1", region="americas"):
        self.session = session
        self.key = key
        self.platform = platform
        self.region = region
        self.limiter = RateLimiter([(18, 1), (95, 120)])

    @property
    def platform_url(self):
        return f"https://{self.platform}.api.riotgames.com"

    @property
    def region_url(self):
        return f"https://{self.region}.api.riotgames.com"

    async def _get(self, url: str, params=None):
        if not self.key:
            raise RiotError(0, "RIOT_API_KEY não configurada no arquivo .env")
        for _ in range(4):
            await self.limiter.acquire()
            async with self.session.get(url, headers={"X-Riot-Token": self.key}, params=params) as r:
                if r.status == 429:
                    await asyncio.sleep(float(r.headers.get("Retry-After", 5)))
                    continue
                if r.status == 404:
                    return None
                if r.status in (401, 403):
                    raise RiotError(r.status, "Chave da Riot inválida ou expirada "
                                              "(a chave de desenvolvimento expira a cada 24h).")
                if r.status >= 500:
                    await asyncio.sleep(2)
                    continue
                if r.status >= 400:
                    raise RiotError(r.status, await r.text())
                return await r.json()
        raise RiotError(503, "A API da Riot não respondeu. Tenta de novo daqui a pouco.")

    # ---------- Conta ----------
    async def account_by_riot_id(self, name: str, tag: str):
        return await self._get(
            f"{self.region_url}/riot/account/v1/accounts/by-riot-id/{quote(name, safe='')}/{quote(tag, safe='')}")

    async def account_by_puuid(self, puuid: str):
        return await self._get(f"{self.region_url}/riot/account/v1/accounts/by-puuid/{puuid}")

    # ---------- Invocador / elo / maestria ----------
    async def summoner_by_puuid(self, puuid: str):
        return await self._get(f"{self.platform_url}/lol/summoner/v4/summoners/by-puuid/{puuid}")

    async def league_entries(self, puuid: str):
        return await self._get(f"{self.platform_url}/lol/league/v4/entries/by-puuid/{puuid}") or []

    async def solo_entry(self, puuid: str):
        for entry in await self.league_entries(puuid):
            if entry.get("queueType") == "RANKED_SOLO_5x5":
                return entry
        return None

    async def top_masteries(self, puuid: str, count=3):
        return await self._get(
            f"{self.platform_url}/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top",
            params={"count": count}) or []

    # ---------- Partidas ----------
    async def active_game(self, puuid: str):
        return await self._get(f"{self.platform_url}/lol/spectator/v5/active-games/by-summoner/{puuid}")

    async def match_ids(self, puuid: str, count=1, type=None, queue=None):
        params = {"start": 0, "count": count}
        if type:
            params["type"] = type
        if queue:
            params["queue"] = queue
        return await self._get(
            f"{self.region_url}/lol/match/v5/matches/by-puuid/{puuid}/ids", params=params) or []

    async def match(self, match_id: str):
        return await self._get(f"{self.region_url}/lol/match/v5/matches/{match_id}")
