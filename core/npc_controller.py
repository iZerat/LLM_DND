from __future__ import annotations
import random
import re
from typing import Optional

from core.character import modifier
from world.entity import NPC
from resource.item_db import item_db
from resource.models import ItemType

_ATTITUDE_CN = {"hostile": "敌对", "friendly": "友方", "neutral": "中立"}
_ATTACK_HINTS = ("攻击", "冲锋", "斩", "劈", "刺", "射", "轰", "扑", "锤", "咬", "挥")


class NPCController:
    """NPC 行动控制器：每轮让在场 NPC 按先攻顺序独立行动。

    设计（用户确认）：
    - 每个在场 NPC 一个独立 LLM 子请求，以该 NPC 身份决定本轮唯一行动；
    - 严格按 D&D 先攻（敏捷检定 d20+敏捷调整值，从高到低）依次串行处理，绝不并发；
    - 时序：玩家行动机械结算之后、主 DM 叙事整合之前；
    - 攻击类行动由系统机械结算（骰子+落账），主 DM 只把已结算结果编织进叙事，
      不再重复扣血；非攻击行动仅产生叙事意图。
    """

    def __init__(self, gm, regulator):
        self.gm = gm
        self.character = gm.character
        self.manager = regulator.manager
        self.world = regulator.world
        self.log_lines: list[str] = []
        self.changed_names: set[str] = set()

    # ── 主入口 ──

    def run(self, player_input: str) -> str:
        """结算在场 NPC 本轮行动，返回注入给主 DM 的上下文片段（空串=无 NPC 行动）。"""
        self.log_lines = []
        self.changed_names = set()
        if not self.world:
            return ""
        order = self._initiative_order()
        if not order:
            return ""
        parts: list[str] = []
        for npc in order:
            if getattr(npc, "hp", 1) <= 0:
                self.log_lines.append(f"{npc.name} 已倒下，跳过行动")
                continue
            decision = self._ask_npc(npc, player_input)
            line, injected = self._resolve(npc, decision)
            self.log_lines.append(line)
            if injected:
                parts.append(injected)
        if not parts:
            return ""
        return (
            "[系统·NPC行动]（本轮在场 NPC 已由系统按先攻顺序依次行动并机械结算，"
            "伤害已直接落账，请勿再通过 [状态变更] 重复扣减这些目标的 HP）：\n"
            + "\n".join(parts)
            + "\n请把上述行动自然编织进 [事件] 叙事；[状态] 区块请如实写出这些目标的当前 HP。"
        )

    # ── 先攻顺序 ──

    def _initiative_order(self) -> list[NPC]:
        """按 D&D 先攻排序：d20 + 敏捷调整值，从高到低；同名同类共享一次掷骰。"""
        active = [e for e in self.world.active.values() if isinstance(e, NPC)]
        if not active:
            return []
        roll_cache: dict[str, int] = {}

        def init_key(npc: NPC):
            if npc.name not in roll_cache:
                roll_cache[npc.name] = random.randint(1, 20)
            return roll_cache[npc.name] + modifier(npc.dexterity)

        ordered = sorted(
            active,
            key=lambda n: (init_key(n), modifier(n.dexterity)),
            reverse=True,
        )
        return ordered

    # ── 子请求：以 NPC 身份决策 ──

    def _ask_npc(self, npc: NPC, player_input: str) -> str:
        prompt = self._build_npc_prompt(npc, player_input)
        return self.gm.complete(
            [{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7,
        )

    def _build_npc_prompt(self, npc: NPC, player_input: str) -> str:
        char = self.character
        context = self.world.render_context_for_llm(
            char.name, char.ac, char.hp, char.max_hp
        ) or ""
        weapon = self._npc_weapon(npc)
        weapon_desc = f"{weapon.name}（{weapon.damage_dice}）" if weapon.damage_dice else weapon.name
        attitude = _ATTITUDE_CN.get(npc.attitude, "中立")
        return (
            f"你是「{npc.name}」，一个{attitude}角色。你正在一场 D&D 战斗中，"
            f"必须独立思考并行动。\n\n"
            f"你的档案：种族={npc.species or '人类'}，职业={npc.char_class or '平民'}，"
            f"等级={npc.level}。HP：{npc.hp}/{npc.max_hp}，AC：{npc.ac}。"
            f"力量={npc.strength} 敏捷={npc.dexterity} 体质={npc.constitution} "
            f"智力={npc.intelligence} 感知={npc.wisdom} 魅力={npc.charisma}。\n"
            f"武器：{weapon_desc}。\n"
            f"背景：{npc.description or '无'}\n\n"
            f"[当前局面]\n{player_input.strip()}\n\n{context}\n\n"
            f"请以「{npc.name}」的视角决定本轮唯一的行动。"
            f"若当前并无威胁或不在战斗中，倾向选择对话/观望/移动/协助，而非攻击。\n"
            f"只输出两行，不要解释：\n"
            f"行动: <攻击/移动/对话/协助/观望/撤退/躲藏>\n"
            f"目标: <玩家 或 在场角色名，仅当行动为攻击时填写>\n"
        )

    # ── 机械结算 ──

    def _resolve(self, npc: NPC, decision: str) -> tuple[str, str]:
        """机械结算 NPC 决策。

        返回 (log 行, 注入主 DM 的叙事行)。攻击命中并造成伤害时直接落账。
        """
        text = (decision or "").strip()
        action_m = re.search(r"行动\s*[:：]\s*([^\n]+)", text)
        target_m = re.search(r"目标\s*[:：]\s*([^\n]+)", text)
        action = (action_m.group(1).strip() if action_m else "").strip()
        target = (target_m.group(1).strip() if target_m else "").strip()

        is_attack = bool(action) and any(h in action for h in _ATTACK_HINTS)
        if not is_attack:
            if not action:
                action = "观望"
            return (
                f"{npc.name} 选择：{action}",
                f"{npc.name} 本轮{action}。",
            )

        target_ac, is_player = self._target_ac(target)
        if target_ac is None:
            return (
                f"{npc.name} 攻击目标「{target or '未知'}」：目标不存在，落空",
                f"{npc.name} 试图攻击「{target or '未知'}」，但目标不在场。",
            )

        roll = random.randint(1, 20)
        bonus = self._attack_bonus(npc)
        total = roll + bonus
        if roll == 20:
            hit, word = True, "暴击"
        elif roll == 1:
            hit, word = False, "严重失误"
        else:
            hit, word = total >= target_ac, ("命中" if total >= target_ac else "未命中")

        if not hit:
            return (
                f"{npc.name} 攻击{'玩家' if is_player else target}："
                f"d20({roll})+({bonus:+d})={total} < {target_ac}，未命中",
                f"{npc.name} 对{'你' if is_player else target}发起攻击，但攻击落空了。",
            )

        weapon = self._npc_weapon(npc)
        dmg = self._roll_damage(weapon.damage_dice, npc, crit=(roll == 20))
        if is_player:
            res = self.manager.remove_hp(dmg)
            self.changed_names.add(self.character.name)
            line = (f"{npc.name} 攻击玩家：d20({roll})+({bonus:+d})={total} ≥ {target_ac}，"
                    f"命中，造成 {dmg} 点伤害")
            injected = f"{npc.name} 对你发动攻击，命中，造成 {dmg} 点伤害。"
        else:
            tgt = self.world.get_by_name(target)
            if tgt is None:
                return (
                    f"{npc.name} 攻击目标「{target}」：目标不在场，落空",
                    f"{npc.name} 试图攻击「{target}」，但对方已不在场上。",
                )
            tgt.hp = max(tgt.hp - dmg, 0)
            self.changed_names.add(tgt.name)
            line = (f"{npc.name} 攻击 {tgt.name}：d20({roll})+({bonus:+d})={total} ≥ {target_ac}，"
                    f"命中，造成 {dmg} 点伤害")
            injected = f"{npc.name} 攻击 {tgt.name}，命中，造成 {dmg} 点伤害。"
        return line, injected

    # ── 数值辅助 ──

    def _attack_bonus(self, npc: NPC) -> int:
        prof = getattr(npc, "proficiency_bonus", 2) or 2
        weapon = self._npc_weapon(npc)
        finesse = any("灵巧" in p for p in weapon.properties)
        ranged = weapon.weapon_range == "ranged" or any("远程" in t for t in weapon.tags)
        if finesse:
            mod = max(modifier(npc.strength), modifier(npc.dexterity))
        elif ranged:
            mod = modifier(npc.dexterity)
        else:
            mod = modifier(npc.strength)
        return prof + mod

    def _npc_weapon(self, npc: NPC):
        """取 NPC 背包中第一把武器；无则退回徒手。"""
        for guid in getattr(npc, "inventory", None) or []:
            wdef = item_db.get(guid)
            if wdef and wdef.type == ItemType.WEAPON and wdef.damage_dice:
                return wdef
        return _UNARMED

    def _target_ac(self, target: str):
        if not target:
            return None, False
        if target in ("玩家", "player", "PC", "你") or target == self.character.name:
            return self.character.ac, True
        tgt = self.world.get_by_name(target)
        if tgt is None:
            return None, False
        return getattr(tgt, "ac", 10), False

    def _roll_damage(self, dice: str, npc: NPC, crit: bool = False) -> int:
        m = re.match(r"(\d+)d(\d+)(?:\s*\+\s*(\d+))?", dice or "")
        count = int(m.group(1)) if m else 1
        sides = int(m.group(2)) if m else 1
        extra = int(m.group(3)) if m and m.group(3) else 0
        if count < 1:
            count = 1
        if sides < 1:
            sides = 1
        rolls = [random.randint(1, sides) for _ in range(count)]
        if crit:
            rolls += [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls) + extra + max(modifier(npc.strength), 0)
        return max(total, 1)


class _Unarmed:
    name = "徒手"
    damage_dice = "1d1"
    properties: list = []
    tags: list = []
    weapon_range = ""


_UNARMED = _Unarmed()
