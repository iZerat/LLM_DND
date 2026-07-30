import json
import re
import random as dice_random
import time as _time
from pathlib import Path

from rich.prompt import Prompt
from rich.markup import escape
from rich.panel import Panel
from rich import box

from config import Config
from character import Character, modifier
from game_master import GameMaster, ABILITY_CN_TO_EN, parse_check_from_text
from core.ui import (
    console, render_dm_output, show_status, show_info,
    show_equip, show_bag, show_skills, show_time, show_help,
    set_round_counter, get_round_counter,
)

SAVE_DIR = Path("./saves")
LOG_DIR = Path("./logs")


# ---------- 存档 ----------

def list_saves():
    saves = sorted(SAVE_DIR.glob("*.json"))
    dirs = sorted(d for d in SAVE_DIR.iterdir() if d.is_dir())
    if not saves and not dirs:
        return []
    console.print("\n[bold]存档列表:[/bold]")
    for i, save in enumerate(saves, 1):
        size = save.stat().st_size
        console.print(f"  {i}. {save.stem} ({size}B) [grey50]旧格式[/grey50]")
    for i, d in enumerate(dirs, len(saves) + 1):
        console.print(f"  {i}. {d.name} [grey50]文件夹[/grey50]")
    return saves + dirs


def save_game(gm: GameMaster, name: str = None):
    if not name:
        name = gm.character.name
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    char_dir = SAVE_DIR / name
    char_dir.mkdir(parents=True, exist_ok=True)

    (char_dir / "info.json").write_text(
        json.dumps(gm.character.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (char_dir / "equip.json").write_text(
        json.dumps(gm.character.inventory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (char_dir / "skill.json").write_text(
        json.dumps(gm.character.skills, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    history_meta = {"last_scene": gm.last_scene, "last_scene_detail": gm.last_scene_detail, "last_time": gm.last_time, "setting_stem": gm.setting_stem}
    (char_dir / "history.json").write_text(
        json.dumps({"meta": history_meta, "compressed": gm.compressed_history, "last_assistant": gm.last_assistant}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    console.print(f"[grey50]已保存: {name}[/grey50]")


def _migrate_char_data(data: dict) -> dict:
    if "gold" in data and "gp" not in data:
        data["gp"] = data.pop("gold")
    if "equipment" not in data:
        data["equipment"] = {"武器": "", "副手": "", "头部": "", "身体": "", "背部": "", "项链": "", "戒指1": "", "戒指2": ""}
    if "inventory" not in data:
        data["inventory"] = []
    if "gp" not in data:
        data["gp"] = 0
    if "sp" not in data:
        data["sp"] = 0
    if "cp" not in data:
        data["cp"] = 0
    return data


def load_game(save_path: str) -> GameMaster:
    path = Path(save_path)
    if path.is_dir():
        info = json.loads((path / "info.json").read_text(encoding="utf-8"))
        info = _migrate_char_data(info)
        char = Character(**info)
        gm = GameMaster(char)
        history_path = path / "history.json"
        if history_path.exists():
            data = json.loads(history_path.read_text(encoding="utf-8"))
            gm.compressed_history = data.get("compressed", [])
            gm.last_assistant = data.get("last_assistant", "")
            meta = data.get("meta", {})
            gm.last_scene = meta.get("last_scene", "")
            gm.last_scene_detail = meta.get("last_scene_detail", "")
            gm.last_time = meta.get("last_time", "")
            setting_stem = meta.get("setting_stem", "")
            if setting_stem:
                gm.setting_stem = setting_stem
                from core.setting import load_setting
                gm.setting_content = load_setting(setting_stem)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        char_data = _migrate_char_data(data["character"])
        char = Character(**char_data)
        gm = GameMaster(char)
        if "history" in data:
            gm.set_history(data["history"])
        if "last_scene" in data:
            gm.last_scene = data["last_scene"]
        if "last_scene_detail" in data:
            gm.last_scene_detail = data["last_scene_detail"]
        if "last_time" in data:
            gm.last_time = data["last_time"]
    console.print(f"[grey50]已加载: {path.stem}[/grey50]")
    return gm


# ---------- 日志 ----------

def log_dm_response(round_num: int, player_input: str, response_text: str):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = _time.strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"round_{round_num:03d}_{ts}.txt"
    content = f">>> 玩家: {player_input}\n\n{response_text}\n"
    path.write_text(content, encoding="utf-8")


# ---------- 投骰与检定 ----------

def _interactive_check(char: Character, ability_cn: str, ability_key: str, dc: int) -> tuple[int, int, int, bool]:
    ability_mod = modifier(getattr(char, ability_key))
    console.print()
    console.print(f"[yellow]{ability_cn}检定[/yellow] DC [bold]{dc}[/bold] | 调整值: {ability_mod:+d}")
    roll = dice_random.randint(1, 20)
    total = roll + ability_mod
    success = total >= dc
    result_word = "成功" if success else "失败"
    result_color = "green" if success else "red"
    console.print(f"[grey50]d20({roll}) + ({ability_mod:+d}) = {total}[/grey50]")
    console.print(f"[bold {result_color}]{result_word}[/bold {result_color}]")
    console.print()
    return roll, ability_mod, total, success


def _roll_expression(expr: str) -> tuple[int, str]:
    def roll_dice(m):
        count = int(m.group(1)) if m.group(1) else 1
        sides = int(m.group(2))
        mod = int(m.group(3)) if m.group(3) else 0
        if count < 1:
            count = 1
        results = [dice_random.randint(1, sides) for _ in range(count)]
        total = sum(results) + mod
        return str(total)

    expr_parsed = re.sub(r"(\d+)?d(\d+)(?:\s*\+\s*(\d+))?", roll_dice, expr)
    try:
        total = eval(expr_parsed)
    except:
        return 0, f"[grey50]无效骰子表达式: {expr}[/grey50]"
    return total, f"[grey50]{expr} = {total}[/grey50]"


# ---------- 上轮记录 ----------

def _show_round_recap(gm):
    if gm.last_assistant:
        val = gm.compressed_history[-1]["round"] - 1 if gm.compressed_history else 0
        set_round_counter(val)
        render_dm_output(gm.last_assistant, gm)


# ---------- 游戏循环 ----------

def game_loop(gm: GameMaster):
    console.print(f"\n[steel_blue]{gm.character.name}[/steel_blue] 的冒险开始了！输入 [grey62]/help[/grey62] 查看命令\n")
    last_choice_record = ""

    while True:
        try:
            player_input = Prompt.ask(f"[grey82]{gm.character.name}[/grey82]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n冒险结束！")
            break

        if not player_input.strip():
            continue

        cmd = player_input.strip().lower()

        if cmd == "/quit":
            save = Prompt.ask("是否保存？y/n")
            if save in ("y", "yes", ""):
                save_game(gm)
                console.print("冒险结束！")
                break
            else:
                confirm = Prompt.ask("是否退出游戏？y/n")
                if confirm in ("y", "yes", ""):
                    console.print("冒险结束！")
                    break
            continue
        elif cmd in ("/help", "/"):
            show_help()
            continue
        elif cmd == "/status":
            show_status(gm.character)
            continue
        elif cmd == "/info":
            show_info(gm.character)
            continue
        elif cmd == "/scene":
            from core.ui import _filter_scene_fields
            if gm.last_scene:
                scene_text = _filter_scene_fields(gm.last_scene, basic_only=False)
                console.print(Panel(
                    scene_text,
                    title="[grey58]完整场景信息[/grey58]",
                    border_style="grey58",
                    box=box.SQUARE,
                ))
            else:
                console.print("[grey50]尚无场景信息[/grey50]")
            continue
        elif cmd.startswith("/save"):
            parts = player_input.strip().split(maxsplit=1)
            save_game(gm, parts[1] if len(parts) > 1 else None)
            continue
        elif cmd == "/load":
            saves = list_saves()
            if not saves:
                console.print("[grey50]没有找到存档[/grey50]")
                continue
            try:
                idx = int(Prompt.ask("选择编号")) - 1
                if 0 <= idx < len(saves):
                    gm = load_game(str(saves[idx]))
                    show_status(gm.character)
            except ValueError:
                console.print("[grey50]请输入有效数字[/grey50]")
            except:
                console.print("[grey50]无效选择[/grey50]")
            continue
        elif cmd == "/menu":
            save = Prompt.ask("是否保存？y/n")
            if save in ("y", "yes", ""):
                save_game(gm)
                return "menu"
            else:
                confirm = Prompt.ask("是否返回主菜单？y/n")
                if confirm in ("y", "yes", ""):
                    return "menu"
            continue
        elif cmd == "/equip":
            show_equip(gm.character)
            continue
        elif cmd == "/bag":
            show_bag(gm.character)
            continue

        elif cmd == "/skill":
            show_skills(gm.character)
            continue
        elif cmd == "/time":
            show_time(gm)
            continue
        elif cmd.startswith("/roll"):
            rest = player_input[5:].strip()
            if not rest:
                rest = "d20"

            dc_match = re.match(r"(\S+)\s+DC\s+(\d+)", rest) if not rest.startswith("d") else None
            if dc_match and dc_match.group(1) in ABILITY_CN_TO_EN:
                ability_cn = dc_match.group(1)
                ability_key = ABILITY_CN_TO_EN[ability_cn]
                dc = int(dc_match.group(2))
                r, m, t, success = _interactive_check(gm.character, ability_cn, ability_key, dc)
                rw = "成功" if success else "失败"
                player_input = f"[检定] {ability_cn} DC {dc}: d20({r})+({m:+d})={t} {rw}"
            elif rest in ABILITY_CN_TO_EN:
                ability_key = ABILITY_CN_TO_EN[rest]
                ability_mod = modifier(getattr(gm.character, ability_key))
                roll = dice_random.randint(1, 20)
                total = roll + ability_mod
                console.print(f"\n[grey50]d20({roll}) + ({ability_mod:+d}) = {total}[/grey50]")
                player_input = f"[检定] {rest}: d20({roll})+({ability_mod:+d})={total}"
            else:
                total, display = _roll_expression(rest)
                console.print(f"\n{display}")
                player_input = f"[投骰] {rest} = {total}"
        elif cmd.startswith("/"):
            console.print("[grey50]无效命令，输入 /help 查看可用命令[/grey50]")
            continue

        last_was_option = False
        if not cmd.startswith("/"):
            raw = player_input.strip()
            if raw in gm.last_choices_map:
                last_choice_record = gm.last_choices_map[raw]
                last_was_option = True
            else:
                last_choice_record = raw

        check_text = ""
        if player_input.strip().isdigit():
            selected_num = player_input.strip()
            option_text = gm.last_choices_map.get(selected_num, "")
            check_info = parse_check_from_text(option_text) if option_text else None
            if check_info:
                ability_cn, ability_key, dc = check_info
                ability_mod = modifier(getattr(gm.character, ability_key))
                roll = dice_random.randint(1, 20)
                total = roll + ability_mod
                success = total >= dc
                result_color = "green" if success else "red"
                result_word = "\u6210\u529f" if success else "\u5931\u8d25"
                check_text = f"[yellow]{ability_cn}\u68c0\u5b9a[/yellow] DC [bold]{dc}[/bold] | \u8c03\u6574\u503c: {ability_mod:+d}\n[grey50]d20({roll}) + ({ability_mod:+d}) = {total}[/grey50]\n[bold {result_color}]{result_word}[/bold {result_color}]"
                player_input = f"[\u9009\u62e9\u9009\u9879{selected_num}] {option_text} | [\u68c0\u5b9a] d20({roll})+({ability_mod:+d})={total} {result_word}"
            else:
                player_input = f"[\u9009\u62e9\u9009\u9879{selected_num}] {option_text or selected_num}"

        if last_choice_record:
            record_display = last_choice_record
            if last_was_option:
                record_display = re.sub(
                    r'([（(][^）)]*(?:(?:力量|敏捷|体质|智力|感知|魅力)|检定|击骰)[^）)]*[）)])',
                    r'[#5DCCCC]\1[/#5DCCCC]',
                    record_display,
                )
                m = re.match(r"^(\d+[.)])\s*(.*)", record_display)
                if m:
                    record_text = f"[white]{m.group(1)}[/white] [#F9F1A5]{m.group(2)}[/#F9F1A5]"
                else:
                    record_text = f"[#F9F1A5]{record_display}[/#F9F1A5]"
            else:
                record_text = record_display
            if check_text:
                record_text += "\n\n" + check_text
            console.print(Panel(
                record_text,
                title="[#9b87c4]行动[/#9b87c4]",
                border_style="#9b87c4",
                box=box.SQUARE,
            ))

        try:
            response_parts = []
            _t0 = _time.time()
            console.print()
            console.print("[grey50]DM 思考中...[/grey50]")
            for chunk in gm.send_message_stream(player_input):
                response_parts.append(chunk)
            _elapsed = _time.time() - _t0

            full = "".join(response_parts).replace("（无需检定）", "")

            log_dm_response(get_round_counter() + 1, player_input, full)

            if not gm.history:
                gm.set_history([])

            if gm.needs_repair(full):
                full = gm.repair_status(full)
                log_dm_response(get_round_counter() + 1, "（修复状态）", full)

            console.print(f"[grey50]\u601d\u8003\u8017\u65f6: {_elapsed:.1f}s[/grey50]")
            console.print()
            render_dm_output(full, gm, _elapsed)

            if getattr(gm, '_truncated', False):
                console.print("[grey50]（注意：回答被截断，可尝试 /continue 让 DM 继续输出，或简化指令）[/grey50]")

        except KeyboardInterrupt:
            console.print("\n[grey50]中断[/grey50]")
        except Exception as e:
            from rich.markup import escape
            console.print(f"\n[indian_red]错误: {escape(str(e))}[/indian_red]")
