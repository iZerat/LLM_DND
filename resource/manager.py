from __future__ import annotations
import os
import re
from typing import Optional
from uuid import uuid4
from resource.models import Inventory, Currency, ItemInstance, ItemDef, format_cp, format_cp_change
from resource.item_db import item_db
from resource.objects import NPCTemplate
from resource.packs import RESOURCE_MODE_PACK, RESOURCE_MODE_FREE
from world.actor import Actor


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name, "") or str(default)).strip())
    except (TypeError, ValueError):
        return default


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


# 选项文本中 LLM 可能自造的括号技术标注关键词（攻击/目标/检定/DC/技能/属性）
_CHOICE_TECH_KEYWORDS = (
    "攻击|检定|豁免|DC|威吓|欺瞒|欺骗|察觉|潜行|调查|洞悉|表演|运动|体操|生存|隐匿|说服|"
    "自然|医药|奥术|历史|宗教|驯兽|先攻|力量|敏捷|体质|智力|感知|魅力|难度|判定|AC"
)
# 尾部「（攻击 对哥布林）/（魅力威吓）/（魅力检定 DC 15）」类括号技术标注
_CHOICE_TECH_SUFFIX_RE = re.compile(
    r"\s*[（(][^（()）]*(?:" + _CHOICE_TECH_KEYWORDS + r")[^（()）]*[）)]\s*$"
)


