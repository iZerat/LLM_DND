"""角色模板：把创建好的角色（含背包/装备/金钱）存到本地，供新游戏导入。"""
from __future__ import annotations
import json
from pathlib import Path

from core.character import Character
from resource.models import Inventory, Currency, ItemInstance

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "character_templates"


def _dir() -> Path:
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    return TEMPLATE_DIR


def list_templates() -> list[str]:
    """返回所有模板的 stem（按修改时间倒序）。"""
    if not TEMPLATE_DIR.exists():
        return []
    files = sorted(TEMPLATE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem for p in files]


def template_data(char: Character) -> dict:
    """角色模板数据：角色卡 + 背包/装备/金钱 的完整快照（可独立持久化）。"""
    data = char.to_dict()
    data["inventory"] = {
        "bag": [
            {"instance_id": inst.instance_id, "guid": inst.guid}
            for inst in char.inventory.all_instances()
        ],
        "equip": {slot: guid for slot, guid in char.inventory.equipped.items() if guid},
        "copper": char.inventory.currency.copper,
    }
    return data


def save_template(char: Character, name: str | None = None) -> Path:
    """序列化角色（含背包/装备/金钱）为本地模板文件。"""
    name = (name or char.name or "未命名角色").strip()
    fp = _dir() / f"{name}.json"
    fp.write_text(json.dumps(template_data(char), ensure_ascii=False, indent=2), encoding="utf-8")
    return fp


def _build_inventory(inv_data: dict) -> Inventory:
    inv = Inventory()
    for entry in inv_data.get("bag", []):
        if "instance_id" in entry:
            inst = ItemInstance(instance_id=entry["instance_id"], guid=entry["guid"], quantity=1)
            inv.items[inst.instance_id] = inst
        else:
            inv.add_item(entry["guid"], entry.get("quantity", 1))
    for slot, guid in inv_data.get("equip", {}).items():
        inv.equipped[slot] = guid
    inv.currency = Currency(copper=inv_data.get("copper", 0))
    return inv


def load_template(stem: str) -> Character:
    """从本地模板文件重建角色。"""
    fp = TEMPLATE_DIR / f"{stem}.json"
    data = json.loads(fp.read_text(encoding="utf-8"))
    inv_data = data.pop("inventory", {})
    char = Character(**data)
    char.inventory = _build_inventory(inv_data)
    return char
