from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
from uuid import uuid4

from world.object import Object


class ItemType(str, Enum):
    WEAPON = "weapon"
    ARMOR = "armor"
    SHIELD = "shield"
    CONSUMABLE = "consumable"
    AMMUNITION = "ammunition"
    TOOL = "tool"
    EQUIPMENT = "equipment"
    QUEST = "quest"
    MISC = "misc"


class EquipmentSlot(str, Enum):
    WEAPON = "weapon"
    OFF_HAND = "off_hand"
    HEAD = "head"
    BODY = "body"
    BACK = "back"
    NECK = "neck"
    RING1 = "ring1"
    RING2 = "ring2"


EQUIPPABLE_TYPES: dict[EquipmentSlot, set[ItemType]] = {
    EquipmentSlot.WEAPON: {ItemType.WEAPON},
    EquipmentSlot.OFF_HAND: {ItemType.WEAPON, ItemType.SHIELD},
    EquipmentSlot.HEAD: {ItemType.ARMOR},
    EquipmentSlot.BODY: {ItemType.ARMOR},
    EquipmentSlot.BACK: {ItemType.ARMOR, ItemType.EQUIPMENT},
    EquipmentSlot.NECK: {ItemType.EQUIPMENT},
    EquipmentSlot.RING1: {ItemType.EQUIPMENT},
    EquipmentSlot.RING2: {ItemType.EQUIPMENT},
}

ALL_SLOTS = list(EquipmentSlot)


@dataclass
class ItemDef(Object):
    """物品定义基类（继承 Object，纳入世界对象体系）。

    武器/护甲/消耗品等字段平铺在基类以保持存档兼容；
    具体子类（WeaponDef/ArmorDef/ConsumableDef）为类型提供语义化行为。
    guid 为物品身份标识（资源库主键）。
    """
    guid: str = ""
    name: str = ""
    name_en: str = ""
    type: ItemType = ItemType.MISC
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    value_cp: int = 0
    damage_dice: str = ""
    damage_type: str = ""
    weapon_category: str = ""
    weapon_range: str = ""
    properties: list[str] = field(default_factory=list)
    base_ac: int = 0
    dex_cap: int = 99
    strength_req: int = 0
    stealth_disadvantage: bool = False
    armor_category: str = ""
    heal_dice: str = ""
    heal_bonus: int = 0
    effect: str = ""

    def __post_init__(self):
        super().__post_init__()
        if isinstance(self.type, str):
            try:
                self.type = ItemType(self.type)
            except ValueError:
                self.type = ItemType.MISC

    def matches_name(self, query: str) -> bool:
        q = query.strip().lower()
        if self.name.lower() == q or self.name_en.lower() == q:
            return True
        for alias in self.aliases:
            if alias.lower() == q:
                return True
        return False

    def matches_fuzzy(self, query: str) -> float:
        q = query.strip().lower()
        if self.name.lower() == q or self.name_en.lower() == q:
            return 1.0
        for alias in self.aliases:
            if alias.lower() == q:
                return 1.0
        if q in self.name.lower() or q in self.name_en.lower():
            return 0.8
        for alias in self.aliases:
            if q in alias.lower():
                return 0.8
        for tag in self.tags:
            if q == tag.lower():
                return 0.6
        return 0.0

    @classmethod
    def schema(cls):
        from resource.objects import FieldSpec, ResourceSchema, TYPE_INT, TYPE_LIST
        return ResourceSchema(fields=[
            FieldSpec("name", "名称", required=True),
            FieldSpec("name_en", "英文名", required=False),
            FieldSpec("type", "类型", required=False, options=["武器", "护甲", "盾牌", "消耗品", "弹药", "工具", "装备", "任务", "杂物"], default="杂物"),
            FieldSpec("tags", "标签", type=TYPE_LIST, required=False),
            FieldSpec("aliases", "别名", type=TYPE_LIST, required=False),
            FieldSpec("description", "描述", required=False),
            FieldSpec("value_cp", "价值(铜币)", type=TYPE_INT, min_value=0, required=False, default=0),
            FieldSpec("damage_dice", "伤害骰(如2d6)", required=False),
            FieldSpec("damage_type", "伤害类型", required=False),
            FieldSpec("weapon_category", "武器类别", required=False, options=["简易", "军用"]),
            FieldSpec("weapon_range", "武器射程", required=False),
            FieldSpec("properties", "特性", type=TYPE_LIST, required=False),
            FieldSpec("base_ac", "基础护甲", type=TYPE_INT, min_value=0, required=False, default=0),
            FieldSpec("dex_cap", "敏捷上限", type=TYPE_INT, min_value=0, required=False, default=99),
            FieldSpec("strength_req", "力量需求", type=TYPE_INT, min_value=0, required=False, default=0),
            FieldSpec("armor_category", "护甲类别", required=False, options=["轻甲", "中甲", "重甲"]),
            FieldSpec("heal_dice", "治疗骰(如1d4)", required=False),
            FieldSpec("heal_bonus", "治疗加成", type=TYPE_INT, min_value=0, required=False, default=0),
            FieldSpec("effect", "效果", required=False),
        ])

    @classmethod
    def from_form(cls, values: dict, guid: str) -> tuple[Optional[ItemDef], list[str]]:
        schema = cls.schema()
        errors = schema.validate(values)
        if errors:
            return None, errors
        vals = schema.clamp(values)

        ITEM_TYPE_CN_TO_EN = {
            "武器": "weapon", "护甲": "armor", "盾牌": "shield", "消耗品": "consumable",
            "弹药": "ammunition", "工具": "tool", "装备": "equipment", "任务": "quest", "杂物": "misc",
        }
        WEAPON_CAT_CN_TO_EN = {"简易": "simple", "军用": "martial"}
        ARMOR_CAT_CN_TO_EN = {"轻甲": "light", "中甲": "medium", "重甲": "heavy"}

        def split_list(v) -> list[str]:
            if not v:
                return []
            if isinstance(v, list):
                raw = v
            else:
                raw = [x.strip() for x in re.split(r"[,/、]", str(v)) if x.strip()]
            out = []
            for x in raw:
                x = str(x).strip().strip("[]")
                if x and x not in out:
                    out.append(x)
            return out

        def to_int(v, default):
            try:
                return int(str(v).strip())
            except (TypeError, ValueError):
                return default

        type_cn = str(vals.get("type") or "杂物").strip()
        try:
            item_type = ItemType(ITEM_TYPE_CN_TO_EN.get(type_cn, type_cn))
        except ValueError:
            return None, [f"type 无效的类型: {type_cn}"]

        item = item_def_from_dict({
            "guid": guid,
            "name": str(vals.get("name", "")).strip(),
            "name_en": str(vals.get("name_en", "")).strip(),
            "type": item_type,
            "tags": split_list(vals.get("tags")),
            "aliases": split_list(vals.get("aliases")),
            "description": str(vals.get("description", "")).strip(),
            "value_cp": to_int(vals.get("value_cp"), 0),
            "damage_dice": str(vals.get("damage_dice", "")).strip(),
            "damage_type": str(vals.get("damage_type", "")).strip(),
            "weapon_category": WEAPON_CAT_CN_TO_EN.get(str(vals.get("weapon_category", "")).strip(), str(vals.get("weapon_category", "")).strip()),
            "weapon_range": str(vals.get("weapon_range", "")).strip(),
            "properties": split_list(vals.get("properties")),
            "base_ac": to_int(vals.get("base_ac"), 0),
            "dex_cap": to_int(vals.get("dex_cap"), 99),
            "strength_req": to_int(vals.get("strength_req"), 0),
            "armor_category": ARMOR_CAT_CN_TO_EN.get(str(vals.get("armor_category", "")).strip(), str(vals.get("armor_category", "")).strip()),
            "heal_dice": str(vals.get("heal_dice", "")).strip(),
            "heal_bonus": to_int(vals.get("heal_bonus"), 0),
            "effect": str(vals.get("effect", "")).strip(),
        })
        return item, []

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d


