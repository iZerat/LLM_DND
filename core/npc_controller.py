from __future__ import annotations
import random
import re
from typing import Optional

from core.character import modifier
from world.entity import NPC
from resource.item_db import item_db
from resource.models import ItemType
from resource.attitude import level_cn

_ATTACK_HINTS = ("攻击", "冲锋", "斩", "劈", "刺", "射", "轰", "扑", "锤", "咬", "挥")


class NPCController:
    """NPC 行动子工具：以每个在场 NPC 的独立子请求决定其本轮行动，并机械结算。

    设计（用户确认）：
    - 每个在场 NPC 一个独立 LLM 子请求，以该 NPC 身份决定本轮唯一行动；
    - 先攻排序由 Initiative（core/rounds/initiative.py）统一维护，本控制器不再重复掷；
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
        self.check_results: list[dict] = []

    # ── 子工具入口：单个 NPC 本轮行动 ──

    def act(self, npc: NPC, player_input: str) -> tuple[str, str, str]:
        """结算单个 NPC 本轮行动。

        返回 (check_text, injected, change_msg)：
        - check_text：行动块的骰面/结果文本（非攻击行动为空串）
        - injected：注入主 DM 短调用的叙事行（空串=该 NPC 本轮无需行动/已倒下）
        - change_msg：变更块的落账消息（空串=无 HP 变更）
        """
        if not npc or getattr(npc, "dead", False) or getattr(npc, "hp", 1) <= 0:
            self.log_lines.append(f"{npc.name} 已倒下/死亡，跳过行动")
            return "", "", ""
        decision = self._ask_npc(npc, player_input)
        line, injected, check_text, change_msg = self._resolve(npc, decision)
        self.log_lines.append(line)
        return check_text, injected, change_msg

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
            char.name, char.ac, char.hp, char.max_hp,
            pc_dead=getattr(char, "dead", False),
        ) or ""
        weapon = self._npc_weapon(npc)
        weapon_desc = f"{weapon.name}（{weapon.damage_dice}）" if weapon.damage_dice else weapon.name
        attitude = level_cn(npc.attitude)
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
            f"注意：HP 0 的目标已倒地昏迷，已死亡的目标无法被攻击。\n"
            f"只输出两行，不要解释：\n"
            f"行动: <攻击/移动/对话/协助/观望/撤退/躲藏>\n"
            f"目标: <玩家 或 在场角色名，仅当行动为攻击时填写>\n"
        )

    # ── 机械结算 ──

    def _resolve(self, npc: NPC, decision: str) -> tuple[str, str, str, str]:
        """机械结算 NPC 决策。

        返回 (log 行, 注入主 DM 的叙事行, 行动块骰面文本, 变更块落账消息)。
        攻击命中并造成伤害时直接落账。
        """
        text = (decision or "").strip()
        action_m = re.search(r"行动\s*[:：]\s*([^\n]+)", text)
        target_m = re.search(r"目标\s*[:：]\s*([^\n]+)", text)
        action = (action_m.group(1).strip() if action_m else "").strip()
        target = (target_m.group(1).strip() if target_m else "").strip()

        is_attack = bool(action) and any(h in action for h in _ATTACK_HINTS)
        tag = level_cn(npc.attitude)
        if not is_attack:
            if not action:
                action = "观望"
            return (
                f"{npc.name} 选择：{action}",
                f"[{tag}] {npc.name}：本轮{action}。",
                "",
                "",
            )

        target_ac, is_player = self._target_ac(target)
        if target_ac is None:
            return (
                f"{npc.name} 攻击目标「{target or '未知'}」：目标不存在，落空",
                f"[{tag}] {npc.name}：试图攻击「{target or '未知'}」，但目标不在场。",
                "",
                "",
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
        target_label = "玩家" if is_player else target
        if total == target_ac:
            op = "≥"
        elif hit:
            op = ">"
        else:
            op = "<"
        color = "yellow" if roll == 20 else ("red" if not hit else "green")
        check_text = (
            f"[yellow]{npc.name} 攻击检定[/yellow] 目标 [bold]{target_label}[/bold] "
            f"AC [bold]{target_ac}[/bold] | 加值: {bonus:+d}\n"
            f"[grey50]d20({roll}) + ({bonus:+d}) = {total} {op} {target_ac}[/grey50]"
        )
        self.check_results.append({
            "target": npc.name,
            "text": check_text,
            "success": hit,
        })

        if not hit:
            check_text += f"\n[bold {color}]{word}[/bold {color}]"
            self.check_results[-1]["text"] = check_text
            return (
                f"{npc.name} 攻击{target_label}："
                f"d20({roll})+({bonus:+d})={total} < {target_ac}，未命中",
                f"[{tag}] {npc.name}：对{'你' if is_player else target}发起攻击，但攻击落空了。",
                check_text,
                "",
            )

        weapon = self._npc_weapon(npc)
        dmg = self._roll_damage(weapon.damage_dice, npc, crit=(roll == 20))
        check_text += f"\n[bold {color}]命中，造成 {dmg} 点伤害[/bold {color}]"
        self.check_results[-1]["text"] = check_text
        if is_player:
            res = self.manager.remove_hp(dmg, crit=(roll == 20))
            self.changed_names.add(self.character.name)
            line = (f"{npc.name} 攻击玩家：d20({roll})+({bonus:+d})={total} ≥ {target_ac}，"
                    f"命中，造成 {dmg} 点伤害")
            injected = f"[{tag}] {npc.name}：攻击你，命中，造成 {dmg} 点伤害。"
            change_msg = res.message if res and res.message else f"{self.character.name} HP {dmg:-d}"
        else:
            tgt = self.world.get_by_name(target)
            if tgt is None:
                return (
                    f"{npc.name} 攻击目标「{target}」：目标不在场，落空",
                    f"[{tag}] {npc.name}：试图攻击「{target}」，但对方已不在场上。",
                    "",
                    "",
                )
            self.manager.npc_change_status(tgt.name, hp=-dmg)
            self.changed_names.add(tgt.name)
            line = (f"{npc.name} 攻击 {tgt.name}：d20({roll})+({bonus:+d})={total} ≥ {target_ac}，"
                    f"命中，造成 {dmg} 点伤害")
            injected = f"[{tag}] {npc.name}：攻击 {tgt.name}，命中，造成 {dmg} 点伤害。"
            change_msg = f"{tgt.name} HP {dmg:-d}"
        return line, injected, self.check_results[-1]["text"], change_msg

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
            if getattr(self.character, "dead", False):
                return None, False
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
