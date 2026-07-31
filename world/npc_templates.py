import json
from pathlib import Path
from typing import Optional
from uuid import uuid4
from world.entity import NPC

_NPC_TEMPLATES: dict[str, dict] = {}
_loaded = False


def _load():
    global _loaded
    if _loaded:
        return
    path = Path(__file__).resolve().parent.parent / "data" / "npcs" / "templates.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data:
            _NPC_TEMPLATES[entry["id"]] = entry
    _loaded = True


def get_template(template_id: str) -> Optional[dict]:
    _load()
    return _NPC_TEMPLATES.get(template_id)


def spawn(template_id: str, name: str = "", attitude: str = "") -> Optional[NPC]:
    tmpl = get_template(template_id)
    if not tmpl:
        return None
    npc = NPC(
        id=f"{template_id}_{uuid4().hex[:8]}",
        name=name or tmpl["name"],
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
        attitude=attitude or tmpl.get("attitude", "neutral"),
        tags=list(tmpl.get("tags", [])),
    )
    from resource.models import Currency
    npc.currency = Currency(copper=tmpl.get("currency_cp", 0))
    npc.inventory = list(tmpl.get("inventory", []))
    return npc


def list_templates() -> list[dict]:
    _load()
    return [{"id": tid, "name": t["name"]} for tid, t in _NPC_TEMPLATES.items()]
