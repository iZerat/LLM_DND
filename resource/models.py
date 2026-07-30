from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from uuid import uuid4


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
class ItemDef:
    guid: str
    name: str
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
        return self.copper // 100

    @property
    def silver(self) -> int:
        return (self.copper % 100) // 10

    @property
    def copper_display(self) -> int:
        return self.copper % 10

    def add(self, cp: int):
        self.copper += cp

    def remove(self, cp: int) -> bool:
        if self.copper < cp:
            return False
        self.copper -= cp
        return True

    def __str__(self) -> str:
        return f"{self.gold}金 {self.silver}银 {self.copper_display}铜"


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
