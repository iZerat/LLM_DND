from __future__ import annotations
from typing import Optional
from resource.models import Inventory, Currency, ItemInstance, ItemDef
from resource.item_db import item_db


class ResourceResult:
    def __init__(self, success: bool, message: str = "", data: dict = None):
        self.success = success
        self.message = message
        self.data = data or {}

    @classmethod
    def ok(cls, message: str = "", data: dict = None) -> ResourceResult:
        return cls(True, message, data)

    @classmethod
    def fail(cls, message: str) -> ResourceResult:
        return cls(False, message)


class ResourceManager:
    def __init__(self, inventory: Inventory):
        self.inv = inventory

    def resolve_item(self, query: str) -> Optional[ItemDef]:
        item = item_db.find_by_name(query)
        if item:
            return item
        item = item_db.find_by_alias(query)
        if item:
            return item
        return item_db.find_best(query)

    def has_item(self, guid: str, quantity: int = 1) -> bool:
        return self.inv.count(guid) >= quantity

    def add_item(self, guid: str, quantity: int = 1) -> ResourceResult:
        item_def = item_db.get(guid)
        if not item_def:
            return ResourceResult.fail(f"物品 {guid} 不存在于物品库中")
        instance_ids = self.inv.add_item(guid, quantity)
        return ResourceResult.ok(f"+{quantity}x {item_def.name}", {"instance_ids": instance_ids})

    def remove_item(self, guid: str, quantity: int = 1) -> ResourceResult:
        item_def = item_db.get(guid)
        name = item_def.name if item_def else guid
        if not self.has_item(guid, quantity):
            got = self.inv.count(guid)
            return ResourceResult.fail(f"背包中没有足够的 {name} (需要 {quantity}, 持有 {got})")
        removed = self.inv.remove_by_guid(guid, quantity)
        return ResourceResult.ok(f"-{removed}x {name}")

    def equip(self, slot: str, guid: str) -> ResourceResult:
        item_def = item_db.get(guid)
        if not item_def:
            return ResourceResult.fail(f"物品 {guid} 不存在于物品库中")
        if not self.inv.count(guid):
            return ResourceResult.fail(f"背包中没有 {item_def.name}")
        success = self.inv.equip(slot, guid)
        if not success:
            return ResourceResult.fail(f"{item_def.name} 无法装备到 {slot} 槽位")
        return ResourceResult.ok(f"已装备 {item_def.name} 到 {slot}")

    def unequip(self, slot: str) -> ResourceResult:
        from loc import tr
        eq = self.inv.get_equipped(slot)
        if not eq or not eq.guid:
            slot_name = tr(f"slot:{slot}")
            return ResourceResult.fail(f"{slot_name} 槽位为空")
        item_def = item_db.get(eq.guid)
        name = item_def.name if item_def else eq.guid
        self.inv.unequip(slot)
        return ResourceResult.ok(f"已从 {slot} 卸下 {name}")

    def add_currency(self, cp: int) -> ResourceResult:
        self.inv.currency.add(cp)
        return ResourceResult.ok(f"金币 +{self._format_cp(cp)}")

    def remove_currency(self, cp: int) -> ResourceResult:
        if self.inv.currency.copper < cp:
            return ResourceResult.fail(f"金币不足 (需要 {self._format_cp(cp)}, 持有 {self.inv.currency})")
        self.inv.currency.remove(cp)
        return ResourceResult.ok(f"金币 -{self._format_cp(cp)}")

    def _format_cp(self, cp: int) -> str:
        g = cp // 100
        s = (cp % 100) // 10
        c = cp % 10
        parts = []
        if g: parts.append(f"{g}金")
        if s: parts.append(f"{s}银")
        if c or not parts: parts.append(f"{c}铜")
        return "".join(parts)

    def process_requests(self, requests: list[dict]) -> list[ResourceResult]:
        results = []
        for req in requests:
            action = req.get("action")
            if action == "add":
                results.append(self.add_item(req["guid"], req.get("quantity", 1)))
            elif action == "remove":
                results.append(self.remove_item(req["guid"], req.get("quantity", 1)))
            elif action == "equip":
                results.append(self.equip(req["slot"], req["guid"]))
            elif action == "unequip":
                results.append(self.unequip(req["slot"]))
            elif action == "currency_add":
                results.append(self.add_currency(req["amount"]))
            elif action == "currency_remove":
                results.append(self.remove_currency(req["amount"]))
            else:
                results.append(ResourceResult.fail(f"未知操作: {action}"))
        return results
