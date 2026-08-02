from __future__ import annotations
"""游戏命令注册表与回合回顾展示（从 core.game_loop 拆出）。

切断 game_round → game_loop 的架构环：回合子系统只依赖本模块，
不再反向引用游戏循环外壳。存档/读档仍归 core.game_loop 持有，
本模块作为命令层消费其 save/load 接口。
"""
import re
import random as dice_random

from rich.prompt import Prompt
from rich.panel import Panel
from rich import box

from core.character import modifier
from core.game_master import ABILITY_CN_TO_EN
from core.commands import build_registry
from core.ui import (
    console, render_dm_output, show_status, show_info,
    show_equip, show_bag, show_skills, show_time, show_help,
    set_round_counter,
)


def _show_round_recap(gm):
    if gm.last_assistant:
        val = gm.compressed_history[-1]["round"] - 1 if gm.compressed_history else 0
        set_round_counter(val)
        render_dm_output(gm.last_assistant, gm)


class _GameCmdResult:
    """命令处理结果。action: continue / quit / menu / load / narrative"""
    def __init__(self, action="continue", gm=None, player_input=None):
        self.action = action
        self.gm = gm
        self.player_input = player_input


def _game_show_help(gm, args):
    show_help()
    return _GameCmdResult()


def _game_status(gm, args):
    show_status(gm.character)
    return _GameCmdResult()


def _game_info(gm, args):
    show_info(gm.character)
    return _GameCmdResult()


def _game_scene(gm, args):
    from core.ui import current_scene, _filter_env_fields
    scene = current_scene(gm)
    if scene is not None and (scene.environment or scene.location or scene.name):
        env = scene.environment or {}
        parts = [f"{k}：{v}" for k, v in env.items() if v]
        if scene.location and "地点" not in env:
            parts.append(f"地点：{scene.location}")
        if not parts:
            parts.append(scene.name or "未知场景")
        scene_text = "\n".join(parts)
        console.print(Panel(
            scene_text,
            title="[grey58]完整环境信息[/grey58]",
            border_style="grey58",
            box=box.SQUARE,
        ))
    elif gm.last_scene:
        scene_text = _filter_env_fields(gm.last_scene, basic_only=False)
        console.print(Panel(
            scene_text,
            title="[grey58]完整环境信息[/grey58]",
            border_style="grey58",
            box=box.SQUARE,
        ))
    else:
        console.print("[grey50]尚无环境信息[/grey50]")
    return _GameCmdResult()


def _game_equip(gm, args):
    show_equip(gm.character)
    return _GameCmdResult()


def _game_bag(gm, args):
    show_bag(gm.character)
    return _GameCmdResult()


def _game_skill(gm, args):
    show_skills(gm.character)
    return _GameCmdResult()


def _game_time(gm, args):
    show_time(gm)
    return _GameCmdResult()


def _game_save(gm, args):
    from core.game_loop import save_game
    save_game(gm, args or None)
    return _GameCmdResult()


def _game_load(gm, args):
    from core.game_loop import load_game, list_saves, SAVE_DIR
    saves = list_saves()
    if not saves:
        console.print("[grey50]没有找到存档[/grey50]")
        return _GameCmdResult()
    try:
        idx = int(Prompt.ask("选择编号")) - 1
    except ValueError:
        console.print("[grey50]请输入有效数字[/grey50]")
        return _GameCmdResult()
    if not (0 <= idx < len(saves)):
        console.print("[grey50]无效选择[/grey50]")
        return _GameCmdResult()
    try:
        new_gm = load_game(str(SAVE_DIR / saves[idx]))
        return _GameCmdResult(action="load", gm=new_gm)
    except Exception as e:
        console.print(f"[grey50]读取存档失败: {e}[/grey50]")
    return _GameCmdResult()


def _game_menu(gm, args):
    from core.game_loop import save_game
    save = Prompt.ask("是否保存？y/n")
    if save in ("y", "yes", ""):
        save_game(gm)
        return _GameCmdResult(action="menu")
    confirm = Prompt.ask("是否返回主菜单？y/n")
    if confirm in ("y", "yes", ""):
        return _GameCmdResult(action="menu")
    return _GameCmdResult()


def _game_quit(gm, args):
    from core.game_loop import save_game
    save = Prompt.ask("是否保存？y/n")
    if save in ("y", "yes", ""):
        save_game(gm)
        return _GameCmdResult(action="quit")
    confirm = Prompt.ask("是否退出游戏？y/n")
    if confirm in ("y", "yes", ""):
        return _GameCmdResult(action="quit")
    return _GameCmdResult()


def _game_roll(gm, args):
    from resource.checker import Checker
    checker = Checker(gm.character, None, None)
    rest = args or "d20"
    dc_match = re.match(r"(\S+)\s+DC\s+(\d+)", rest) if not rest.startswith("d") else None
    if dc_match and dc_match.group(1) in ABILITY_CN_TO_EN:
        ability_cn = dc_match.group(1)
        ability_key = ABILITY_CN_TO_EN[ability_cn]
        dc = int(dc_match.group(2))
        r, m, t, success = checker.interactive_check(gm.character, ability_cn, ability_key, dc)
        _, _, rw, _, _ = checker.resolve_check(r, m, dc)
        player_input = f"[检定] {ability_cn} DC {dc}: d20({r})+({m:+d})={t} {rw}"
    elif rest in ABILITY_CN_TO_EN:
        ability_key = ABILITY_CN_TO_EN[rest]
        ability_mod = modifier(getattr(gm.character, ability_key))
        roll = dice_random.randint(1, 20)
        total = roll + ability_mod
        tag = " [大成功]" if roll == 20 else (" [大失败]" if roll == 1 else "")
        console.print(f"\n[grey50]d20({roll}) + ({ability_mod:+d}) = {total}{tag}[/grey50]")
        player_input = f"[检定] {rest}: d20({roll})+({ability_mod:+d})={total}{tag}"
    else:
        total, display = checker.roll_expression(rest)
        console.print(f"\n{display}")
        player_input = f"[投骰] {rest} = {total}"
    return _GameCmdResult(action="narrative", player_input=player_input)


def _build_game_registry():
    reg = build_registry()
    reg.get("help").handler = _game_show_help
    reg.get("status").handler = _game_status
    reg.get("info").handler = _game_info
    reg.get("scene").handler = _game_scene
    reg.get("equip").handler = _game_equip
    reg.get("bag").handler = _game_bag
    reg.get("skill").handler = _game_skill
    reg.get("time").handler = _game_time
    reg.get("save").handler = _game_save
    reg.get("load").handler = _game_load
    reg.get("menu").handler = _game_menu
    reg.get("quit").handler = _game_quit
    reg.get("roll").handler = _game_roll
    return reg


GAME_REGISTRY = _build_game_registry()
