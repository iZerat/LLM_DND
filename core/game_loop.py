import json
import re
import random as dice_random
import time as _time
from pathlib import Path

from rich.prompt import Prompt
from rich.markup import escape
from rich.panel import Panel
from rich import box

from core.config import Config
from core.character import Character, modifier
from core.game_master import GameMaster, ABILITY_CN_TO_EN, parse_check_from_text
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

    # info.json — character static stats only
    info_data = gm.character.to_dict()
    (char_dir / "info.json").write_text(
        json.dumps(info_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # bag.json — inventory items (instance_id + guid)
    bag_data = [
        {"instance_id": inst.instance_id, "guid": inst.guid}
        for inst in gm.character.inventory.all_instances()
    ]
    (char_dir / "bag.json").write_text(
        json.dumps(bag_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # equip.json — equipped items (slot -> guid)
    equip_data = {
        slot: guid for slot, guid in gm.character.inventory.equipped.items() if guid
    }
    (char_dir / "equip.json").write_text(
        json.dumps(equip_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # money.json — currency (copper only)
    money_data = {"copper": gm.character.inventory.currency.copper}
    (char_dir / "money.json").write_text(
        json.dumps(money_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # skill.json — skills
    (char_dir / "skill.json").write_text(
        json.dumps(gm.character.skills, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # history.json — game history
    history_meta = {
        "last_scene": gm.last_scene,
        "last_scene_detail": gm.last_scene_detail,
        "last_time": gm.last_time,
        "setting_stem": gm.setting_stem,
    }
    (char_dir / "history.json").write_text(
        json.dumps({
            "meta": history_meta,
            "compressed": gm.compressed_history,
            "last_assistant": gm.last_assistant,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    console.print(f"[grey50]已保存: {name}[/grey50]")
    console.print()


_SLOT_CN_TO_EN = {
    "武器": "weapon", "副手": "off_hand", "头部": "head", "身体": "body",
    "背部": "back", "项链": "neck", "戒指1": "ring1", "戒指2": "ring2",
}

_SKILL_CN_TO_EN = {
    "特技": "acrobatics", "驯兽": "animal_handling", "奥秘": "arcana",
    "运动": "athletics", "欺瞒": "deception", "历史": "history",
    "洞察": "insight", "威吓": "intimidation", "调查": "investigation",
    "医药": "medicine", "自然": "nature", "察觉": "perception",
    "表演": "performance", "游说": "persuasion", "宗教": "religion",
    "巧手": "sleight_of_hand", "隐匿": "stealth", "生存": "survival",
}

_RACE_CN_TO_EN = {
    "龙裔": "dragonborn", "矮人": "dwarf", "精灵": "elf",
    "半身人": "halfling", "侏儒": "gnome", "哥利亚": "goliath",
    "人类": "human", "兽人": "orc", "提夫林": "tiefling",
}

_CLASS_CN_TO_EN = {
    "野蛮人": "barbarian", "吟游诗人": "bard", "牧师": "cleric",
    "德鲁伊": "druid", "战士": "fighter", "武僧": "monk",
    "圣骑士": "paladin", "游侠": "ranger", "盗贼": "rogue",
    "术士": "sorcerer", "邪术师": "warlock", "法师": "wizard",
}

_BG_CN_TO_EN = {
    "贵族": "noble", "流浪儿": "urchin", "学者": "sage",
    "士兵": "soldier", "罪犯": "criminal", "艺人": "entertainer",
    "水手": "sailor", "隐士": "hermit", "商贩": "merchant",
    "工匠": "artisan",
}

_GENDER_CN_TO_EN = {"男": "male", "女": "female"}


def _cn_to_en(val: str, table: dict) -> str:
    return table.get(val, val)


def _migrate_char_data(info: dict) -> dict:
    info.pop("inventory", None)
    info.pop("equipment", None)

    # age: "中年" -> 30
    if isinstance(info.get("age"), str):
        age_map = {"少年": 16, "青年": 22, "壮年": 30, "中年": 35, "老年": 55}
        info["age"] = age_map.get(info["age"], 30)

    # gender
    if info.get("gender") in _GENDER_CN_TO_EN:
        info["gender"] = _GENDER_CN_TO_EN[info["gender"]]

    # race / class / background
    if info.get("race") in _RACE_CN_TO_EN:
        info["race"] = _RACE_CN_TO_EN[info["race"]]
    if info.get("char_class") in _CLASS_CN_TO_EN:
        info["char_class"] = _CLASS_CN_TO_EN[info["char_class"]]
    if info.get("background") in _BG_CN_TO_EN:
        info["background"] = _BG_CN_TO_EN[info["background"]]

    # skills
    if "skills" in info and isinstance(info["skills"], list):
        info["skills"] = [_cn_to_en(s, _SKILL_CN_TO_EN) for s in info["skills"]]

    # saving_throws
    if "saving_throws" in info and isinstance(info["saving_throws"], list):
        info["saving_throws"] = [_cn_to_en(s, _SKILL_CN_TO_EN) for s in info["saving_throws"]]

    return info


def _migrate_load_inventory(char_dir: Path, char: Character):
    from resource.models import Inventory, Currency

    inv = Inventory()

    bag_path = char_dir / "bag.json"
    if bag_path.exists():
        bag_data = json.loads(bag_path.read_text(encoding="utf-8"))
        for entry in bag_data:
            if "instance_id" in entry:
                inst = __import__("resource.models", fromlist=["ItemInstance"]).ItemInstance(
                    instance_id=entry["instance_id"], guid=entry["guid"], quantity=1
                )
                inv.items[inst.instance_id] = inst
            else:
                inv.add_item(entry["guid"], entry.get("quantity", 1))

    equip_path = char_dir / "equip.json"
    if equip_path.exists():
        equip_data = json.loads(equip_path.read_text(encoding="utf-8"))
        for slot, guid in equip_data.items():
            slot_en = _cn_to_en(slot, _SLOT_CN_TO_EN)
            inv.equipped[slot_en] = guid

    money_path = char_dir / "money.json"
    if money_path.exists():
        money_data = json.loads(money_path.read_text(encoding="utf-8"))
        inv.currency = Currency(copper=money_data.get("copper", 0))

    char.inventory = inv


def _migrate_old_inventory(char: Character):
    from resource.models import Inventory, Currency
    from resource.item_db import item_db

    inv = Inventory()

    if hasattr(char, "equipment") and char.equipment:
        for slot_cn, name in char.equipment.items():
            if name:
                slot_en = _cn_to_en(slot_cn, _SLOT_CN_TO_EN)
                item_def = item_db.find_by_name(name) or item_db.find_best(name)
                if item_def:
                    inv.equipped[slot_en] = item_def.guid

    old_inv = getattr(char, "inventory", [])
    if isinstance(old_inv, list):
        for entry in old_inv:
            if isinstance(entry, str):
                qty = 1
                name = entry
                m = __import__("re").match(r"(.+)x(\d+)", entry)
                if m:
                    name = m.group(1)
                    qty = int(m.group(2))
                item_def = item_db.find_by_name(name) or item_db.find_best(name)
                if item_def:
                    inv.add_item(item_def.guid, qty)

    old_gp = getattr(char, "gp", 0) or 0
    old_sp = getattr(char, "sp", 0) or 0
    old_cp = getattr(char, "cp", 0) or 0
    inv.currency = Currency(copper=old_gp * 100 + old_sp * 10 + old_cp)

    for attr in ["gp", "sp", "cp", "equipment"]:
        if hasattr(char, attr):
            delattr(char, attr)

    char.inventory = inv


def load_game(save_path: str) -> GameMaster:
    path = Path(save_path)
    if path.is_dir():
        info = json.loads((path / "info.json").read_text(encoding="utf-8"))
        info = _migrate_char_data(info)
        char = Character(**info)
        _migrate_load_inventory(path, char)
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
        char_data = _migrate_char_data(data.get("character", data))
        char = Character(**char_data)
        _migrate_old_inventory(char)
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
            from core.prompt_lib import build_prompt_suffix
            prompt_reminder = build_prompt_suffix(player_input)
            if prompt_reminder:
                player_input += prompt_reminder
            response_parts = []
            _t0 = _time.time()
            console.print()
            console.print("[grey50]DM 思考中...[/grey50]")
            for chunk in gm.send_message_stream(player_input):
                response_parts.append(chunk)
            _elapsed = _time.time() - _t0

            full = "".join(response_parts).replace("（无需检定）", "")

            # ── 资源变更处理（银行柜台） ──
            from resource.manager import ResourceManager
            from resource.llm_parser import parse_item_changes
            manager = ResourceManager(gm.character.inventory)
            retries = 0
            max_retries = 3
            change_messages: list[str] = []
            while retries < max_retries:
                requests = parse_item_changes(full)
                if requests is None:
                    break
                unknown = [r for r in requests if r["action"] == "unknown"]
                if not unknown:
                    results = manager.process_requests(requests)
                    full = re.sub(
                        r'\n?\[物品变更\].*?(?=\n\[|\Z)',
                        '', full, count=1, flags=re.DOTALL
                    ).strip()
                    for r in results:
                        change_messages.append(r.message)
                    break
                retries += 1
                missing = "、".join(r["name"] for r in unknown)
                if retries >= max_retries:
                    change_messages.append(f"物品库中不存在: {missing}，已忽略相关变更，故事由 DM 自行圆场")
                    full = re.sub(
                        r'\n?\[物品变更\].*?(?=\n\[|\Z)',
                        '', full, count=1, flags=re.DOTALL
                    ).strip()
                    break
                change_messages.append(f"物品库中不存在: {missing}，DM 正在调整故事…")
                correction_prompt = f"[系统] 注意：以下物品不在游戏资源库中：{missing}。请修改你的输出，改用库中存在的物品，或修改叙事让这些物品不可获得。保留其他内容不变。请重新输出完整回答。"
                try:
                    retry_parts = []
                    for chunk in gm.send_message_stream(correction_prompt):
                        retry_parts.append(chunk)
                    full = "".join(retry_parts).replace("（无需检定）", "")
                except Exception:
                    break

            log_dm_response(get_round_counter() + 1, player_input, full)

            if not gm.history:
                gm.set_history([])

            if gm.needs_repair(full):
                full = gm.repair_status(full)
                log_dm_response(get_round_counter() + 1, "（修复状态）", full)

            console.print(f"[grey50]\u601d\u8003\u8017\u65f6: {_elapsed:.1f}s[/grey50]")
            console.print()
            render_dm_output(full, gm, _elapsed, change_messages)

            if getattr(gm, '_truncated', False):
                console.print("[grey50]（注意：回答被截断，可尝试 /continue 让 DM 继续输出，或简化指令）[/grey50]")

        except KeyboardInterrupt:
            console.print("\n[grey50]中断[/grey50]")
        except Exception as e:
            from rich.markup import escape
            console.print(f"\n[indian_red]错误: {escape(str(e))}[/indian_red]")
