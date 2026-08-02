import json
from pathlib import Path
from typing import Optional
from resource.models import ItemDef, ItemType
from resource.packs import default_pack_dir


class ItemDatabase:
    def __init__(self, items_dir: Optional[Path] = None):
        self._items_dir = Path(items_dir) if items_dir else default_pack_dir() / "items"
        self._items: dict[str, ItemDef] = {}
        self._runtime: dict[str, ItemDef] = {}
        self._by_name: dict[str, str] = {}
        self._by_alias: dict[str, str] = {}
        self._by_name_en: dict[str, str] = {}
        self._loaded = False

    def set_items_dir(self, items_dir: Optional[Path]):
        self._items_dir = Path(items_dir) if items_dir else None
        self._items.clear()
        self._by_name.clear()
        self._by_alias.clear()
        self._by_name_en.clear()
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        self._items.clear()
        self._by_name.clear()
        self._by_alias.clear()
        self._by_name_en.clear()

        if not self._items_dir or not self._items_dir.exists():
            return

        for fpath in sorted(self._items_dir.glob("*.json")):
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

    # ── 运行时覆盖层（填表创建的定义，随存档保存）──

    def add_runtime(self, item_def: ItemDef) -> str:
        self._runtime[item_def.guid] = item_def
        return item_def.guid

    def replace_runtime(self, defs: dict[str, ItemDef]):
        self._runtime = dict(defs)

    def runtime_items(self) -> dict[str, ItemDef]:
        return dict(self._runtime)

    def _find_runtime(self, q: str) -> Optional[ItemDef]:
        q = q.strip().lower()
        for item in self._runtime.values():
            if item.name.lower() == q or item.name_en.lower() == q:
                return item
            for alias in item.aliases:
                if alias.lower() == q:
                    return item
        return None

    def get(self, guid: str) -> Optional[ItemDef]:
        self.load()
        if guid in self._runtime:
            return self._runtime[guid]
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
        return self._find_runtime(q)

    def find_by_alias(self, alias: str) -> Optional[ItemDef]:
        self.load()
        guid = self._by_alias.get(alias.strip().lower())
        if guid:
            return self._items.get(guid)
        return self._find_runtime(alias.strip())

    def search(self, query: str, threshold: float = 0.5) -> list[tuple[ItemDef, float]]:
        self.load()
        q = query.strip().lower()
        results: list[tuple[ItemDef, float]] = []
        for item in self.all_items():
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
        return list(self._items.values()) + list(self._runtime.values())


item_db = ItemDatabase()