def strip_choice_annotation(label: str) -> str:
    """剥离选项文本尾部自带的括号技术标注（系统会另行渲染检定类型/目标/DC）。"""
    return _CHOICE_TECH_SUFFIX_RE.sub("", label or "").strip()


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
        # 工具层段内防重复日志：同一目标同一类型同一数值的变更只允许一次，
        # 配合 pending_attacks 防止 LLM 重复调用工具造成数据多次修改（C1/C3）。
        self.change_log: dict[str, list[tuple[str, int]]] = {}
        # 结构化选择（DM 通过 create_choice 工具创建，替代正则解析）
        self.choices: list = []
        self.next_choice_index: int = 1
        self.pending_changes: list[str] = []

    def reset_choices(self) -> None:
        self.choices.clear()
        self.next_choice_index = 1
        # 资源创建管线：查表失败计数（每回合重置）+ 回退开关
        self.lookup_fail_count: int = 0
        self.resource_lookup_retries: int = _env_int("RESOURCE_LOOKUP_RETRIES", 2)
        self.allow_free_create: bool = (
            os.getenv("ALLOW_FREE_CREATE", "").strip().lower() in ("1", "true", "yes", "on")
        )

    def set_target(self, name: str) -> ResourceResult:
        if not self.world:
            return ResourceResult.fail("世界状态未初始化")
        npc = self.world.get_by_name(name)
        if npc:
            self._target_npc = npc
            self.world.touch(npc.id)
            return ResourceResult.ok(f"目标设定: {npc.name}", visible=False)
        return ResourceResult.fail(
            f"目标「{name}」不在场。若要创建新 NPC，请先调用 create_npc 工具"
            "（pack 模式需目录中存在的名称，可先调用 search_resource 查询）。"
        )

    def resolve_item(self, query: str) -> Optional[ItemDef]:
        item = item_db.find_by_name(query)
        if item:
            return item
        item = item_db.find_by_alias(query)
        if item:
            return item
        return item_db.find_best(query)

    def grant_item_not_found(self, name: str) -> ResourceResult:
        """grant_item 查表未命中：计数并返回建议（search_resource 或 create_item 回退）。"""
        self.lookup_fail_count += 1
        remain = max(0, self.resource_lookup_retries - self.lookup_fail_count)
        if remain > 0:
            return ResourceResult.fail(
                f"物品「{name}」不在库中。请换表述重试（{self.lookup_fail_count}/{self.resource_lookup_retries}）"
                f"或调用 search_resource 查询可用的物品。"
            )
        if self.allow_free_create:
            return ResourceResult.fail(
                f"物品「{name}」不在库中（已达 {self.resource_lookup_retries} 次重试上限）。"
                f"由于已开启自由创建回退，可调用 create_item 工具先定义该物品，再调用 grant_item 加入背包。"
            )
        return ResourceResult.fail(
            f"物品「{name}」不在库中（已达 {self.resource_lookup_retries} 次重试上限且未开启自由创建），"
            f"请改用库中存在的物品名或调整叙事。"
        )

    # ── 攻击检定待落账登记（检定器 → 调节器 校验落账） ──

    def record_attack_outcome(self, target: str, damage: int = 0,
                              baseline: int = 0, applied: bool = False,
                              actor: str = "") -> None:
        """登记一次攻击判定的期望落账（检定器掷骰后调用，不在此处变更任何数据）。

        target=待变更对象（玩家或 NPC 名），damage=命中伤害，baseline=态度基线，
        actor=攻击发起者（玩家名或 NPC 名），供玩家段校验「非玩家发起的伤害」
        只能在对应 NPC 行动段由系统结算。
        applied=True（本地选项路径已由系统直接落账）时标记为已落账，
        供工具层校验重复结算；applied=False（d20_roll 工具路径）时等待 LLM
        经 change_status / change_attitude 按此数值落账。
        """
        self.pending_attacks[target] = {
            "damage": max(damage, 0),
            "damage_applied": applied or damage <= 0,
            "baseline": baseline,
            "baseline_applied": applied or baseline == 0,
            "actor": actor,
        }

    def reset_pending_attacks(self) -> None:
        self.pending_attacks.clear()
        self.change_log.clear()
        self.lookup_fail_count = 0
        self.pending_changes.clear()
        self.reset_choices()

    def _bump_lookup_fail(self, hint: str) -> str:
        """查表失败计数 + 1；返回面向 LLM 的提示语（含当前次数/上限/回退状态）。"""
        self.lookup_fail_count += 1
        remain = max(0, self.resource_lookup_retries - self.lookup_fail_count)
        note = f"「{hint}」未命中本地目录（第 {self.lookup_fail_count}/{self.resource_lookup_retries} 次）。"
        if remain > 0:
            note += f" 请换一种表述重新尝试，或调用 search_resource 查询库里存在的名称。"
        elif self.allow_free_create:
            note += " 已达到重试上限且已开启自由创建回退——你可以通过 create_npc 填表创建（无需再匹配目录名称）。"
        else:
            note += " 已达到重试上限且未开启自由创建回退——请改用库中真实存在的名称，或调整叙事。"
        return note

    def _lookup_fallback_allowed(self) -> bool:
        return (self.allow_free_create
                and self.lookup_fail_count > self.resource_lookup_retries)

    def search_resource(self, query: str, kind: str = "") -> ResourceResult:
        """查询本地目录（不倾倒全表），返回 NPC/物品的简短摘要列表。"""
        q = (query or "").strip()
        if not q:
            return ResourceResult.fail("search_resource 缺少查询关键词")
        items = item_db.search(q, threshold=0.3)[:8]
        item_summary = [
            {
                "name": it.name,
                "kind": "物品",
                "type": it.type.value if hasattr(it.type, "value") else str(it.type),
                "desc": (it.damage_dice or it.effect or it.description or "")[:40],
            }
            for it, _ in items
        ]
        from world.npc_templates import npc_catalog
        npcs = npc_catalog.search(q, limit=6)
        npc_summary = [
            {
                "name": n["name"],
                "kind": "NPC",
                "type": f"{n.get('species','')} {n.get('char_class','')} Lv.{n.get('level',1)}".strip(),
                "desc": "/".join(n.get("tags", [])),
            }
            for n in npcs
        ]
        results = item_summary + npc_summary
        if kind and kind in ("npc", "item"):
            results = [r for r in results if (
                (kind == "npc" and r["kind"] == "NPC")
                or (kind == "item" and r["kind"] == "物品")
            )]
        if not results:
            return ResourceResult.fail(f"未找到与「{q}」匹配的目录条目，请换个关键词重试")
        return ResourceResult.ok(
            f"找到 {len(results)} 条匹配", {"matches": results}, visible=False,
        )

    def create_choice(self, fields: dict) -> ResourceResult:
        ct = str(fields.get("choice_type", "narrative")).strip().lower()
        if ct not in ("attack", "ability_check", "narrative"):
            ct = "narrative"
        label = str(fields.get("label", "")).strip()
        if not label:
            return ResourceResult.fail("create_choice 缺少 label（选项文本）")
        label = strip_choice_annotation(label)
        if not label:
            return ResourceResult.fail("create_choice 缺少 label（选项文本）")
        ability = str(fields.get("ability", "")).strip()
        dc = int(fields.get("dc") or 0)
        target = str(fields.get("target", "")).strip()
        skill = str(fields.get("skill", "")).strip()
        idx = self.next_choice_index
        self.next_choice_index += 1
        self.choices.append({
            "id": f"choice_{uuid4().hex[:8]}",
            "index": idx,
            "choice_type": ct,
            "label": label,
            "ability": ability,
            "dc": dc,
            "target": target,
            "skill": skill,
        })
        return ResourceResult.ok(f"选项 {idx}: {label}", data={"index": idx}, visible=False)

    def check_change_repeat(self, target: str, kind: str, value: int) -> Optional[ResourceResult]:
        """工具层段内防重复校验：同一目标同一类型同一数值的变更只允许一次。

        返回错误 ResourceResult 表示重复应拒绝（中止本次变更）；None 表示首次放行并登记。
        适用于治疗/最大HP/态度等「剧情数值」——避免 LLM 重复调用同一工具刷值。
        """
        entries = self.change_log.setdefault(str(target or ""), [])
        if (kind, value) in entries:
            return ResourceResult.fail(
                f"「{target}」的「{kind} {value:+d}」已在本轮应用过，"
                f"请勿重复调用工具结算同一变更"
            )
        entries.append((kind, value))
        return None

    def consume_pending_damage(self, target: str, hp: int) -> Optional[ResourceResult]:
        """工具层落账前校验：伤害必须先经 d20_roll 攻击检定登记，且只能落账一次。

        返回错误 ResourceResult 表示拒绝（应中止本次变更）；None 表示放行。
        """
        if hp >= 0:
            return None
        pending = self.pending_attacks.get(target)
        if not pending or not pending["damage"]:
            return ResourceResult.fail(
                f"「{target}」当前没有待结算的攻击检定，伤害不能直接扣减。"
                f"请先用 d20_roll（attack_roll）对「{target}」发起攻击检定，"
                f"再按判定结果用 change_status 落账"
            )
        expected = -pending["damage"]
        if not pending["damage_applied"]:
            if hp != expected:
                return ResourceResult.fail(
                    f"「{target}」本次攻击检定已判定造成 {pending['damage']} 点伤害，"
                    f"请用 change_status(target=\"{target}\", hp={expected}) 落账，不要传其他数值"
                )
            pending["damage_applied"] = True
            return None
        return ResourceResult.fail(f"「{target}」本次攻击伤害已落账，禁止再次结算")

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
        before = self.inv.count(guid)
        instance_ids = self.inv.add_item(guid, quantity)
        after = self.inv.count(guid)
        owner = self._owner_name()
        return ResourceResult.ok(
            f"{owner} 物品 +{quantity}x {item_def.name} ({before} >>> {after})",
            {"instance_ids": instance_ids},
        )

    def remove_item(self, guid: str, quantity: int = 1) -> ResourceResult:
        item_def = item_db.get(guid)
        name = item_def.name if item_def else guid
        bag_have = self.inv.count(guid)
        eq_slots = [slot for slot, g in self.inv.equipped.items() if g == guid]
        total_have = bag_have + len(eq_slots)
        if total_have < quantity:
            return ResourceResult.fail(f"没有足够的 {name} (需要 {quantity}, 持有 {total_have})")
        before = total_have
        removed = self.inv.remove_by_guid(guid, quantity)
        from_equip = 0
        for slot in eq_slots:
            if removed >= quantity:
                break
            self.inv.unequip(slot)
            from_equip += 1
            removed += self.inv.remove_by_guid(guid, quantity - removed)
        after = self.inv.count(guid) + sum(
            1 for slot, g in self.inv.equipped.items() if g == guid)
        owner = self._owner_name()
        msg = f"{owner} 物品 -{removed}x {name} ({before} >>> {after})"
        if from_equip:
            msg += "（从装备卸下）"
        return ResourceResult.ok(msg)

    def use_item(self, item_name: str, target: str = "玩家", quantity: int = 1) -> ResourceResult:
        """使用消耗品：掷出效果 → 应用到目标 → 从背包扣除（闭环）。

        消耗品有真实扣除成本，不经过 check_change_repeat（那是针对无成本刷值的门禁）；
        效果落账仍走统一 change_status，保证数据只经调节器变更。
        """
        from resource.models import ConsumableDef, ItemType
        quantity = int(quantity or 1)
        if quantity < 1:
            return ResourceResult.fail("quantity 必须 ≥ 1")
        item = self.resolve_item(str(item_name or "").strip())
        if not item:
            return ResourceResult.fail(f"物品「{item_name}」不在资源库中")
        if not isinstance(item, ConsumableDef) and item.type != ItemType.CONSUMABLE:
            return ResourceResult.fail(f"「{item.name}」不是消耗品，无法使用")
        bag_have = self.inv.count(item.guid)
        if bag_have < quantity:
            return ResourceResult.fail(
                f"背包中没有足够的 {item.name} (需要 {quantity}, 持有 {bag_have})"
            )
        heal_total = 0
        hp_before = hp_after = None
        actor = self._resolve_actor(target)
        if actor is not None:
            hp_before = getattr(actor, "hp", None)
        for _ in range(quantity):
            effect = item.roll_effect()
            heal = int(effect.get("heal") or 0)
            if heal:
                r = self.change_status(target, hp=heal)
                if not r.success:
                    return r
                heal_total += heal
            removed = self.inv.remove_by_guid(item.guid, 1)
            if removed != 1:
                return ResourceResult.fail(f"扣除 {item.name} 失败")
        owner = self._owner_name()
        bag_before = bag_have
        bag_after = self.inv.count(item.guid)
        if actor is not None:
            hp_after = getattr(actor, "hp", None)
        msg = f"{owner} 使用 {quantity}x {item.name}"
        if heal_total and hp_before is not None and hp_after is not None:
            msg += f" (HP {hp_before} >>> {hp_after})"
        else:
            msg += f" (背包 {bag_before} >>> {bag_after})"
        return ResourceResult.ok(msg)

    def equip(self, slot: str, guid: str) -> ResourceResult:
        item_def = item_db.get(guid)
        if not item_def:
            return ResourceResult.fail(f"物品 {guid} 不存在于物品库中")
        if not self.inv.count(guid):
            return ResourceResult.fail(f"背包中没有 {item_def.name}")
        before = self.inv.count(guid)
        success = self.inv.equip(slot, guid)
        if not success:
            return ResourceResult.fail(f"{item_def.name} 无法装备到 {slot} 槽位")
        after = self.inv.count(guid)
        owner = self._owner_name()
        return ResourceResult.ok(
            f"{owner} 装备 {item_def.name} → {slot} (背包 {before} >>> {after})")

    def unequip(self, slot: str) -> ResourceResult:
        from loc import tr
        eq = self.inv.get_equipped(slot)
        if not eq or not eq.guid:
            slot_name = tr(f"slot:{slot}")
            return ResourceResult.fail(f"{slot_name} 槽位为空")
        item_def = item_db.get(eq.guid)
        name = item_def.name if item_def else eq.guid
        before = self.inv.count(eq.guid)
        self.inv.unequip(slot)
        after = self.inv.count(eq.guid)
        owner = self._owner_name()
        return ResourceResult.ok(
            f"{owner} 装备 {name} → 背包 (背包 {before} >>> {after})")

    def add_currency(self, cp: int) -> ResourceResult:
        before = self.inv.currency.copper
        self.inv.currency.add(cp)
        after = self.inv.currency.copper
        owner = self._owner_name()
        return ResourceResult.ok(
            format_cp_change(owner, cp, before, after),
            data={"change": {
                "kind": "money", "actor": owner,
                "delta_cp": cp, "before_cp": before, "after_cp": after,
            }},
        )

    def remove_currency(self, cp: int) -> ResourceResult:
        if self.inv.currency.copper < cp:
            return ResourceResult.fail(
                f"金钱不足 (需要 {format_cp(cp)}, 持有 {self.inv.currency})")
        before = self.inv.currency.copper
        self.inv.currency.remove(cp)
        after = self.inv.currency.copper
        owner = self._owner_name()
        return ResourceResult.ok(
            format_cp_change(owner, -cp, before, after),
            data={"change": {
                "kind": "money", "actor": owner,
                "delta_cp": -cp, "before_cp": before, "after_cp": after,
            }},
        )

    def _format_cp(self, cp: int) -> str:
        return format_cp(cp)

    @staticmethod
    def _hp_change_display(amount: int) -> str:
        return f"{amount}点"

    def _owner_name(self) -> str:
        return self.character.name if self.character else "玩家"

    def add_hp(self, amount: int) -> ResourceResult:
        """玩家治疗（委托给统一落账）。"""
        return self.change_status("玩家", hp=int(amount or 0))

    def remove_hp(self, amount: int, crit: bool = False) -> ResourceResult:
        """玩家伤害（委托给统一落账）。"""
        return self.change_status("玩家", hp=-int(amount or 0), crit=crit)

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
        return ResourceResult.ok(f"{c.name} 状态 稳定 (死亡豁免 >>> 已稳定)")

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
                f"{line} 天然20：{c.name} 苏醒 (HP 0 >>> {c.hp})",
                {"outcome": "awake", "roll": roll},
            )
        if roll == 1:
            f_before = c.death_fails
            c.death_fails += 2
            msg = f"{line} 天然1：{c.name} 死亡豁免失败 2 次 (失败 {f_before}/3 >>> {c.death_fails}/3)"
            if c.death_fails >= 3:
                c.dead = True
                msg += "，第 3 次失败，死亡！"
                return ResourceResult.ok(msg, {"outcome": "dead", "roll": roll})
            return ResourceResult.ok(msg, {"outcome": "fail", "roll": roll})
        if roll >= 10:
            s_before = c.death_successes
            c.death_successes += 1
            msg = f"{line} 成功（≥10）：{c.name} 死亡豁免成功 (成功 {s_before}/3 >>> {c.death_successes}/3)"
            if c.death_successes >= 3:
                c.stable = True
                c.death_fails = 0
                c.death_successes = 0
                msg += "，第 3 次成功，转为稳定"
                return ResourceResult.ok(msg, {"outcome": "stable", "roll": roll})
            return ResourceResult.ok(msg, {"outcome": "success", "roll": roll})
        f_before = c.death_fails
        c.death_fails += 1
        msg = f"{line} 失败（<10）：{c.name} 死亡豁免失败 (失败 {f_before}/3 >>> {c.death_fails}/3)"
        if c.death_fails >= 3:
            c.dead = True
            msg += "，第 3 次失败，死亡！"
            return ResourceResult.ok(msg, {"outcome": "dead", "roll": roll})
        return ResourceResult.ok(msg, {"outcome": "fail", "roll": roll})

    def add_maxhp(self, amount: int) -> ResourceResult:
        return self.change_status("玩家", max_hp=int(amount or 0))

    def remove_maxhp(self, amount: int) -> ResourceResult:
        return self.change_status("玩家", max_hp=-int(amount or 0))

    # ── 世界/场景创建（受控，防 C8 类滥用）──

    def create_scene(self, name: str, location: str = "", description: str = "",
                     tags: list = None) -> ResourceResult:
        """LLM 创建场景：位置粒度容器。创建后成为当前场景，后续实体归入其中。

        受控性：source="llm" 标记来源、memory_weight=30 低权重（生命周期回收候选）；
        场景是结构容器，不提供任何攻击/交易能力，杜绝 C8 类「凭空造可战斗实体」。
        """
        from world.scene import Scene
        if not self.world:
            return ResourceResult.fail("世界状态未初始化")
        name = str(name or "").strip()
        if not name:
            return ResourceResult.fail("场景缺少名称")
        scene = Scene.create(
            name=name,
            location=str(location or "").strip() or name,
            description=str(description or "").strip(),
            tags=list(tags or []),
            source="llm",
            memory_weight=30,
        )
        self.world.add_scene(scene)
        self.world.current_scene_id = scene.id
        self.world.location = scene.location
        return ResourceResult.ok(f"场景已建立: {scene.name}", visible=False)

    def set_environment(self, fields: dict) -> ResourceResult:
        if not self.world:
            return ResourceResult.fail("世界状态未初始化")
        scene = self.world._ensure_scene()
        scene.environment.update({k: v for k, v in (fields or {}).items() if v})
        loc = fields.get("地点", "") or fields.get("location", "")
        time_val = fields.get("时间", "") or fields.get("time", "")
        if loc:
            scene.location = loc
            self.world.location = loc
        if time_val:
            self.world.time = time_val
        return ResourceResult.ok("环境已更新", visible=False)

    def create_object(self, name: str, description: str = "", tags: list = None) -> ResourceResult:
        """LLM 创建非角色对象（物品/道具/机关等）：加入当前场景。

        受控性：source="llm"、memory_weight=30、persistent=False（次要对象可回收）；
        只进场景不进入层池（不影响目标列表与 LLM 上下文），不可攻击/交易。
        """
        from world.object import Object
        if not self.world:
            return ResourceResult.fail("世界状态未初始化")
        name = str(name or "").strip()
        if not name:
            return ResourceResult.fail("对象缺少名称")
        obj = Object.create(
            name=name,
            description=str(description or "").strip(),
            tags=list(tags or []),
            source="llm",
            memory_weight=30,
            persistent=False,
        )
        scene = self.world._ensure_scene()
        scene.add_object(obj)
        return ResourceResult.ok(f"对象已加入场景: {obj.name}", visible=False)

    # ── NPC operations ──

    def _resolve_actor(self, target: str) -> Optional[Actor]:
        t = str(target or "").strip()
        if self.character and t in ("玩家", "player", "PC", "pc", self.character.name):
            return self.character
        if self.world:
            e = self.world.get_by_name(t)
            if isinstance(e, Actor):
                return e
        return None

    def is_player_name(self, name: str) -> bool:
        """判断名称是否指向玩家角色（用于玩家段伤害落账范围校验）。"""
        t = str(name or "").strip()
        return bool(self.character) and t in ("玩家", "player", "PC", "pc", self.character.name)

    def change_status(self, target: str, hp: int = 0, max_hp: int = 0,
                      crit: bool = False) -> ResourceResult:
        actor = self._resolve_actor(target)
        if actor is None:
            return ResourceResult.fail(f"未找到目标「{target}」")
        parts: list[str] = []
        if hp:
            if actor.dead:
                return ResourceResult.fail(f"{actor.name} 已死亡，无法变更 HP")
            before, new, notes = actor.apply_hp(hp, crit=crit)
            delta = new - before
            hp_color = "#6CB77A" if delta >= 0 else "#E08E8E"
            parts.append(
                f"{actor.name} HP [{hp_color}]{delta:+d}[/{hp_color}]"
                f" ({before}/{actor.max_hp} >>> {new}/{actor.max_hp})")
            parts.extend(notes)
        if max_hp:
            if actor.dead:
                return ResourceResult.fail(f"{actor.name} 已死亡，无法变更最大HP")
            mbefore, mnew, mnotes = actor.apply_max_hp(max_hp)
            parts.append(f"{actor.name} 最大HP {max_hp:+d} ({mbefore} >>> {mnew})")
            parts.extend(mnotes)
        return ResourceResult.ok("，".join(parts) if parts else "无变化")

    def npc_change_status(self, name: str, hp: int = 0, max_hp: int = 0) -> ResourceResult:
        return self.change_status(name, hp=hp, max_hp=max_hp)

    def change_attitude(self, name: str, delta: int = 0, reason: str = "",
                        event: str = "") -> ResourceResult:
        actor = self._resolve_actor(name)
        if actor is None:
            return ResourceResult.fail(f"未找到目标「{name}」")
        old, new = actor.apply_attitude(delta)
        applied = new - old
        reasons = getattr(actor, "attitude_reasons", None)
        if not isinstance(reasons, list):
            reasons = []
            actor.attitude_reasons = reasons
        reasons.append({
            "event": event or "manual",
            "delta": applied,
            "reason": reason,
            "source": "manager.change_attitude",
        })
        color = "#E08E8E" if applied < 0 else "#6CB77A"
        return ResourceResult.ok(
            f"{actor.name} 态度 [{color}]{applied:+d}[/{color}] ({old:+d} >>> {new:+d})")

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
        查表回退：如果启用 ALLOW_FREE_CREATE 且 lookup_fail_count 已达到上限，
        则即使在 pack 模式下也回退为 form 校验（允许凭空创建）。
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
                note = self._bump_lookup_fail(name)
                if self._lookup_fallback_allowed():
                    tmpl, errs = NPCTemplate.from_form(fields)
                    if errs:
                        return ResourceResult.fail(f"{note}（回退填表失败：{'；'.join(errs)}）")
                    tid = npc_catalog.add_runtime(
                        f"npc_runtime_{uuid4().hex[:8]}", tmpl.to_template_dict()
                    )
                    npc = npc_catalog.spawn(tid, name=name)
                else:
                    return ResourceResult.fail(note)
            else:
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
        if self.resource_mode != RESOURCE_MODE_FREE and not self._lookup_fallback_allowed():
            return "item_add 仅适用于填表创建模式"
        fields = req.get("fields") or {}
        _, errs = ItemDef.from_form(fields, guid="runtime_")
        return "；".join(errs) if errs else None

    def item_add(self, fields: dict) -> ResourceResult:
        """填表创建物品：校验 → 运行时 ItemDef。

        只定义不发放；如需进入背包，调用 grant_item 工具 + 名称引用。
        查表回退开启时，pack 模式也放行。
        """
        if self.resource_mode != RESOURCE_MODE_FREE and not self._lookup_fallback_allowed():
            return ResourceResult.fail("item_add 仅适用于填表创建模式")
        item_def, errs = ItemDef.from_form(fields, guid=f"runtime_{uuid4().hex[:8]}")
        if errs:
            return ResourceResult.fail("；".join(errs))
        item_db.add_runtime(item_def)
        return ResourceResult.ok(f"新物品定义: {item_def.name}", visible=False)
