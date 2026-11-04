"""Data Dragon: dados estáticos oficiais do LoL (campeões, itens, runas, imagens). Não precisa de chave."""
import aiohttp

from core.util import normalize

BASE = "https://ddragon.leagueoflegends.com"


def patch_of(version: str) -> str:
    """'15.21.1' -> '15.21'"""
    return ".".join(version.split(".")[:2])


class DDragon:
    def __init__(self, session: aiohttp.ClientSession, lang="pt_BR"):
        self.session = session
        self.lang = lang
        self.version: str | None = None
        self.versions: list[str] = []
        self.champions: dict = {}      # id -> dados (ex.: "Jinx")
        self.by_key: dict = {}         # chave numérica -> dados
        self.by_norm: dict = {}        # nome normalizado -> dados
        self.runes: dict = {}          # id da runa/árvore -> nome
        self.keystones: list[str] = []
        self.rune_icons: dict = {}
        self.summoner_spells: dict = {}
        self.summoner_spell_icons: dict = {}
        self._items = None
        self._cache: dict = {}

    async def _json(self, url: str):
        async with self.session.get(url) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def refresh(self) -> str:
        self.versions = await self._json(f"{BASE}/api/versions.json")
        latest = self.versions[0]
        if latest == self.version and self.champions:
            return latest
        data = await self._json(f"{BASE}/cdn/{latest}/data/{self.lang}/champion.json")
        self.champions = data["data"]
        self.by_key = {int(c["key"]): c for c in self.champions.values()}
        self.by_norm = {}
        for c in self.champions.values():
            self.by_norm[normalize(c["id"])] = c
            self.by_norm[normalize(c["name"])] = c

        runes = await self._json(f"{BASE}/cdn/{latest}/data/{self.lang}/runesReforged.json")
        self.runes = {}
        self.rune_icons = {}
        self.keystones = [r["name"] for style in runes for r in style["slots"][0]["runes"]]
        for style in runes:
            self.runes[style["id"]] = style["name"]
            self.rune_icons[style["id"]] = f"{BASE}/cdn/img/{style['icon']}"
            for slot in style["slots"]:
                for rune in slot["runes"]:
                    self.runes[rune["id"]] = rune["name"]
                    self.rune_icons[rune["id"]] = f"{BASE}/cdn/img/{rune['icon']}"

        spells = await self._json(f"{BASE}/cdn/{latest}/data/{self.lang}/summoner.json")
        self.summoner_spells = {int(s["key"]): s["name"] for s in spells["data"].values()}
        self.summoner_spell_icons = {int(s["key"]): f"{BASE}/cdn/{latest}/img/spell/{s['image']['full']}"
                                     for s in spells["data"].values()}

        self._items = None
        self._cache.clear()
        self.version = latest
        return latest

    async def ensure(self):
        if not self.version:
            await self.refresh()

    # ---------- busca de campeões ----------
    def find(self, text: str):
        n = normalize(text)
        if not n:
            return None
        if n in self.by_norm:
            return self.by_norm[n]
        for key, champ in self.by_norm.items():
            if key.startswith(n):
                return champ
        return None

    def search(self, text: str, limit=25) -> list[str]:
        n = normalize(text)
        names = sorted({c["name"] for c in self.champions.values()})
        if not n:
            return names[:limit]
        starts = [x for x in names if normalize(x).startswith(n)]
        contains = [x for x in names if n in normalize(x) and x not in starts]
        return (starts + contains)[:limit]

    def champ_name(self, key: int) -> str:
        c = self.by_key.get(int(key))
        return c["name"] if c else f"#{key}"

    # ---------- dados detalhados ----------
    async def champion_detail(self, champ_id: str, version: str | None = None):
        version = version or self.version
        cache_key = ("champ", champ_id, version)
        if cache_key not in self._cache:
            data = await self._json(f"{BASE}/cdn/{version}/data/{self.lang}/champion/{champ_id}.json")
            self._cache[cache_key] = data["data"][champ_id]
        return self._cache[cache_key]

    async def items(self):
        if self._items is None:
            data = await self._json(f"{BASE}/cdn/{self.version}/data/{self.lang}/item.json")
            self._items = data["data"]
        return self._items

    def previous_patch_version(self) -> str | None:
        current = patch_of(self.versions[0])
        for v in self.versions[1:]:
            if patch_of(v) != current and "_" not in v and not v.startswith("lolpatch"):
                return v
        return None

    # ---------- imagens ----------
    def champ_icon(self, champ_id: str) -> str:
        return f"{BASE}/cdn/{self.version}/img/champion/{champ_id}.png"

    def profile_icon(self, icon_id: int) -> str:
        return f"{BASE}/cdn/{self.version}/img/profileicon/{icon_id}.png"

    def splash(self, champ_id: str, num=0) -> str:
        return f"{BASE}/cdn/img/champion/splash/{champ_id}_{num}.jpg"

    def spell_icon(self, filename: str) -> str:
        return f"{BASE}/cdn/{self.version}/img/spell/{filename}"

    def item_icon(self, item_id: str) -> str:
        return f"{BASE}/cdn/{self.version}/img/item/{item_id}.png"
