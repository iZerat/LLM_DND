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
        # 本轮已被工具主动改过 HP 的对象（"玩家" 或 NPC 名称），
        # 供 sync_status_block 判定「世界值 vs [状态] 声明值」谁生效。
        self.changed_npcs: set[str] = set()
        # 攻击检定待落账登记（检定器掷骰判定后，交由 LLM 经调节器工具落账；
        # 调节器据此校验数值一致性，拒绝随意/重复结算——游戏数据只经调节器变更）。
        self.pending_attacks: dict[str, dict] = {}

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

    # ── 攻击检定待落账登记（检定器 → 调节器 校验落账） ──

    def record_attack_outcome(self, target: str, damage: int = 0,
                              baseline: int = 0, applied: bool = False) -> None:
        """登记一次攻击判定的期望落账（检定器掷骰后调用，不在此处变更任何数据）。

        target=待变更对象（玩家或 NPC 名），damage=命中伤害，baseline=态度基线。
        applied=True（本地选项路径已由系统直接落账）时标记为已落账，
        供工具层校验重复结算；applied=False（d20_test 工具路径）时等待 LLM
        经 change_status / change_attitude 按此数值落账。
        """
        self.pending_attacks[target] = {
            "damage": max(damage, 0),
            "damage_applied": applied or damage <= 0,
            "baseline": baseline,
            "baseline_applied": applied or baseline == 0,
        }

    def reset_pending_attacks(self) -> None:
        self.pending_attacks.clear()

    def consume_pending_damage(self, target: str, hp: int) -> Optional[ResourceResult]:
        """工具层落账前校验：待落账攻击的伤害必须与判定一致；已落账的攻击禁止重复结算。

        返回错误 ResourceResult 表示拒绝（应中止本次变更）；None 表示放行。
        """
        pending = self.pending_attacks.get(target)
        if not pending or not pending["damage"]:
            return None
        expected = -pending["damage"]
        if not pending["damage_applied"]:
            if hp != expected:
                return ResourceResult.fail(
                    f"「{target}」本次攻击检定已判定造成 {pending['damage']} 点伤害，"
                    f"请用 change_status(target=\"{target}\", hp={expected}) 落账，不要传其他数值"
                )
            pending["damage_applied"] = True
            return None
        if hp == expected:
            return ResourceResult.fail(f"「{target}」本次攻击伤害已落账，请勿重复结算")
        return None

    def consume_pending_baseline(self, target: str, delta: int) -> Optional[ResourceResult]:
        """工具层态度基线校验：基线必须按判定值落账；已落账的基线禁止重复结算。"""
        pending = self.pending_attacks.get(target)
        if not pending or not pending["baseline"]:
            return None
        if not pending["baseline_applied"]:
            if delta != pending["baseline"]:
                return ResourceResult.fail(
                    f"「{target}」本次攻击的态度基线为 {pending['baseline']:+d}，"
                    f"请先用 change_attitude(target=\"{target}\", delta={pending['baseline']}) "
                    f"落账基线，再在后续调用中叠加额外态度变化"
                )
            pending["baseline_applied"] = True
            return None
        if delta == pending["baseline"]:
            return ResourceResult.fail(f"「{target}」本次攻击的态度基线已落账，请勿重复结算")
        return None

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
        """玩家治疗（D&D：0 HP 恢复生命 → 苏醒；死亡者普通治疗无效，需复活魔法）。"""
        if not self.character:
            return ResourceResult.fail("无法修改HP：未传入角色对象")
        c = self.character
        if c.dead:
            return ResourceResult.fail(f"{c.name} 已死亡，普通治疗无法生效（需复活魔法）")
        hp_before = c.hp
        c.hp = min(c.hp + amount, c.max_hp)
        notes = []
        if hp_before <= 0 < c.hp:
            c.stable = False
            c.death_fails = 0
            c.death_successes = 0
            notes.append("苏醒")
        return ResourceResult.ok(
            f"{self._owner_name()} HP +{c.hp - hp_before} "
            f"({hp_before}/{c.max_hp} >>> {c.hp}/{c.max_hp})"
            + ("，" + "，".join(notes) if notes else "")
        )

    def remove_hp(self, amount: int, crit: bool = False) -> ResourceResult:
        """玩家伤害（D&D 归零/濒死规则，T17）。

        - HP 归零 → 昏迷；巨量伤害（余量 ≥ 生命上限）→ 即死。
        - 0 HP 再受伤 → 死亡豁免失败（暴击 2 次）；伤害 ≥ 生命上限 → 即死；
          稳定者受伤 → 稳定被打破。
        - crit：本次伤害是否来自暴击（影响 0 HP 下的失败计数）。
        """
        if not self.character:
            return ResourceResult.fail("无法修改HP：未传入角色对象")
        c = self.character
        if c.dead:
            return ResourceResult.fail(f"{c.name} 已死亡，无法再承受伤害")
        amount = int(amount or 0)
        hp_before = c.hp
        c.hp = max(c.hp - amount, 0)
        notes: list[str] = []
        if c.hp == 0 and amount > 0:
            if hp_before == 0:
                if c.stable:
                    c.stable = False
                    notes.append("稳定被打破")
                if amount >= c.max_hp:
                    c.dead = True
                    notes.append("即死（伤害 ≥ 生命上限）")
                else:
                    fails = 2 if crit else 1
                    c.death_fails += fails
                    notes.append(f"死亡豁免失败 {fails} 次（{c.death_fails}/3）")
                    if c.death_fails >= 3:
                        c.dead = True
                        notes.append("死亡")
            else:
                overkill = amount - hp_before
                if overkill >= c.max_hp:
                    c.dead = True
                    notes.append("即死（巨量伤害 ≥ 生命上限）")
                else:
                    notes.append("昏迷")
        return ResourceResult.ok(
            f"{self._owner_name()} HP -{hp_before - c.hp} "
            f"({hp_before}/{c.max_hp} >>> {c.hp}/{c.max_hp})"
            + ("，" + "，".join(notes) if notes else "")
        )

    def set_stable(self) -> ResourceResult:
        """稳定：停止死亡豁免（仍昏迷），计数清零。医药检定/治疗行为的结果。"""
        if not self.character:
            return ResourceResult.fail("无法修改状态：未传入角色对象")
        c = self.character
        if c.dead:
            return ResourceResult.fail(f"{c.name} 已死亡")
        if c.hp > 0:
            return ResourceResult.fail(f"{c.name} 生命值大于 0，无需稳定")
        c.stable = True
        c.death_fails = 0
        c.death_successes = 0
        return ResourceResult.ok(f"{c.name} 已稳定（停止死亡豁免，仍昏迷）")

    def roll_death_save(self) -> ResourceResult:
        """系统自动死亡豁免（T17，玩家回合起手 0 HP 时调用）。

        d20：≥10 成功 / <10 失败；天然1=2 失败；天然20=恢复 1 HP 苏醒；
        3 次成功→稳定，3 次失败→死亡。
        """
        import random
        if not self.character:
            return ResourceResult.fail("无法进行死亡豁免：未传入角色对象")
        c = self.character
        if c.dead:
            return ResourceResult.fail(f"{c.name} 已死亡")
        if c.hp > 0:
            return ResourceResult.fail(f"{c.name} 生命值大于 0，无需死亡豁免")
        if c.stable:
            return ResourceResult.fail(f"{c.name} 已稳定，无需死亡豁免")
        roll = random.randint(1, 20)
        line = f"d20({roll})"
        if roll == 20:
            c.hp = min(c.max_hp, c.hp + 1)
            c.stable = False
            c.death_fails = 0
            c.death_successes = 0
            return ResourceResult.ok(
                f"{line} 天然20：恢复 1 点生命，{c.name} 苏醒！",
                {"outcome": "awake", "roll": roll},
            )
        if roll == 1:
            c.death_fails += 2
            msg = f"{line} 天然1：死亡豁免失败 2 次（失败 {c.death_fails}/3）"
            if c.death_fails >= 3:
                c.dead = True
                msg += "，第 3 次失败，死亡！"
                return ResourceResult.ok(msg, {"outcome": "dead", "roll": roll})
            return ResourceResult.ok(msg, {"outcome": "fail", "roll": roll})
        if roll >= 10:
            c.death_successes += 1
            msg = f"{line} 成功（≥10）：死亡豁免成功 {c.death_successes}/3"
            if c.death_successes >= 3:
                c.stable = True
                c.death_fails = 0
                c.death_successes = 0
                msg += "，第 3 次成功，转为稳定（停止豁免，仍昏迷）"
                return ResourceResult.ok(msg, {"outcome": "stable", "roll": roll})
            return ResourceResult.ok(msg, {"outcome": "success", "roll": roll})
        c.death_fails += 1
        msg = f"{line} 失败（<10）：死亡豁免失败 {c.death_fails}/3"
        if c.death_fails >= 3:
            c.dead = True
            msg += "，第 3 次失败，死亡！"
            return ResourceResult.ok(msg, {"outcome": "dead", "roll": roll})
        return ResourceResult.ok(msg, {"outcome": "fail", "roll": roll})

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

    def npc_change_status(self, name: str, hp: int = 0, max_hp: int = 0) -> ResourceResult:
        """按名称对 NPC 增减 HP / 最大HP（负数=扣减）。NPC 生命值变更的唯一落账漏斗。

        由工具箱 change_status 与 NPC 机械结算共用，禁止在漏斗外直写 npc.hp / npc.max_hp。
        0 HP → 倒地昏迷留场（可治疗苏醒，BG3 式可复活）；巨量伤害（余量 ≥ 生命上限）→ 即死；
        已死亡者不接受治疗/伤害（复活留待高等级法术，本期不做）。
        """
        npc = self.world.get_by_name(name) if self.world else None
        if not npc:
            return ResourceResult.fail(f"未找到 NPC「{name}」")
        parts: list[str] = []
        if hp:
            if npc.dead:
                parts.append(f"{npc.name} 已死亡，无法变更 HP")
            else:
                hp_before = npc.hp
                if hp > 0:
                    npc.hp = min(npc.hp + hp, npc.max_hp)
                    parts.append(
                        f"{npc.name} HP +{npc.hp - hp_before} "
                        f"({hp_before}/{npc.max_hp} >>> {npc.hp}/{npc.max_hp})"
                    )
                    if hp_before <= 0 < npc.hp:
                        parts.append("苏醒")
                else:
                    npc.hp = max(npc.hp + hp, 0)
                    parts.append(
                        f"{npc.name} HP {npc.hp - hp_before:+d} "
                        f"({hp_before}/{npc.max_hp} >>> {npc.hp}/{npc.max_hp})"
                    )
                    if npc.hp == 0:
                        if hp_before == 0:
                            parts.append("（仍倒地）")
                        else:
                            overkill = -hp - hp_before
                            if overkill >= npc.max_hp:
                                npc.dead = True
                                parts.append("即死（巨量伤害 ≥ 生命上限）")
                            else:
                                parts.append("倒地昏迷")
        if max_hp:
            if npc.dead:
                parts.append(f"{npc.name} 已死亡，无法变更最大HP")
            else:
                max_before = npc.max_hp
                npc.max_hp = max(npc.max_hp + max_hp, 1)
                npc.hp = min(npc.hp, npc.max_hp)
                parts.append(f"{npc.name} 最大HP {max_hp:+d} ({max_before} >>> {npc.max_hp})")
        return ResourceResult.ok("，".join(parts) if parts else "无变化")

    def change_attitude(self, name: str, delta: int = 0, reason: str = "",
                        event: str = "") -> ResourceResult:
        """NPC 态度变更的唯一漏斗（D2）：clamp ±100 + attitude_reasons 落账。

        delta 为该轮净变化量（可正可负）；reason 为叙事理由（LLM 必填，审计用）；
        event 为事件表 id（可选，供攻击基线等自动落账标注）。
        """
        from resource.attitude import clamp
        npc = self.world.get_by_name(name) if self.world else None
        if not npc:
            return ResourceResult.fail(f"未找到 NPC「{name}」")
        old = int(getattr(npc, "attitude", 0) or 0)
        new = clamp(old + int(delta or 0))
        applied = new - old
        npc.attitude = new
        reasons = getattr(npc, "attitude_reasons", None)
        if not isinstance(reasons, list):
            reasons = []
            npc.attitude_reasons = reasons
        reasons.append({
            "event": event or "manual",
            "delta": applied,
            "reason": reason,
            "source": "manager.change_attitude",
        })
        return ResourceResult.ok(f"{npc.name} 态度 {applied:+d} ({old:+d} >>> {new:+d})")

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

        只定义不发放；如需进入背包，调用 grant_item 工具 + 名称引用。
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
