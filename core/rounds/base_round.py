from __future__ import annotations
import re
import random as dice_random
import time as _time
from dataclasses import dataclass

from core.character import modifier
from core.game_master import parse_check_from_text
from core.game_loop import (
    log_dm_response, format_elapsed, _resolve_check, _resolve_attack, _find_target_ac,
)
from core.ui import console, render_decision_block


@dataclass
class RoundContext:
    """一个回合所需的共享状态：由 GameRound 创建，所有段共用同一轮号。"""
    gm: object
    regulator: object
    supervisor: object
    toolbox: object
    npc_controller: object
    initiative: object
    round_num: int = 1


class RoundResult:
    """回合结束返回给 GameRound 的控制结果。action: continue / quit / menu / load"""

    def __init__(self, action="continue", gm=None, player_input=""):
        self.action = action
        self.gm = gm
        self.player_input = player_input or ""


class PromptResult:
    """玩家输入结果。action 非 continue 表示命令分流（quit/menu/load）。"""

    def __init__(self, action="continue", gm=None, player_input="", from_command=False):
        self.action = action
        self.gm = gm
        self.player_input = player_input or ""
        self.from_command = from_command


# ── 玩家输入解析（供回合与读档预置共用）──

def update_choices_map(gm, choice_text: str):
    """从 [选择] 区块文本重建 gm.last_choices_map（选项编号 → 整行文本）。"""
    mapping = {}
    for line in (choice_text or "").strip().split("\n"):
        line = line.strip()
        m = re.match(r"^(\d+)[.)]\s*(.+)", line)
        if m:
            mapping[m.group(1)] = line
    gm.last_choices_map = mapping


def record_to_display(record: str, is_option: bool) -> str:
    """决定块展示文本：选项行着色 + 剥掉无需检定标注。"""
    if is_option:
        record = re.sub(
            r'[（(]\s*无需[^）)]*[）)]', '', record,
        ).strip()
        record = re.sub(
            r'([（(][^）)]*(?:(?:力量|敏捷|体质|智力|感知|魅力)|检定|击骰)[^）)]*[）)])',
            r'[#5DCCCC]\1[/#5DCCCC]',
            record,
        )
        m = re.match(r"^(\d+[.)])\s*(.*)", record)
        if m:
            return f"[white]{m.group(1)}[/white] [#F9F1A5]{m.group(2)}[/#F9F1A5]"
        return f"[#F9F1A5]{record}[/#F9F1A5]"
    return record


def resolve_player_input(gm, character, raw: str, from_command: bool = False):
    """解析玩家输入。

    选项编号 → 映射选项文本 + 本地检定（交互骰：属性/攻击）；自由文本 → 原样传递。
    返回 (发送给 DM 的输入, 决定块文本, 检定文本)。
    """
    raw = raw.strip()
    if from_command or not raw:
        return raw, record_to_display(raw, False), ""

    is_option = raw in gm.last_choices_map
    record = gm.last_choices_map[raw] if is_option else raw
    check_text = ""
    transformed = raw

    if raw.isdigit():
        selected_num = raw
        option_text = gm.last_choices_map.get(selected_num, "")
        check_info = parse_check_from_text(option_text) if option_text else None
        if check_info:
            ability_cn, ability_key, dc = check_info
            ability_mod = modifier(getattr(character, ability_key))
            roll = dice_random.randint(1, 20)
            total, success, word, color, line = _resolve_check(roll, ability_mod, dc)
            check_text = (
                f"[yellow]{ability_cn}检定[/yellow] DC [bold]{dc}[/bold] | 调整值: {ability_mod:+d}\n"
                f"[grey50]{line}[/grey50]\n[bold {color}]{word}[/bold {color}]"
            )
            transformed = f"[选择选项{selected_num}] {option_text} | [检定] d20({roll})+({ability_mod:+d})={total} {word}"
        elif re.search(r'[（(]\s*攻击\s*检定', option_text):
            roll = dice_random.randint(1, 20)
            target_ac = _find_target_ac(gm)
            total, atk_bonus, hit, word, color, line = _resolve_attack(roll, character, target_ac)
            ac_label = target_ac if target_ac is not None else "?"
            check_text = (
                f"[yellow]攻击检定[/yellow] AC [bold]{ac_label}[/bold] | 加值: {atk_bonus:+d}\n"
                f"[grey50]{line}[/grey50]"
            )
            if word:
                check_text += f"\n[bold {color}]{word}[/bold {color}]"
            transformed = (
                f"[选择选项{selected_num}] {option_text} | [攻击] d20({roll})+({atk_bonus:+d})={total}"
                + (f" {word}" if word else "")
            )
        else:
            transformed = f"[选择选项{selected_num}] {option_text or selected_num}"

    return transformed, record_to_display(record, is_option), check_text


