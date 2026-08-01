"""【检定器】Checker：本地 D20 检定唯一实现（一逻辑，两入口）。

- 本地入口：base_round / npc_controller 等直接调用方法（选项带检定 → 本地结算）。
- LLM 入口：`d20_test` 工具（schemas/execute），监督者让 LLM 决定是否发起检定后，
  由 LLM 调回本机掷骰并直接判定。

术语与规则书一致（rules/playing-the-game.md「D20 Tests」）：
D20 Test 涵盖三种 kind —— ability_check（属性检定，DC）、saving_throw（豁免检定，DC）、
attack_roll（攻击检定，AC）。本模块是这些检定的单一事实源，不做数据落账以外的决策。
"""

from __future__ import annotations
import json
import random
import re
from typing import Optional

from core.character import Character, modifier, proficiency_bonus
from resource.manager import ResourceResult
from world.entity import NPC

_ABILITY_KEYS = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
_ABILITY_CN = {
    "strength": "力量", "dexterity": "敏捷", "constitution": "体质",
    "intelligence": "智力", "wisdom": "感知", "charisma": "魅力",
}
_KIND_CN = {"ability_check": "属性检定", "saving_throw": "豁免检定", "attack_roll": "攻击检定"}
_KIND_CN_SHORT = {"ability_check": "检定", "saving_throw": "豁免", "attack_roll": "攻击"}

# 目标名解析时从玩家文本中剔除的动作词（去除后余下的片段用来匹配在场 NPC 名）
_TARGET_STRIP_VERBS = (
    "狠狠", "接着", "继续", "再次", "再", "用力", "上前", "扑向", "扑上去",
    "攻击", "砍", "斩", "劈", "刺", "射", "轰", "揍", "踢", "打", "挥拳",
    "挥剑", "挥刀", "拔刀", "拔剑", "开火", "围殴", "突袭", "偷袭", "招呼",
    "对", "朝", "向", "往", "一下", "一下去", "我", "你", "他", "她", "它",
)


