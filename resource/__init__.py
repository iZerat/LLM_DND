from resource.models import (
    ItemType, EquipmentSlot, ALL_SLOTS, EQUIPPABLE_TYPES,
    ItemDef, ItemInstance, Currency, Inventory,
)
from resource.item_db import item_db, ItemDatabase
from resource.manager import ResourceManager, ResourceResult
from resource.llm_parser import parse_item_changes, parse_status_changes