class BaseRound:
    """回合级共享：DM 调用（含监督者审计落账）、日志、玩家输入解析、决定块渲染。"""

    def __init__(self, ctx: RoundContext):
        self.ctx = ctx
        self.gm = ctx.gm
        self.character = ctx.gm.character
        self.regulator = ctx.regulator
        self.supervisor = ctx.supervisor
        self.world = ctx.regulator.world
        self.toolbox = ctx.toolbox

    # ── DM 调用 ──

    def dm_call(self, user_text, tools=None, status="DM 思考中...",
                protected_npcs=None, mode="full", tag=""):
        """单次 DM 调用：流式收集 → 监督者审计/落账。返回 (audit, elapsed)。

        tools：传 None 用工具箱 schemas；传 [] 表示不给工具（段内纯叙事调用）。
        mode：'full' 完整落账；'light' 仅剥离变更区块、不落账（段内叙事用，防止双重结算）。
        """
        if tools is None:
            tools = self.toolbox.schemas()
        system_override = None
        if mode == "light":
            from core.game_master import NARRATION_SYSTEM_PROMPT
            system_override = NARRATION_SYSTEM_PROMPT
        self.toolbox.results = []
        self.toolbox.check_results = []
        t0 = _time.time()
        raw = ""
        for attempt in range(2):
            h_len = len(self.gm.history)
            c_len = len(self.gm.compressed_history)
            parts = []
            console.print()
            console.print(f"[grey50]{status}[/grey50]")
            for chunk in self.gm.send_message_stream(
                user_text,
                tools=tools or None,
                tool_executor=self.toolbox.execute,
                status_cb=lambda msg: console.print(f"[grey50]{msg}[/grey50]"),
                system_override=system_override,
                round_num=self.ctx.round_num,
            ):
                parts.append(chunk)
            raw = "".join(parts)
            if raw.strip():
                break
            while len(self.gm.history) > h_len:
                self.gm.history.pop()
            while len(self.gm.compressed_history) > c_len:
                self.gm.compressed_history.pop()
            if attempt == 0:
                console.print("[red]DM 返回为空，正在重试…[/red]")
            else:
                console.print("[red]DM 多次返回为空，本轮无叙事输出。[/red]")
        elapsed = _time.time() - t0
        raw = "".join(parts)
        self.gm.last_tool_results = list(self.toolbox.results)
        audit = self.supervisor.audit(raw, protected_npcs=protected_npcs, mode=mode)
        if not self.gm.history:
            self.gm.set_history([])
        console.print(f"[grey50]思考耗时: {format_elapsed(elapsed)}{self.gm.usage_summary()}[/grey50]")
        console.print()
        if tag:
            log_dm_response(
                self.ctx.round_num, user_text, audit.text,
                raw_text=raw, tag=tag,
                change_messages="\n".join(audit.messages) if audit.messages else "",
            )
        return audit, elapsed

    # ── 玩家输入 ──

    def world_context(self) -> str:
        """当前世界状态上下文（注入段级 DM 调用，保证短上下文也能感知全局）。"""
        return self.world.render_context_for_llm(
            self.character.name, self.character.ac,
            self.character.hp, self.character.max_hp,
        ) or ""

    def resolve_input(self, raw, from_command=False):
        return resolve_player_input(self.gm, self.character, raw, from_command)

    def render_decision(self, decision_text):
        render_decision_block(decision_text)
