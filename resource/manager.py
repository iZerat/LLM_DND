from __future__ import annotations
import re
from typing import Optional
from uuid import uuid4
from resource.models import Inventory, Currency, ItemInstance, ItemDef
from resource.item_db import item_db
from resource.objects import NPCTemplate
from resource.packs import RESOURCE_MODE_PACK, RESOURCE_MODE_FREE
from world.entity import NPC


class ResourceResult:
    def __init__(self, success: bool, message: str = "", data: dict = None, visible: bool = True):
        self.success = success
        self.message = message
        self.data = data or {}
        self.visible = visible

    @classmethod
    def ok(cls, message: str = "", data: dict = None, visible: bool = True) -> ResourceResult:
        return cls(True, message, data, visible)

    @classmethod
    def fail(cls, message: str) -> ResourceResult:
        return cls(False, message)


class NPCProxy:
    """Thin wrapper to apply changes to an NPC via the manager."""
    def __init__(self, npc: NPC):
        self._npc = npc

    @property
    def npc(self) -> NPC:
        return self._npc


class ResourceManager:
    def __init__(self, inventory: Inventory, character=None):
        self.inv = inventory
        self.character = character
        self.world = None  # set by game_loop
        self.resource_mode = RESOURCE_MODE_PACK
        self._target_npc: Optional[NPC] = None
        # 本轮已被工具 / [状态变更] 主动改过 HP 的对象（"玩家" 或 NPC 名称），
        # 供 sync_status_block 判定「世界值 vs [状态] 声明值」谁生效。
        self.changed_npcs: set[str] = set()

    def set_target(self, name: str) -> ResourceResult:
        if not self.world:
            return ResourceResult.fail("世界状态未初始化")
        npc = self.world.get_by_name(name)
        if npc:
            self._target_npc = npc
            self.world.touch(npc.id)
            return ResourceResult.ok(f"目标设定: {npc.name}", visible=False)
        # Try to find by template
        from world.npc_templates import spawn
        npc = spawn("npc_commoner", name=name)
        if npc:
            self.world.add_active(npc)
            self._target_npc = npc
            return ResourceResult.ok(f"目标创建: {npc.name}", visible=False)
        return ResourceResult.fail(f"未找到目标: {name}")

    def resolve_item(self, query: str) -> Optional[ItemDef]:
        item = item_db.find_by_name(query)
        if item:
            return item
        item = item_db.find_by_alias(query)
        if item:
            return item
        return item_db.find_best(query)

    def _equipped_count(self, guid: str) -> int:
        return sum(1 for g in self.inv.equipped.values() if g == guid)

    def has_item(self, guid: str, quantity: int = 1) -> bool:
        return self.inv.count(guid) + self._equipped_count(guid) >= quantity

    def add_item(self, guid: str, quantity: int = 1) -> ResourceResult:
        item_def = item_db.get(guid)
        if not item_def:
            return ResourceResult.fail(f"物品 {guid} 不存在于物品库中")
        instance_ids = self.inv.add_item(guid, quantity)
        return ResourceResult.ok(f"+{quantity}x {item_def.name}", {"instance_ids": instance_ids})

    def remove_item(self, guid: str, quantity: int = 1) -> ResourceResult:
        item_def = item_db.get(guid)
        name = item_def.name if item_def else guid
        bag_have = self.inv.count(guid)
        eq_slots = [slot for slot, g in self.inv.equipped.items() if g == guid]
        total_have = bag_have + len(eq_slots)
        if total_have < quantity:
            return ResourceResult.fail(f"没有足够的 {name} (需要 {quantity}, 持有 {total_have})")
        removed = self.inv.remove_by_guid(guid, quantity)
        from_equip = 0
        for slot in eq_slots:
            if removed >= quantity:
                break
            self.inv.unequip(slot)
            from_equip += 1
            removed += self.inv.remove_by_guid(guid, quantity - removed)
        msg = f"-{removed}x {name}"
        if from_equip:
            msg += "（从装备卸下）"
        return ResourceResult.ok(msg)

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
        return ResourceResult.ok(f"+{self._format_cp(cp)}")

    def remove_currency(self, cp: int) -> ResourceResult:
        if self.inv.currency.copper < cp:
            return ResourceResult.fail(f"金钱不足 (需要 {self._format_cp(cp)}, 持有 {self.inv.currency})")
        self.inv.currency.remove(cp)
        return ResourceResult.ok(f"-{self._format_cp(cp)}")

    def _format_cp(self, cp: int) -> str:
        g = cp // 10000
        s = (cp % 10000) // 100
        c = cp % 100
        parts = []
        if g: parts.append(f"{g}金")
        if s: parts.append(f"{s}银")
        if c or not parts: parts.append(f"{c}铜")
        return "".join(parts)

    @staticmethod
    def _hp_change_display(amount: int) -> str:
        return f"{amount}点"

    def _owner_name(self) -> str:
        return self.character.name if self.character else "玩家"

    def add_hp(self, amount: int) -> ResourceResult:
        if not self.character:
            return ResourceResult.fail("无法修改HP：未传入角色对象")
        self.character.hp = min(self.character.hp + amount, self.character.max_hp)
        return ResourceResult.ok(f"{self._owner_name()} HP +{self._hp_change_display(amount)}")

    def remove_hp(self, amount: int) -> ResourceResult:
        if not self.character:
            return ResourceResult.fail("无法修改HP：未传入角色对象")
        self.character.hp = max(self.character.hp - amount, 0)
        return ResourceResult.ok(f"{self._owner_name()} HP -{self._hp_change_display(amount)}")

    def add_maxhp(self, amount: int) -> ResourceResult:
        if not self.character:
            return ResourceResult.fail("无法修改HP：未传入角色对象")
        self.character.max_hp += amount
        self.character.hp = min(self.character.hp, self.character.max_hp)
        return ResourceResult.ok(f"{self._owner_name()} 最大HP +{self._hp_change_display(amount)}")

    def remove_maxhp(self, amount: int) -> ResourceResult:
        if not self.character:
            return ResourceResult.fail("无法修改HP：未传入角色对象")
        self.character.max_hp = max(self.character.max_hp - amount, 1)
        self.character.hp = min(self.character.hp, self.character.max_hp)
        return ResourceResult.ok(f"{self._owner_name()} 最大HP -{self._hp_change_display(amount)}")

    # ── NPC operations ──

    def _get_target(self) -> Optional[NPC]:
        if self._target_npc:
            return self._target_npc
        if self.world and self.world.active:
            first = list(self.world.active.values())[0]
            if isinstance(first, NPC):
                self._target_npc = first
                return first
        return None

    def target_hp_add(self, amount: int) -> ResourceResult:
        npc = self._get_target()
        if not npc:
            return ResourceResult.fail("未设定目标")
        npc.hp = min(npc.hp + amount, npc.max_hp)
        return ResourceResult.ok(f"目标 {npc.name} HP +{self._hp_change_display(amount)}")

    def target_hp_remove(self, amount: int) -> ResourceResult:
        npc = self._get_target()
        if not npc:
            return ResourceResult.fail("未设定目标")
        npc.hp = max(npc.hp - amount, 0)
        return ResourceResult.ok(f"目标 {npc.name} HP -{self._hp_change_display(amount)}")

    def target_cp_add(self, amount: int) -> ResourceResult:
        npc = self._get_target()
        if not npc:
            return ResourceResult.fail("未设定目标")
        npc.currency.add(amount)
        return ResourceResult.ok(f"目标 {npc.name} +{self._format_cp(amount)}")

    def target_cp_remove(self, amount: int) -> ResourceResult:
        npc = self._get_target()
        if not npc:
            return ResourceResult.fail("未设定目标")
        if npc.currency.copper < amount:
            return ResourceResult.fail(f"目标 {npc.name} 金钱不足")
        npc.currency.remove(amount)
        return ResourceResult.ok(f"目标 {npc.name} -{self._format_cp(amount)}")

    def npc_add_issue(self, req: dict) -> Optional[str]:
        """校验 npc_add 请求是否可执行（原子拒绝前置检查）。

        返回问题描述；None 表示可通过。
        pack（查表创建）: 名称必须在资源库中。
        free（填表创建）: 表单必须通过 NPCTemplate 校验。
        """
        fields = req.get("fields") or {}
        name = str(fields.get("name", "")).strip()
        if not name:
            return "npc_add 缺少名称"
        if re.search(r"[（）()]", name):
            return f"NPC名称「{name}」含括号，事件描述（如“已逃窜”）应写进[事件]，名称用稳定角色名"
        if self.resource_mode == RESOURCE_MODE_FREE:
            _, errs = NPCTemplate.from_form(fields)
            return "；".join(errs) if errs else None
        from world.npc_templates import npc_catalog
        if npc_catalog.find_by_name(name):
            return None
        return f"NPC「{name}」不在资源库中"

    def npc_add(self, fields: dict) -> ResourceResult:
        """按当前资源策略创建 NPC 并设为目标。

        pack（查表创建）: 按名称查 statblocks/templates，命中即按库生成。
        free（填表创建）: 按 NPCTemplate 表单校验，创建运行时模板并生成实例。
        """
        from world.npc_templates import npc_catalog
        from resource.attitude import label_to_int
        name = str(fields.get("name", "")).strip()
        if not name:
            return ResourceResult.fail("npc_add 缺少名称")
        if self.resource_mode == RESOURCE_MODE_FREE:
            tmpl, errs = NPCTemplate.from_form(fields)
            if errs:
                return ResourceResult.fail("；".join(errs))
            tid = npc_catalog.add_runtime(
                f"npc_runtime_{uuid4().hex[:8]}", tmpl.to_template_dict()
            )
            npc = npc_catalog.spawn(tid, name=name)
        else:
            found = npc_catalog.find_by_name(name)
            if not found:
                return ResourceResult.fail(f"NPC「{name}」不在资源库中")
            npc = npc_catalog.spawn(found["id"], name=name)
            attitude_cn = str(fields.get("attitude", "")).strip()
            if attitude_cn:
                v = label_to_int(attitude_cn)
                if v is not None:
                    npc.attitude = v
        if not npc:
            return ResourceResult.fail(f"NPC「{name}」创建失败")
        if self.world:
            self.world.add_active(npc)
        self._target_npc = npc
        return ResourceResult.ok(f"NPC创建: {npc.name}", visible=False)

    # ── 物品填表创建（仅 free 模式）──

    def item_add_issue(self, req: dict) -> Optional[str]:
        """校验 item_add 请求是否可执行（原子拒绝前置检查）。"""
        if self.resource_mode != RESOURCE_MODE_FREE:
            return "item_add 仅适用于填表创建模式"
        fields = req.get("fields") or {}
        _, errs = ItemDef.from_form(fields, guid="runtime_")
        return "；".join(errs) if errs else None

    def item_add(self, fields: dict) -> ResourceResult:
        """填表创建物品：校验 → 运行时 ItemDef。

        只定义不发放；如需进入背包，由 [物品变更] 中的 + 名称 xN 引用。
        """
        if self.resource_mode != RESOURCE_MODE_FREE:
            return ResourceResult.fail("item_add 仅适用于填表创建模式")
        item_def, errs = ItemDef.from_form(fields, guid=f"runtime_{uuid4().hex[:8]}")
        if errs:
            return ResourceResult.fail("；".join(errs))
        item_db.add_runtime(item_def)
        return ResourceResult.ok(f"新物品定义: {item_def.name}")

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
            elif action == "hp_add":
                results.append(self.add_hp(req["amount"]))
            elif action == "hp_remove":
                results.append(self.remove_hp(req["amount"]))
            elif action == "maxhp_add":
                results.append(self.add_maxhp(req["amount"]))
            elif action == "maxhp_remove":
                results.append(self.remove_maxhp(req["amount"]))
            elif action == "set_target":
                results.append(self.set_target(req["name"]))
            elif action == "target_hp_add":
                results.append(self.target_hp_add(req["amount"]))
            elif action == "target_hp_remove":
                results.append(self.target_hp_remove(req["amount"]))
            elif action == "target_cp_add":
                results.append(self.target_cp_add(req["amount"]))
            elif action == "target_cp_remove":
                results.append(self.target_cp_remove(req["amount"]))
            elif action == "npc_add":
                results.append(self.npc_add(req["fields"]))
            elif action == "item_add":
                results.append(self.item_add(req["fields"]))
            else:
                results.append(ResourceResult.fail(f"未知操作: {action}"))
        return results
