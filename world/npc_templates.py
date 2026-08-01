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
            level=tmpl.get("level", 0),
            hp=tmpl.get("hp", 8),
            max_hp=tmpl.get("max_hp", 8),
            ac=tmpl.get("ac", 10),
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
        )
        from resource.models import Currency
        npc.currency = Currency(copper=tmpl.get("currency_cp", 0))
        entries = list(tmpl.get("inventory", [])) + list(tmpl.get("items", []))
        npc.inventory = [self._resolve_item_ref(e) for e in entries]
        return npc

    def list_templates(self) -> list[dict]:
        return [{"id": tid, "name": t.get("name", tid)} for tid, t in self._all().items()]

    def add_runtime(self, template_id: str, data: dict) -> str:
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
