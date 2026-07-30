import json
from pathlib import Path
from typing import Optional
from resource.models import ItemDef, ItemType

ITEMS_DIR = Path(__file__).resolve().parent.parent / "data" / "items"


class ItemDatabase:
    def __init__(self):
        self._items: dict[str, ItemDef] = {}
        self._by_name: dict[str, str] = {}
        self._by_alias: dict[str, str] = {}
        self._by_name_en: dict[str, str] = {}
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        self._items.clear()
        self._by_name.clear()
        self._by_alias.clear()
        self._by_name_en.clear()

        if not ITEMS_DIR.exists():
            return

        for fpath in sorted(ITEMS_DIR.glob("*.json")):
            data = json.loads(fpath.read_text(encoding="utf-8"))
            for guid, entry in data.items():
                entry["guid"] = guid
                if "type" in entry and isinstance(entry["type"], str):
                    entry["type"] = ItemType(entry["type"])
                item = ItemDef(**entry)
                self._items[guid] = item
                self._by_name[item.name.lower()] = guid
                if item.name_en:
                    self._by_name_en[item.name_en.lower()] = guid
                for alias in item.aliases:
                    self._by_alias[alias.lower()] = guid

        self._loaded = True

    def get(self, guid: str) -> Optional[ItemDef]:
        self.load()
        return self._items.get(guid)

    def find_by_name(self, name: str) -> Optional[ItemDef]:
        self.load()
        q = name.strip().lower()
        guid = self._by_name.get(q)
        if guid:
            return self._items.get(guid)
        guid = self._by_name_en.get(q)
        if guid:
            return self._items.get(guid)
        return None

    def find_by_alias(self, alias: str) -> Optional[ItemDef]:
        self.load()
        guid = self._by_alias.get(alias.strip().lower())
        return self._items.get(guid) if guid else None

    def search(self, query: str, threshold: float = 0.5) -> list[tuple[ItemDef, float]]:
        self.load()
        q = query.strip().lower()
        results: list[tuple[ItemDef, float]] = []
        for item in self._items.values():
            score = item.matches_fuzzy(q)
            if score >= threshold:
                results.append((item, score))
        results.sort(key=lambda x: -x[1])
        return results

    def find_best(self, query: str) -> Optional[ItemDef]:
        results = self.search(query, threshold=0.5)
        return results[0][0] if results else None

    def all_items(self) -> list[ItemDef]:
        self.load()
        return list(self._items.values())

    def items_by_type(self, t: ItemType) -> list[ItemDef]:
        return [it for it in self.all_items() if it.type == t]


item_db = ItemDatabase()
