import sys
import time as _time
from pathlib import Path

from rich.panel import Panel
from rich.prompt import Prompt
from rich.markup import escape
from rich import box

from config import Config
from character import Character, RACES, CLASSES, BACKGROUNDS, ARMOR_BY_CLASS, CLASS_DEFAULT_SKILLS, HIT_DICE
from game_master import GameMaster
from core.ui import console, render_dm_output
from core.game_loop import (
    game_loop, save_game, load_game, log_dm_response,
    list_saves, SAVE_DIR, LOG_DIR, _show_round_recap,
)
from core.setting import list_settings, load_setting

SETTINGS_DIR = Path(__file__).resolve().parent.parent / "settings"


# ---------- API 连接测试 ----------

def _test_api_connection(model: str) -> bool:
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=Config.API_BASE_URL,
            api_key=Config.API_KEY,
            timeout=10,
        )
        console.print("[grey50]测试 API 连接...[/grey50]")
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        console.print("[green]API 连接成功[/green]")
        return True
    except Exception as e:
        console.print(f"[grey50]连接失败: {e}[/grey50]")
        return False


# ---------- 配置 ----------

def _setup_interactive():
    console.print("\n[steel_blue]配置 API[/steel_blue]")
    console.print("输入你的 LLM API 信息（支持 OpenAI / DeepSeek / 任何兼容服务）\n")

    while True:
        base_url = Prompt.ask("API 地址")
        if base_url.strip():
            break
        console.print("[grey50]API 地址不能为空，请重新输入[/grey50]")

    while True:
        api_key = Prompt.ask("API 密钥")
        if api_key.strip():
            break
        console.print("[grey50]API 密钥不能为空，请重新输入[/grey50]")

    model = Config._detect_model(base_url)

    lines = [
        f"API_BASE_URL={base_url}",
        f"API_KEY={api_key}",
        f"MODEL_NAME={model}",
    ]
    Path(".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    Config.load()

    if not _test_api_connection(model):
        console.print("[indian_red]API 连接测试失败，可稍后通过菜单重新配置[/indian_red]")
        return


def check_config():
    if Config.is_ready():
        return
    console.print("\n[steel_blue]欢迎来到大模型地下城！[/steel_blue]")
    console.print("[grey50]检测到未配置 API，进入交互式设置。[/grey50]")
    _setup_interactive()
    if not Config.is_ready():
        console.print("\n[indian_red]配置后仍不完整，请检查输入。[/indian_red]")
        sys.exit(1)


# ---------- 角色创建 ----------

def create_character() -> Character:
    console.print(f"\n[steel_blue]创建你的角色[/steel_blue]")
    console.print("1. 快速创建（随机生成，直接开玩）")
    console.print("2. 详细创建（手动分配属性）")
    mode = Prompt.ask(escape("选择 [1/2]"))
    if not mode or mode == "1":
        return _quick_character()
    return _detailed_character()


def _quick_character() -> Character:
    import random
    name = Prompt.ask("角色名称（留空回车随机）")
    if not name:
        confirm = Prompt.ask("是否随机生成名字？（再次回车确认随机，或直接输入名字）")
        if not confirm:
            import random as _rand
            fantasy_names = ["艾琳", "索恩", "灰风", "夜影", "石心", "霜牙", "火鬃", "刃歌", "晨星", "雾行"]
            name = _rand.choice(fantasy_names)
        else:
            name = confirm
    race = random.choice(RACES)
    char_class = random.choice(CLASSES)
    background = random.choice(BACKGROUNDS)

    attrs = ["力量", "敏捷", "体质", "智力", "感知", "魅力"]
    vals = [15, 14, 13, 12, 10, 8]
    random.shuffle(vals)
    stats = dict(zip(attrs, vals))

    hd = HIT_DICE.get(char_class, 10)
    con_mod = (stats["体质"] - 10) // 2
    hp = hd + con_mod

    desc = f"一位{race}{char_class}，背景是{background}。"

    console.print(f"\n[steel_blue]角色已生成！[/steel_blue]")
    console.print(f"  {race} {char_class} | 背景: {background}")
    console.print(f"  HP:{hp} AC:{ARMOR_BY_CLASS.get(char_class, 10)}")
    stats_line = "  ".join(f"{k}:{v}" for k, v in stats.items())
    console.print(f"  {stats_line}")

    char = Character(
        name=name, race=race, char_class=char_class,
        background=background, description=desc, level=1,
        hp=hp, max_hp=hp,
        strength=stats["力量"], dexterity=stats["敏捷"],
        constitution=stats["体质"], intelligence=stats["智力"],
        wisdom=stats["感知"], charisma=stats["魅力"],
        skills=list(CLASS_DEFAULT_SKILLS.get(char_class, [])),
        inventory=[],
        gender=random.choice(["男", "女"]),
        age=random.choice(["少年", "青年", "壮年", "中年"]),
        gp=30,
    )
    _init_equipment(char)
    return char


def _detailed_character() -> Character:
    name = Prompt.ask("角色名称")

    console.print("\n[bold]选择种族:[/bold]")
    for i, race in enumerate(RACES, 1):
        console.print(f"  {i}. {race}")
    race = _menu_choice(RACES, "种族")

    console.print("\n[bold]选择职业:[/bold]")
    for i, cls in enumerate(CLASSES, 1):
        console.print(f"  {i}. {cls}")
    char_class = _menu_choice(CLASSES, "职业")

    console.print("\n[bold]选择背景:[/bold]")
    for i, bg in enumerate(BACKGROUNDS, 1):
        console.print(f"  {i}. {bg}")
    background = _menu_choice(BACKGROUNDS, "背景")

    gender = Prompt.ask("性别", default="男")
    age = Prompt.ask("年龄", default="青年")
    desc = Prompt.ask("角色描述（外貌、性格等）")

    console.print("\n[bold]分配属性点（标准阵列: 15,14,13,12,10,8）[/bold]")
    stats = {"力量": 0, "敏捷": 0, "体质": 0, "智力": 0, "感知": 0, "魅力": 0}
    remaining = [15, 14, 13, 12, 10, 8]
    for attr in stats:
        console.print(f"  可用: {remaining}")
        while True:
            try:
                val = int(Prompt.ask(f"{attr}"))
                if val in remaining:
                    stats[attr] = val
                    remaining.remove(val)
                    break
                console.print(f"[grey50]请从 {remaining} 中选择[/grey50]")
            except ValueError:
                pass

    hd = HIT_DICE.get(char_class, 10)
    con_mod = (stats["体质"] - 10) // 2
    hp = hd + con_mod

    char = Character(
        name=name, race=race, char_class=char_class,
        background=background, gender=gender, age=age,
        description=desc, level=1, hp=hp, max_hp=hp,
        skills=list(CLASS_DEFAULT_SKILLS.get(char_class, [])),
        strength=stats["力量"], dexterity=stats["敏捷"],
        constitution=stats["体质"], intelligence=stats["智力"],
        wisdom=stats["感知"], charisma=stats["魅力"],
        inventory=[],
        gp=30,
    )
    _init_equipment(char)
    return char


def _menu_choice(options: list, label: str) -> str:
    while True:
        try:
            choice = int(Prompt.ask(f"请选择{label}"))
            if 1 <= choice <= len(options):
                return options[choice - 1]
        except ValueError:
            pass
        console.print("[grey50]无效选择[/grey50]")


def _init_equipment(char: Character):
    char.equipment["身体"] = "旅行者服装"
    char.inventory = ["背包", "水袋", "口粮x5"]
    class_gear = {
        "战士": ("长剑", "木盾"),
        "法师": ("法术书", "木棍"),
        "盗贼": ("匕首", "盗贼工具"),
        "牧师": ("钉头锤", "圣徽"),
        "圣骑士": ("长剑", "圣徽"),
        "游侠": ("长弓", "箭袋x20"),
        "德鲁伊": ("橡木法杖", "圣徽"),
        "术士": ("奥术法杖", "匕首"),
        "吟游诗人": ("鲁特琴", "匕首"),
        "武僧": ("木棍", ""),
        "野蛮人": ("巨斧", ""),
        "邪术师": ("法杖", "匕首"),
    }
    weapon, offhand = class_gear.get(char.char_class, ("", ""))
    if weapon:
        char.equipment["武器"] = weapon
    if offhand:
        if offhand in ("木盾", "圣徽"):
            char.equipment["副手"] = offhand
        else:
            char.inventory.append(offhand)


# ---------- 主菜单 ----------

def main():
    Config.load()
    check_config()

    if Config.is_ready() and not _test_api_connection(Config.MODEL_NAME):
        console.print("[indian_red]API 连接失败，游戏需要 API 才能运行[/indian_red]")
        if Prompt.ask("重新配置 API？y/n") in ("y", "yes", ""):
            _setup_interactive()
            main()
        else:
            sys.exit(1)
        return

    logo = (
        "  ██╗       ██╗       ███╗   ███╗  ██████╗   ███╗   ██╗  ██████╗ \n"
        "  ██║       ██║       ████╗ ████║  ██╔══██╗  ████╗  ██║  ██╔══██╗\n"
        "  ██║       ██║       ██╔████╔██║  ██║  ██║  ██╔██╗ ██║  ██║  ██║\n"
        "  ██║       ██║       ██║╚██╔╝██║  ██║  ██║  ██║╚██╗██║  ██║  ██║\n"
        "  ██████╗   ██████╗   ██║ ╚═╝ ██║  ██████╔╝  ██║ ╚████║  ██████╔╝\n"
        "  ╚═════╝   ╚═════╝   ╚═╝     ╚═╝  ╚═════╝   ╚═╝  ╚═══╝  ╚═════╝ \n"
        "\n"
        "                         [grey50]由 AI 驱动的 D&D 终端游戏[/grey50]"
    )
    console.print(Panel(
        logo,
        border_style="steel_blue",
        box=box.SQUARE,
        padding=(1, 4),
    ))
    console.print()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    saves = list(SAVE_DIR.glob("*.json")) + [d for d in SAVE_DIR.iterdir() if d.is_dir()]

    if saves:
        console.print("[grey62]检测到存档[/grey62]")
        console.print("1. 继续游戏")
        console.print("2. 新游戏")
        console.print("3. 修改 API 配置")
        choice = Prompt.ask(escape("选择 [1/2/3]"))
    else:
        console.print("1. 新游戏")
        if Config.is_ready():
            console.print("2. 修改 API 配置")
            choice = Prompt.ask(escape("选择 [1/2]"))
        else:
            choice = "1"

    if (saves and choice == "3") or (not saves and choice == "2" and Config.is_ready()):
        _setup_interactive()
        main()
        return

    if saves and (not choice or choice == "1"):
        saves_list = list_saves()
        try:
            idx = int(Prompt.ask("选择编号")) - 1
            if 0 <= idx < len(saves_list):
                gm = load_game(str(saves_list[idx]))
                _show_round_recap(gm)
                game_loop(gm)
                return
        except ValueError:
            console.print("[grey50]请输入有效数字[/grey50]")
        except:
            pass

    # 选择世界背景
    settings_list = list_settings()
    console.print("\n[steel_blue]选择世界背景[/steel_blue]")
    if settings_list:
        for i, (display, stem) in enumerate(settings_list, 1):
            console.print(f"  {i}. {display}")
        if len(settings_list) == 1:
            setting_stem = settings_list[0][1]
            console.print(f"[grey50]使用 {settings_list[0][0]} 背景[/grey50]")
        else:
            bg_choice = Prompt.ask(escape(f"选择 [1-{len(settings_list)}]"))
            try:
                idx = int(bg_choice) - 1
                setting_stem = settings_list[idx][1] if 0 <= idx < len(settings_list) else settings_list[0][1]
            except (ValueError, IndexError):
                setting_stem = settings_list[0][1]
    else:
        setting_stem = "default-dnd"
    setting_content = load_setting(setting_stem)

    char = create_character()

    console.print("\n[steel_blue]选择开场模板[/steel_blue]")
    console.print("1. 随机世界（完全随机生成）")
    console.print("2. 「渡者」（一上来就遇到中立向导）")
    console.print("3. 「伏击」（一上来就遭遇敌人）")
    console.print("4. 「旅伴」（一上来就遇到友善NPC）")
    tpl = Prompt.ask(escape("选择 [1/2/3/4]"))
    if not tpl or tpl not in ("1", "2", "3", "4"):
        tpl = "1"
    template_map = {"1": "random", "2": "guide", "3": "ambush", "4": "ally"}
    gm = GameMaster(char, template_map[tpl], setting_content=setting_content, setting_stem=setting_stem)

    console.print("\n[grey62]冒险即将开始...[/grey62]")
    try:
        _t0 = _time.time()
        parts = []
        for chunk in gm.send_message_stream("DM，请开始我的冒险吧！"):
            parts.append(chunk)
        _elapsed = _time.time() - _t0
        initial_text = "".join(parts)
        log_dm_response(0, "（游戏开始）", initial_text)
        render_dm_output(initial_text, gm, _elapsed)
    except Exception as e:
        console.print(f"[indian_red]错误: {e}[/indian_red]")

    result = game_loop(gm)
    if result == "new_game":
        main()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]再见！[/yellow]")
        sys.exit(0)