@dataclass
class WeaponDef(ItemDef):
    """武器：伤害骰/类型/特性语义化。"""

    def roll_damage(self) -> int:
        import re as _re
        d = _re.match(r"(\d+)d(\d+)", self.damage_dice)
        if not d:
            return 0
        from random import randint
        return sum(randint(1, int(d.group(2))) for _ in range(int(d.group(1))))


@dataclass
class ArmorDef(ItemDef):
    """护甲/盾牌：AC 相关语义化。"""

    @property
    def is_shield(self) -> bool:
        return self.type == ItemType.SHIELD


@dataclass
class ConsumableDef(ItemDef):
    """消耗品：heal_dice/heal_bonus/effect 语义化。"""

    def roll_effect(self) -> dict:
        """掷出治疗效果，返回落地字典（heal 字段）+ 附带 effect 说明。"""
        import re as _re
        from random import randint
        heal = 0
        d = _re.match(r"(\d+)d(\d+)", self.heal_dice)
        if d:
            heal = sum(randint(1, int(d.group(2))) for _ in range(int(d.group(1)))) + self.heal_bonus
        else:
            heal = self.heal_bonus
        return {"heal": heal, "effect": self.effect}


def item_def_from_dict(entry: dict) -> ItemDef:
    """按 type 分派构建多态物品定义；无法识别时回退基类（兼容旧存档）。"""
    t = entry.get("type")
    if isinstance(t, str):
        try:
            t = ItemType(t)
        except ValueError:
            t = None
    if t == ItemType.WEAPON:
        return WeaponDef(**entry)
    if t in (ItemType.ARMOR, ItemType.SHIELD):
        return ArmorDef(**entry)
    if t == ItemType.CONSUMABLE:
        return ConsumableDef(**entry)
    return ItemDef(**entry)


