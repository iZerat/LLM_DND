import json
from pathlib import Path
from typing import Optional
from world.ability import Spell
from resource.packs import default_pack_dir


class SpellDatabase:
    """法术数据层：从资源包 spells/ 目录加载 Spell 定义。

    与 item_db 同构：支持运行时覆盖（replace_runtime/add_runtime，随存档保存）、
    按 id/中英文名检索。SRD 5.2.1 无法术表，spells.json 为自建 schema + 数据。
    """

    def __init__(self, spells_dir: Optional[Path] = None):
        self._spells_dir = Path(spells_dir) if spells_dir else default_pack_dir() / "spells"
        self._spells: dict[str, Spell] = {}
        self._runtime: dict[str, Spell] = {}
        self._by_name: dict[str, str] = {}
        self._by_name_en: dict[str, str] = {}
        self._loaded = False

    def set_spells_dir(self, spells_dir: Optional[Path]):
        self._spells_dir = Path(spells_dir) if spells_dir else None
        self._spells.clear()
        self._by_name.clear()
        self._by_name_en.clear()
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        self._spells.clear()
        self._by_name.clear()
        self._by_name_en.clear()

        if not self._spells_dir or not self._spells_dir.exists():
            return

        for fpath in sorted(self._spells_dir.glob("*.json")):
            data = json.loads(fpath.read_text(encoding="utf-8"))
            for sid, entry in data.items():
                entry["id"] = sid
                spell = Spell.from_dict(entry)
                self._spells[sid] = spell
                self._by_name[spell.name.lower()] = sid
                if spell.name_en:
                    self._by_name_en[spell.name_en.lower()] = sid

        self._loaded = True

    def add_runtime(self, spell: Spell) -> str:
        sid = spell.id or spell.name
        self._runtime[sid] = spell
        return sid

    def replace_runtime(self, spells: dict[str, Spell]):
        self._runtime = dict(spells)

    def runtime_spells(self) -> dict[str, Spell]:
        return dict(self._runtime)

    def get(self, sid: str) -> Optional[Spell]:
        self.load()
        if sid in self._runtime:
            return self._runtime[sid]
        return self._spells.get(sid)

    def find_by_name(self, name: str) -> Optional[Spell]:
        self.load()
        q = name.strip().lower()
        sid = self._by_name.get(q)
        if sid:
            return self._spells.get(sid)
        sid = self._by_name_en.get(q)
        if sid:
            return self._spells.get(sid)
        for spell in self._spells.values():
            if q in spell.name.lower() or q in spell.name_en.lower():
                return spell
        for spell in self._runtime.values():
            if q in spell.name.lower() or q in spell.name_en.lower():
                return spell
        return None

    def all_spells(self) -> list[Spell]:
        self.load()
        return list(self._spells.values()) + list(self._runtime.values())


spell_db = SpellDatabase()