def _tool(name: str, description: str, parameters: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def _tool_reply(success: bool, message: str, data: dict | None = None) -> str:
    payload = {"ok": success, "message": message}
    if data:
        payload.update(data)
    return json.dumps(payload, ensure_ascii=False)


def build_action_text(
    actor: str, label: str, dc_kind: str, dc, mod_label: str, mod: int,
    line: str, word: str, color: str, target: str = "", dmg: int = 0,
) -> str:
    """统一行动块文本（唯一入口，玩家/NPC 行动共用，禁止各路径自行拼接）。

    actor=行动者名，label=检定名（如「攻击检定」「敏捷检定」），
    dc_kind=DC/AC，mod_label=调整值/加值，line=骰面算式行，
    word 为统一结果词（成功/失败/大成功/大失败），color 为其颜色。
    dmg 命中伤害单独一行、不加色。态度变化与检定说明由[变更]块 / 叙事承担，
    行动块不再重复展示。
    """
    header = f"[yellow]{actor} {label}[/yellow]"
    if target:
        header += f" 目标 [bold]{target}[/bold]"
    header += f" {dc_kind} [bold]{dc}[/bold] | {mod_label}: {mod:+d}"
    text = f"{header}\n[grey50]{line}[/grey50]"
    if word:
        text += f"\n[bold {color}]{word}[/bold {color}]"
    if dmg:
        text += f"\n造成 {dmg} 点伤害"
    return text


def _attack_display(roll: int, hit: bool) -> tuple[str, str]:
    """攻击检定结果词统一为属性检定同款：大成功/成功/失败/大失败。"""
    if roll == 20:
        return "大成功", "green"
    if roll == 1:
        return "大失败", "red"
    return ("成功", "green") if hit else ("失败", "red")


class Checker:
    """D20 检定唯一实现。构造需 character（玩家）、world（世界状态）、manager（调节器）。"""

    def __init__(self, character: Character, world, manager):
        self.character = character
        self.world = world
        self.manager = manager

    # ══════════════════════ 基础掷骰（纯函数，供各入口复用） ══════════════════════

    def resolve_check(self, roll: int, mod: int, dc: int) -> tuple[int, bool, str, str, str]:
        """D&D 5e 属性检定/豁免：d20 + 调整值 vs DC。天然20=大成功，天然1=大失败。

        返回 (total, success, 结果词, 颜色, 展示行)。
        """
        total = roll + mod
        if roll == 20:
            return total, True, "大成功", "green", f"d20(20) + ({mod:+d}) = {total}"
        if roll == 1:
            return total, False, "大失败", "red", f"d20(1) + ({mod:+d}) = {total}"
        success = total >= dc
        word = "成功" if success else "失败"
        if success:
            op = "≥" if total == dc else ">"
        else:
            op = "<"
        return total, success, word, ("green" if success else "red"), f"d20({roll}) + ({mod:+d}) = {total} {op} {dc}"

    def attack_bonus(self, char: Character) -> tuple[int, str]:
        """攻击加值：近战=力量，远程=敏捷，灵巧=取高，另加熟练加值。

        返回 (加值, 所用属性)。"""
        from resource.item_db import item_db
        prof = proficiency_bonus(char.level)
        weapon_guid = char.inventory.equipped.get("weapon")
        wdef = item_db.get(weapon_guid) if weapon_guid else None
        if wdef:
            is_finesse = any("灵巧" in p for p in wdef.properties)
            is_ranged = wdef.weapon_range == "ranged" or any("远程" in t for t in wdef.tags)
        else:
            is_finesse = False
            is_ranged = False
        if is_finesse:
            mod = max(modifier(char.strength), modifier(char.dexterity))
            ability = "力量/敏捷"
        elif is_ranged:
            mod = modifier(char.dexterity)
            ability = "敏捷"
        else:
            mod = modifier(char.strength)
            ability = "力量"
        return mod + prof, ability

    def resolve_attack(self, roll: int, char: Character, target_ac: int | None) -> tuple[int, int, bool, str, str, str]:
        """D&D 5e 攻击检定：d20 + 攻击加值 vs 目标 AC。

        天然20=暴击（自动命中），天然1=大失败（自动未命中）。
        返回 (total, 攻击加值, 是否命中, 结果词, 颜色, 展示行)。
        无目标 AC 时不作命中判定（结果词为空，交由 LLM 圆场）。
        """
        atk_bonus, _ = self.attack_bonus(char)
        total = roll + atk_bonus
        if roll == 20:
            return total, atk_bonus, True, "暴击", "yellow", f"d20(20) + ({atk_bonus:+d}) = {total}"
        if roll == 1:
            return total, atk_bonus, False, "大失败", "red", f"d20(1) + ({atk_bonus:+d}) = {total}"
        if target_ac is None:
            return total, atk_bonus, False, "", "white", f"d20({roll}) + ({atk_bonus:+d}) = {total}"
        hit = total >= target_ac
        if hit:
            op = "≥" if total == target_ac else ">"
            word, color = "命中", "green"
        else:
            op, word, color = "<", "未命中", "red"
        return total, atk_bonus, hit, word, color, f"d20({roll}) + ({atk_bonus:+d}) = {total} {op} {target_ac}"

    def find_target_ac(self) -> int | None:
        """取当前战斗目标 AC：优先世界状态中的敌对活动 NPC（存活），其次任意存活活动 NPC。"""
        from resource.attitude import level
        ws = self.world
        if not ws:
            return None
        for e in ws.active.values():
            if (isinstance(e, NPC) and level(getattr(e, "attitude", 0)) == "hostile"
                    and getattr(e, "hp", 0) > 0):
                return getattr(e, "ac", None)
        for e in ws.active.values():
            if isinstance(e, NPC) and getattr(e, "hp", 0) > 0:
                return getattr(e, "ac", None)
        return None

    # ══════════════════════ 目标名解析（放宽：部分匹配 + 候选） ══════════════════════

    def resolve_target(self, text: str, current_target: str | None = None) -> Optional[str]:
        """从文本（选项或自由输入）解析唯一被攻击/指向的在场 NPC 名。

        放宽策略（用户确认）：
        - 全名精确出现在文本 → 唯一命中即返回；
        - 否则剥除动作词后，余下片段若恰好是某在场 NPC 名的子串 → 唯一命中；
        - 否则回退到当前已设目标（manager.set_target）；
        - 多个候选或不存在 → None（交由 LLM 决定，接收侧把关）。
        """
        ws = self.world
        if not ws:
            return None
        actives = [e for e in ws.active.values() if isinstance(e, NPC) and getattr(e, "hp", 0) > 0]
        if not actives:
            return None
        text = text or ""

        exact = [e.name for e in actives if e.name and e.name in text]
        if len(exact) == 1:
            return exact[0]

        remainder = re.sub("|".join(_TARGET_STRIP_VERBS), "", text).strip("，。！？、 　,.:")
        partial = [e.name for e in actives if e.name and remainder and remainder in e.name]
        if len(partial) == 1:
            return partial[0]

        if current_target and any(e.name == current_target for e in actives):
            return current_target
        return None

    # ══════════════════════ 玩家侧检定（本地入口：base_round 选项路径） ══════════════════════

    def _player_attack_core(self, target_name: str, apply: bool = True) -> dict | None:
        """玩家攻击结算核心（本地/工具两入口共用，一逻辑两入口）。

        掷骰 → 命中判定 → 计算目标态度基线（未敌对时 -8）与武器伤害。

        apply=True（本地选项路径）：由系统直接经 manager 落账伤害与态度基线；
        apply=False（d20_test 工具路径）：只掷骰判定并登记 pending_attacks，
        由 LLM 再经调节器工具 change_status / change_attitude 落账（调节器校验数值）。

        返回 {tgt, ac, roll, total, atk_bonus, hit, word, color, line, dmg,
        attitude_applied, attitude_delta, baseline, changes}；无法结算时返回 None。
        changes 为本地路径已落账的变更消息（工具路径为空）。
        """
        world, manager = self.world, self.manager
        if not world or not manager:
            return None
        char = self.character
        tgt = world.get_by_name(target_name)
        if tgt is None or not isinstance(tgt, NPC) or getattr(tgt, "ac", None) is None:
            return None

        ac = tgt.ac
        roll = random.randint(1, 20)
        total, atk_bonus, hit, word, color, line = self.resolve_attack(roll, char, ac)

        from resource.attitude import EVENT_TABLE, level
        attitude_delta = EVENT_TABLE["attack"]["delta"]
        baseline = attitude_delta if level(getattr(tgt, "attitude", 0)) != "hostile" else 0

        dmg = 0
        if hit:
            dmg = self.roll_player_damage(char, crit=(roll == 20))

        changes: list[str] = []
        if apply:
            attitude_applied = False
            if baseline:
                att_res = manager.change_attitude(
                    tgt.name, delta=baseline,
                    event="attack",
                    reason=EVENT_TABLE["attack"]["desc"] + "（玩家攻击，系统基线）",
                )
                if att_res.success:
                    attitude_applied = True
                    if att_res.message:
                        changes.append(att_res.message)
            if hit and dmg:
                hp_res = manager.npc_change_status(tgt.name, hp=-dmg)
                if hp_res.success and hp_res.message:
                    changes.append(hp_res.message)
            manager.record_attack_outcome(tgt.name, damage=dmg, baseline=baseline, applied=True)
        else:
            manager.record_attack_outcome(tgt.name, damage=dmg, baseline=baseline, applied=False)
            attitude_applied = False

        return {
            "tgt": tgt, "ac": ac, "roll": roll, "total": total,
            "atk_bonus": atk_bonus, "hit": hit, "word": word,
            "color": color, "line": line, "dmg": dmg,
            "attitude_applied": attitude_applied,
            "attitude_delta": attitude_delta,
            "baseline": baseline,
            "changes": changes,
        }

    def settle_player_attack(self, target_name: str, label: str = ""):
        """机械结算一次玩家攻击（非战斗/战斗统一路径，D5：机械数值系统算）。

        掷骰 → 命中 → 武器伤害经 manager 落账；目标若尚未敌对，按 EVENT_TABLE['attack'](-8)
        基线落账态度（仅一次/目标）。

        返回 (check_text, 注入玩家输入的「系统已结算」标注)；无法结算时返回 None。
        """
        r = self._player_attack_core(target_name)
        if r is None:
            return None
        char = self.character
        tgt = r["tgt"]
        ac, roll, atk_bonus, total, hit = (
            r["ac"], r["roll"], r["atk_bonus"], r["total"], r["hit"],
        )
        raw_word, line, dmg = r["word"], r["line"], r["dmg"]
        attitude_applied, attitude_delta = r["attitude_applied"], r["attitude_delta"]

        word, color = _attack_display(roll, hit)
        check_text = build_action_text(
            char.name, "攻击检定", "AC", ac, "加值", atk_bonus,
            line, word, color, target=tgt.name, dmg=dmg,
        )
        fragment = f"[攻击] d20({roll})+({atk_bonus:+d})={total}"
        parts = [f"对「{tgt.name}」发起攻击"]
        if hit:
            fragment += f" 命中 造成{dmg}伤害"
            parts.append(f"命中，造成 {dmg} 点伤害")
        else:
            if raw_word:
                fragment += f" {raw_word}"
            parts.append(raw_word or "未命中")
        if attitude_applied:
            parts.append(f"{tgt.name} 态度 {attitude_delta:+d}")
        note = "，".join(parts)
        label_part = f"{label} | " if label else ""
        return check_text, (
            f"{label_part}{fragment} | 系统已结算：{note}"
            "（伤害/态度已由系统落账，你只需叙事）"
        )

    def roll_player_damage(self, char: Character, crit: bool = False) -> int:
        """玩家武器伤害掷骰（武器骰 + 力量调整值；暴击翻倍骰），最低 1 点。"""
        dice = self.player_weapon_dice(char)
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
        total = sum(rolls) + extra + max(modifier(char.strength), 0)
        return max(total, 1)

    def player_weapon_dice(self, char: Character) -> str:
        from resource.item_db import item_db
        weapon_guid = char.inventory.equipped.get("weapon")
        wdef = item_db.get(weapon_guid) if weapon_guid else None
        return (wdef.damage_dice if wdef and wdef.damage_dice else "1d4")

    def npc_weapon_dice(self, npc: NPC) -> str:
        return (self._npc_weapon(npc).damage_dice or "1d1")

    def roll_npc_damage(self, npc: NPC, crit: bool = False) -> int:
        """NPC 武器伤害掷骰（武器骰 + 力量调整值；暴击翻倍骰），最低 1 点。"""
        dice = self.npc_weapon_dice(npc)
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

    def medicine_self_check(self, raw: str) -> tuple[str, str] | None:
        """玩家昏迷时的医药自救检定（T17）：DC10 感知·医药。

        命中关键词（医药/自救/止血/医疗/急救/稳定）→ 系统掷 d20+感知；
        成功 → 未稳定则转为稳定，已稳定则恢复 1 HP 苏醒。返回 (check_text, transformed)。
        非昏迷/无关键词 → None。
        """
        character = self.character
        if character.dead or not character.unconscious:
            return None
        if not any(kw in (raw or "") for kw in _MEDICINE_KEYWORDS):
            return None
        mod = modifier(character.wisdom)
        roll = random.randint(1, 20)
        total, success, word, color, line = self.resolve_check(roll, mod, 10)
        check_text = build_action_text(
            character.name, "医药自救检定", "DC", 10, "调整值", mod,
            line, word, color,
        )
        if success:
            if character.stable:
                self.manager.add_hp(1)
                check_text += f"\n[grey50]成功：恢复 1 点生命，{character.name} 苏醒[/grey50]"
            else:
                self.manager.set_stable()
                check_text += f"\n[grey50]成功：转为稳定（停止死亡豁免，仍昏迷）[/grey50]"
            transformed = f"{raw} | [医药自救] d20({roll})+({mod:+d})={total} 成功"
        else:
            transformed = f"{raw} | [医药自救] d20({roll})+({mod:+d})={total} 失败"
        return check_text, transformed

    def interactive_check(self, char: Character, ability_cn: str, ability_key: str, dc: int) -> tuple[int, int, int, bool]:
        from core.ui import console
        ability_mod = modifier(getattr(char, ability_key))
        roll = random.randint(1, 20)
        total, success, word, color, line = self.resolve_check(roll, ability_mod, dc)
        console.print()
        console.print(build_action_text(
            char.name, f"{ability_cn}检定", "DC", dc, "调整值", ability_mod,
            line, word, color,
        ))
        console.print()
        return roll, ability_mod, total, success

    def roll_expression(self, expr: str) -> tuple[int, str]:
        def roll_dice(m):
            count = int(m.group(1)) if m.group(1) else 1
            sides = int(m.group(2))
            mod = int(m.group(3)) if m.group(3) else 0
            if count < 1:
                count = 1
            results = [random.randint(1, sides) for _ in range(count)]
            total = sum(results) + mod
            return str(total)

        expr_parsed = re.sub(r"(\d+)?d(\d+)(?:\s*\+\s*(\d+))?", roll_dice, expr)
        try:
            total = eval(expr_parsed)
        except:
            return 0, f"[grey50]无效骰子表达式: {expr}[/grey50]"
        return total, f"[grey50]{expr} = {total}[/grey50]"

    # ══════════════════════ LLM 工具入口（d20_test：玩家 + NPC 通用） ══════════════════════

    def tool_schema(self) -> dict:
        return _tool(
            "d20_test",
            "为玩家或目标NPC执行本地 D20 检定（ability_check=属性检定 / saving_throw=豁免检定 / "
            "attack_roll=攻击检定），骰子由系统在本机掷出并直接判定。"
            "ability_check 与 saving_throw 对给定 DC 判定；attack_roll 对目标 AC 判定。"
            "收到返回的判定结果后，在[副事件]区块中描述结果。",
            {
                "type": "object",
                "properties": {
                    "actor": {"type": "string",
                              "description": "检定发起者：玩家 或 目标NPC名称"},
                    "kind": {"type": "string", "enum": ["ability_check", "saving_throw", "attack_roll"],
                             "description": "ability_check=属性检定；saving_throw=豁免检定；attack_roll=攻击检定"},
                    "ability": {"type": "string", "enum": _ABILITY_KEYS,
                                "description": "所用属性（ability_check/saving_throw 必填；attack_roll 缺省取力量/敏捷较高者）"},
                    "dc": {"type": "integer", "minimum": 1,
                           "description": "ability_check/saving_throw 的目标DC"},
                    "target": {"type": "string",
                               "description": "攻击目标：NPC名称（玩家攻击NPC）或「玩家」（NPC攻击玩家）"},
                    "note": {"type": "string",
                             "description": "检定说明（如：对玩家发动攻击、躲避落石）"},
                },
                "required": ["actor", "kind"],
            },
        )

    def execute(self, name: str, arguments: dict) -> str:
        if name != "d20_test":
            return _tool_reply(False, f"未知工具: {name}")
        try:
            result = self._d20_test(arguments)
        except Exception as e:
            return _tool_reply(False, f"工具执行异常: {e}")
        return _tool_reply(result.success, result.message, result.data)

    def _d20_test(self, arguments: dict) -> ResourceResult:
        """d20_test 工具实现：玩家/NPC 检定统一路径（D20 Test 三种 kind）。"""
        actor = str(arguments.get("actor", "")).strip()
        kind = str(arguments.get("kind", "ability_check")).strip().lower()
        ability = str(arguments.get("ability", "")).strip().lower()
        note = str(arguments.get("note", "")).strip()
        dc = arguments.get("dc")
        target = str(arguments.get("target", "")).strip()

        if kind not in _KIND_CN:
            kind = "ability_check"
        if not actor:
            return ResourceResult.fail("d20_test 缺少 actor（玩家 或 NPC名称）")

        is_player = actor in ("玩家", "player", "PC", "你") or actor == self.character.name

        if kind == "attack_roll":
            return self._attack_test(is_player, actor, target, note)

        # ability_check / saving_throw
        if ability not in _ABILITY_KEYS:
            ability = "dexterity"
        try:
            dc_value = int(dc) if dc else 10
        except (TypeError, ValueError):
            dc_value = 10
        if is_player:
            npc_or_char = self.character
            name = self.character.name
        else:
            npc = self._get_npc(actor)
            if npc is None:
                return ResourceResult.fail(f"未找到目标 NPC「{actor}」")
            npc_or_char = npc
            name = npc.name

        ab_mod = modifier(getattr(npc_or_char, ability))
        prof = getattr(npc_or_char, "proficiency_bonus", 0) or 0
        has_prof = (
            kind == "saving_throw"
            and isinstance(npc_or_char, NPC)
            and ability in (npc_or_char.saving_throws or [])
        )
        mod = ab_mod + prof if has_prof else ab_mod

        roll = random.randint(1, 20)
        total, success, word, color, line = self.resolve_check(roll, mod, dc_value)
        label = _KIND_CN[kind]
        kind_cn = _KIND_CN_SHORT[kind]
        ability_cn = _ABILITY_CN.get(ability, ability)
        text = build_action_text(
            name, f"{ability_cn}检定", "DC", dc_value, "调整值", mod,
            line, word, color,
        )
        data = {
            "ok": True, "actor": name, "kind": kind, "kind_cn": label,
            "ability": ability, "ability_cn": ability_cn,
            "dc": dc_value, "dc_kind": "DC",
            "roll": roll, "modifier": mod, "total": total,
            "success": success, "natural_20": roll == 20, "natural_1": roll == 1,
            "note": note, "display": text,
        }
        return ResourceResult(True, "", {"test": data}, visible=False)

    def _attack_test(self, is_player: bool, actor: str, target: str, note: str) -> ResourceResult:
        """攻击检定（检定器：只掷骰判定，不做任何数据落账）。

        判定结果（命中伤害、态度基线）登记到 manager.pending_attacks，
        由 LLM 经调节器工具 change_status / change_attitude 落账（调节器校验数值，
        拒绝随意数值与重复结算）。消息仅作落账指引，非「禁止」提示词。
        """
        if is_player:
            name = self.character.name
            tgt_name = target or self.resolve_target("", current_target=None)
            tgt = self._get_npc(tgt_name) if tgt_name else None
            if tgt is None:
                return ResourceResult.fail(
                    "未找到被攻击的 NPC 目标（请确认 target 名称与在场 NPC 一致，或先调用 set_target）"
                )
            r = self._player_attack_core(tgt.name, apply=False)
            if r is None:
                return ResourceResult.fail(f"目标「{tgt.name}」的 AC 不可用")
            ac, roll, atk_bonus, total, hit = (
                r["ac"], r["roll"], r["atk_bonus"], r["total"], r["hit"],
            )
            line, dmg = r["line"], r["dmg"]
            baseline = r["baseline"]
            target_label = tgt.name
        else:
            npc = self._get_npc(actor)
            if npc is None:
                return ResourceResult.fail(f"未找到目标 NPC「{actor}」")
            name = npc.name
            if target in ("玩家", "player", "PC", "你") or target == self.character.name:
                ac = self.character.ac if not getattr(self.character, "dead", False) else None
                target_label = "玩家"
            else:
                tgt = self._get_npc(target)
                ac = getattr(tgt, "ac", None) if tgt else None
                target_label = target
            if ac is None:
                return ResourceResult.fail(f"攻击目标「{target_label}」的 AC 不可用")
            bonus = self._npc_attack_bonus(npc)
            roll = random.randint(1, 20)
            total = roll + bonus
            hit = roll == 20 or (roll != 1 and total >= ac)
            atk_bonus = bonus
            op = "≥" if total == ac else (">" if hit else "<")
            line = f"d20({roll}) + ({bonus:+d}) = {total} {op} {ac}"
            dmg = 0
            baseline = 0
            if hit:
                dmg = self.roll_npc_damage(npc, crit=(roll == 20))
            self.manager.record_attack_outcome(target_label, damage=dmg, baseline=0, applied=False)

        word, color = _attack_display(roll, hit)
        text = build_action_text(
            name, "攻击检定", "AC", ac, "加值", atk_bonus,
            line, word, color, target=target_label, dmg=dmg,
        )
        data = {
            "ok": True, "actor": name, "kind": "attack_roll", "kind_cn": "攻击检定",
            "ability": "", "ability_cn": "",
            "dc": ac, "dc_kind": "AC",
            "roll": roll, "modifier": atk_bonus, "total": total,
            "success": hit, "natural_20": roll == 20, "natural_1": roll == 1,
            "damage": dmg, "attitude_delta": baseline,
            "note": note, "display": text, "changes": [],
        }
        hint = f"对「{target_label}」造成 {dmg} 点伤害" if hit else f"未命中「{target_label}」，不产生伤害"
        baseline_hint = (
            f"目标「{target_label}」尚未敌对，态度基线需落账 {baseline:+d}（请调用 change_attitude）。"
            if baseline else ""
        )
        message = (
            f"攻击检定结果：{'命中' if hit else '未命中'}。{hint}。{baseline_hint}"
            "请调用 change_status 落账伤害，再在[副事件]中叙事。"
        )
        return ResourceResult(True, message, {"test": data}, visible=False)

    # ══════════════════════ 辅助 ══════════════════════

    def _get_npc(self, name: str) -> Optional[NPC]:
        if not self.world or not name:
            return None
        return self.world.get_by_name(name)

    def _npc_attack_bonus(self, npc: NPC) -> int:
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
        from resource.item_db import item_db
        from resource.models import ItemType
        for guid in getattr(npc, "inventory", None) or []:
            wdef = item_db.get(guid)
            if wdef and wdef.type == ItemType.WEAPON and wdef.damage_dice:
                return wdef
        return _UNARMED


_MEDICINE_KEYWORDS = ("医药", "自救", "止血", "医疗", "急救", "稳定")


class _Unarmed:
    name = "徒手"
    damage_dice = "1d1"
    properties: list = []
    tags: list = []
    weapon_range = ""


_UNARMED = _Unarmed()