@dataclass
class ItemInstance:
    instance_id: str = ""
    guid: str = ""
    quantity: int = 1

    def __post_init__(self):
        if not self.instance_id:
            self.instance_id = uuid4().hex[:12]

    @property
    def def_(self) -> Optional[ItemDef]:
        from resource.item_db import item_db
        return item_db.get(self.guid)

    @property
    def name(self) -> str:
        d = self.def_
        return d.name if d else self.guid

    @property
    def name_en(self) -> str:
        d = self.def_
        return d.name_en if d and d.name_en else self.guid


@dataclass
class Currency:
    copper: int = 0

    @property
    def gold(self) -> int:
        return self.copper // 10000

    @property
    def silver(self) -> int:
        return (self.copper % 10000) // 100

    @property
    def copper_display(self) -> int:
        return self.copper % 100

    def add(self, cp: int):
        self.copper += cp

    def remove(self, cp: int) -> bool:
        if self.copper < cp:
            return False
        self.copper -= cp
        return True

    def __str__(self) -> str:
        return f"{self.gold}金 {self.silver}银 {self.copper_display}铜"


def format_cp(cp: int) -> str:
    """把铜币数换算成 金银铜 显示（1金=10000铜，1银=100铜）。"""
    cp = int(cp or 0)
    neg = cp < 0
    cp = abs(cp)
    g, cp = divmod(cp, 10000)
    s, c = divmod(cp, 100)
    parts = []
    if g:
        parts.append(f"{g}金")
    if s:
        parts.append(f"{s}银")
    if c or not parts:
        parts.append(f"{c}铜")
    return ("-" if neg else "") + "".join(parts)


def format_signed(v: int) -> str:
    """带符号整数显示：负数「-8」、正数「+8」、零「0」（不写成 +0）。"""
    v = int(v)
    if v > 0:
        return f"+{v}"
    if v < 0:
        return f"{v}"
    return "0"


def format_cp_change(actor: str, delta_cp: int, before_cp: int, after_cp: int) -> str:
    """结构化金钱变更行：Actor 金钱 变更 (旧值 >>> 新值)，金银铜换算。"""
    sign = "+" if delta_cp >= 0 else "-"
    return (
        f"{actor} 金钱 {sign}{format_cp(abs(int(delta_cp or 0)))} "
        f"({format_cp(before_cp)} >>> {format_cp(after_cp)})"
    )


@dataclass
class Inventory:
    # bag: instance_id -> ItemInstance (each instance distinct, no quantity merging)
    items: dict[str, ItemInstance] = field(default_factory=dict)
    # equipped: slot_key (English) -> guid
    # We store guid (not instance_id) because we only need the template reference.
    # When unequipping, a new instance is created in bag.
    equipped: dict[str, Optional[str]] = field(default_factory=lambda: {
        s.value: None for s in ALL_SLOTS
    })
    currency: Currency = field(default_factory=Currency)

    # ── bag query ──

    def count(self, guid: str) -> int:
        return sum(1 for inst in self.items.values() if inst.guid == guid)

    def get_by_guid(self, guid: str) -> list[ItemInstance]:
        return [inst for inst in self.items.values() if inst.guid == guid]

    def get(self, instance_id: str) -> Optional[ItemInstance]:
        return self.items.get(instance_id)

    def all_instances(self) -> list[ItemInstance]:
        return list(self.items.values())

    # ── bag add / remove ──

    def add_item(self, guid: str, quantity: int = 1) -> list[str]:
        created = []
        for _ in range(quantity):
            inst = ItemInstance(guid=guid, quantity=1)
            self.items[inst.instance_id] = inst
            created.append(inst.instance_id)
        return created

    def remove_instance(self, instance_id: str) -> bool:
        if instance_id not in self.items:
            return False
        del self.items[instance_id]
        return True

    def remove_by_guid(self, guid: str, quantity: int = 1) -> int:
        to_del = [iid for iid, inst in self.items.items()
                  if inst.guid == guid][:quantity]
        for iid in to_del:
            del self.items[iid]
        return len(to_del)

    # ── equip / unequip ──
    #
    # equipped[slot] stores guid. The item instance remains in `items` with
    # a flag... Actually, we remove it from bag when equipping.
    # On unequip we create a fresh instance in bag.

    def equip(self, slot: str, guid: str) -> bool:
        from resource.item_db import item_db
        slot_enum = EquipmentSlot(slot)
        item_def = item_db.get(guid)
        if not item_def:
            return False
        allowed = EQUIPPABLE_TYPES.get(slot_enum, set())
        if item_def.type not in allowed:
            return False
        if not self.count(guid):
            return False
        current_guid = self.equipped.get(slot)
        if current_guid:
            self.unequip(slot)
        self.remove_by_guid(guid, 1)
        self.equipped[slot] = guid
        return True

    def unequip(self, slot: str) -> bool:
        guid = self.equipped.get(slot)
        if not guid:
            return False
        self.add_item(guid, 1)
        self.equipped[slot] = None
        return True

    def get_equipped(self, slot: str) -> Optional[ItemInstance]:
        guid = self.equipped.get(slot)
        if not guid:
            return None
        return ItemInstance(guid=guid, quantity=1)
