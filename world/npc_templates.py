import json
from pathlib import Path
from typing import Optional
from uuid import uuid4
from world.entity import NPC
from resource.packs import default_pack_dir


class NPCCatalog:
    def __init__(self, base_dir: Optional[Path] = None):
        self._base_dir = Path(base_dir) if base_dir else default_pack_dir() / "npcs"
        self._templates: dict[str, dict] = {}
        self._runtime_templates: dict[str, dict] = {}
        self._loaded = False

    def set_base_dir(self, base_dir: Optional[Path]):
        self._base_dir = Path(base_dir) if base_dir else None
        self._templates.clear()
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._templates.clear()
        if self._base_dir:
            for fname in ("templates.json", "statblocks.json"):
                path = self._base_dir / fname
                if not path.exists():
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for tid, entry in data.items():
                        entry.setdefault("id", tid)
                        self._templates[entry["id"]] = entry
                elif isinstance(data, list):
                    for entry in data:
                        if "id" in entry:
                            self._templates[entry["id"]] = entry
                        else:
                            self._templates[f"tmpl_{len(self._templates) + 1}"] = entry
        self._loaded = True

    def _all(self) -> dict[str, dict]:
        self._load()
        merged = dict(self._templates)
        merged.update(self._runtime_templates)
        return merged

    def get_template(self, template_id: str) -> Optional[dict]:
        return self._all().get(template_id)

    def find_by_name(self, name: str) -> Optional[dict]:
        q = name.strip().lower()
        if not q:
            return None
        for tmpl in self._all().values():
            if tmpl.get("name", "").strip().lower() == q:
                return tmpl
            if tmpl.get("name_en", "").strip().lower() == q:
                return tmpl
            for alias in tmpl.get("aliases", []):
                if alias.strip().lower() == q:
                    return tmpl
        return None

    def search(self, query: str, limit: int = 8) -> list[dict]:
        """模糊搜索模板（按名称/别名/种族/职业子串匹配），返回简短摘要。"""
        q = query.strip().lower()
        if not q:
            return []
        results = []
        for tmpl in self._all().values():
            fields = [
                tmpl.get("name", ""),
                tmpl.get("name_en", ""),
                *tmpl.get("aliases", []),
                tmpl.get("species", ""),
                tmpl.get("char_class", ""),
            ]
            score = max((len(q) / max(len(f.strip()), 1) if q in f.strip().lower() else 0)
                        for f in fields)
            if score > 0:
                results.append((score, tmpl))
        results.sort(key=lambda x: -x[0])
        return [
            {
                "id": t["id"],
                "name": t.get("name", t["id"]),
                "species": t.get("species", ""),
                "char_class": t.get("char_class", ""),
                "level": t.get("level", 1),
                "tags": t.get("tags", [])[:3],
            }
            for _, t in results[:limit]
        ]

    @staticmethod
    def _resolve_item_ref(entry: str) -> str:
        from resource.item_db import item_db
        if item_db.get(entry):
            return entry
        item_def = item_db.find_by_name(entry)
        if item_def:
            return item_def.guid
        return entry

    def spawn(self, template_id: str, name: str = "", attitude="") -> Optional[NPC]:
        from resource.attitude import coerce_legacy
        tmpl = self.get_template(template_id)
        if not tmpl:
            return None
        npc = NPC(
            id=f"{template_id}_{uuid4().hex[:8]}",
            name=name or tmpl.get("name", ""),
            species=tmpl.get("species", "human"),
            char_class=tmpl.get("char_class", "commoner"),
            level=tmpl.get("level", 1),
            hp=tmpl.get("hp", 8),
            max_hp=tmpl.get("max_hp", 8),
            base_ac=tmpl.get("ac", 10),
            strength=tmpl.get("strength", 10),
            dexterity=tmpl.get("dexterity", 10),
            constitution=tmpl.get("constitution", 10),
            intelligence=tmpl.get("intelligence", 10),
            wisdom=tmpl.get("wisdom", 10),
            charisma=tmpl.get("charisma", 10),
            proficiency_bonus=tmpl.get("proficiency_bonus", 2),
            skills=list(tmpl.get("skills", [])),
            saving_throws=list(tmpl.get("saving_throws", [])),
            attitude=coerce_legacy(
                tmpl.get("attitude", "neutral") if attitude in (None, "") else attitude
            ),
            tags=list(tmpl.get("tags", [])),
            is_character=bool(tmpl.get("is_character", False)),
        )
        from resource.models import Currency
        npc.currency = Currency(copper=tmpl.get("currency_cp", 0))
        entries = list(tmpl.get("inventory", [])) + list(tmpl.get("items", []))
        npc.inventory = [self._resolve_item_ref(e) for e in entries]
        return npc

    def list_templates(self) -> list[dict]:
        return [{"id": tid, "name": t.get("name", tid)} for tid, t in self._all().items()]

    def add_runtime(self, template_id: str, data: dict) -> str:
        data.setdefault("id", template_id)
        self._runtime_templates[template_id] = data
        return template_id

    def replace_runtime(self, entries: dict[str, dict]):
        self._runtime_templates = dict(entries)

    def runtime_templates(self) -> dict[str, dict]:
        return dict(self._runtime_templates)


npc_catalog = NPCCatalog()


def get_template(template_id: str) -> Optional[dict]:
    return npc_catalog.get_template(template_id)


def spawn(template_id: str, name: str = "", attitude="") -> Optional[NPC]:
    return npc_catalog.spawn(template_id, name, attitude)


def list_templates() -> list[dict]:
    return npc_catalog.list_templates()
