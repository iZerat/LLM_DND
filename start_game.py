import sys
import io
import json
import re
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt
from rich.table import Table
from rich.columns import Columns
from rich.layout import Layout
from rich.markup import escape
from rich.text import Text
from rich.theme import Theme
from rich import box
from rich import print as rprint

from config import Config
from character import Character, RACES, CLASSES, BACKGROUNDS, ARMOR_BY_CLASS, Combatant, modifier, CLASS_DEFAULT_SKILLS
from game_master import GameMaster, ABILITY_CN_TO_EN, parse_check_from_text

theme = Theme({
    "prompt": "grey82",
    "prompt.default": "grey82",
    "prompt.choices": "grey50",
})
console = Console(theme=theme)
SAVE_DIR = Path("./saves")
LOG_DIR = Path("./logs")


# ---------- 配置检查 ----------

def _setup_interactive():
    console.print("\n[steel_blue]首次运行：配置 API[/steel_blue]")
    console.print("输入你的 LLM API 信息（支持 OpenAI / DeepSeek / 任何兼容服务）\n")

    base_url = Prompt.ask("API 地址")
    if not base_url:
        base_url = "https://api.deepseek.com"

    while True:
        api_key = Prompt.ask("API 密钥")
        if api_key.strip():
            break
        console.print("[grey50]API 密钥不能为空，请重新输入[/grey50]")

    model = _detect_model(base_url)

    lines = [
        f"API_BASE_URL={base_url}",
        f"API_KEY={api_key}",
        f"MODEL_NAME={model}",
    ]
    Path(".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[grey50]已写入 .env（模型: {model}），继续启动...[/grey50]")
    Config.load()


def _detect_model(base_url: str) -> str:
    url_lower = base_url.lower()
    if "deepseek" in url_lower:
        return "deepseek-chat"
    if "openai" in url_lower:
        return "gpt-4o"
    if "anthropic" in url_lower or "claude" in url_lower:
        return "claude"
    if "groq" in url_lower:
        return "llama"
    if "googleapis" in url_lower or "gemini" in url_lower:
        return "gemini"
    return "other"


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

    from character import HIT_DICE
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
        inventory=["旅行者服装", "背包", "水袋", "口粮x5"],
        gender=random.choice(["男", "女"]),
        age=random.choice(["少年", "青年", "壮年", "中年"]),
        gold=30,
    )
    _give_starter_items(char)
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
                val = IntPrompt.ask(f"{attr}")
                if val in remaining:
                    stats[attr] = val
                    remaining.remove(val)
                    break
                console.print(f"[grey50]请从 {remaining} 中选择[/grey50]")
            except:
                pass

    from character import HIT_DICE
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
        inventory=["旅行者服装", "背包", "水袋", "口粮x5"],
        gold=30,
    )
    _give_starter_items(char)
    return char


def _menu_choice(options: list, label: str) -> str:
    while True:
        try:
            choice = IntPrompt.ask(f"请选择{label}")
            if 1 <= choice <= len(options):
                return options[choice - 1]
        except:
            pass
        console.print("[grey50]无效选择[/grey50]")


def _give_starter_items(char: Character):
    gear = {
        "战士": ["长剑", "木盾"],
        "法师": ["法术书", "法杖"],
        "盗贼": ["匕首x2", "盗贼工具"],
        "牧师": ["钉头锤", "圣徽"],
        "圣骑士": ["长剑", "圣徽"],
        "游侠": ["长弓", "箭袋x20"],
        "德鲁伊": ["橡木法杖", "圣徽"],
        "术士": ["奥术法杖", "匕首"],
        "吟游诗人": ["鲁特琴", "匕首"],
        "武僧": ["木棍"],
        "野蛮人": ["巨斧"],
        "邪术师": ["法杖", "匕首"],
    }
    char.inventory.extend(gear.get(char.char_class, []))


# ---------- 输出解析和渲染 ----------

SECTION_ORDER = ["场景", "事件", "状态", "选择", "历史"]

SCENE_BASIC_FIELDS = {"地点", "时间", "温度"}


def parse_sections(text: str) -> dict:
    sections = {}
    pattern = r"\[(场景|场景细节|事件|状态|选择|历史|时间)\]\s*(.*?)(?=\[(?:场景|场景细节|事件|状态|选择|历史|时间)\]|\Z)"
    matches = re.findall(pattern, text, re.DOTALL)
    for name, content in matches:
        sections[name] = content.strip()

    # 兼容旧格式：合并[场景细节]到[场景]
    if "场景细节" in sections:
        if "场景" in sections:
            sections["场景"] += "\n" + sections["场景细节"]
        else:
            sections["场景"] = sections["场景细节"]
        del sections["场景细节"]

    if not sections and text.strip():
        sections["事件"] = text.strip()

    return sections


def _filter_scene_fields(text: str, basic_only: bool = True) -> str:
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if basic_only:
            key = line.split("：")[0].split(":")[0].strip()
            if key in SCENE_BASIC_FIELDS:
                lines.append(line)
        else:
            lines.append(line)
    if basic_only:
        return "    ".join(lines)
    return "\n".join(lines)


_round_counter = 0


def render_dm_output(full_text: str, gm=None, elapsed: float = 0):
    global _round_counter
    _round_counter += 1

    timing = f" [{elapsed:.1f}s]" if elapsed else ""
    console.rule(f"[grey50]第{_round_counter}轮{timing}[/grey50]", style="grey50")

    sections = parse_sections(full_text)

    # 保存选项映射（供上轮记录显示完整文本）
    if gm and "选择" in sections:
        mapping = {}
        for line in sections["选择"].strip().split("\n"):
            line = line.strip()
            m = re.match(r"^(\d+)[.)]\s*(.+)", line)
            if m:
                mapping[m.group(1)] = line
        gm.last_choices_map = mapping

    # 场景
    if "场景" in sections:
        scene_text = _filter_scene_fields(sections["场景"], basic_only=True)
        console.print(Panel(
            scene_text,
            title="[steel_blue]场景[/steel_blue]",
            border_style="steel_blue",
            box=box.SQUARE,
        ))
        if gm:
            gm.last_scene = sections["场景"]

    # 时间
    if gm and "时间" in sections:
        gm.last_time = sections["时间"]

    # 事件
    if "事件" in sections:
        console.print(Panel(
            Markdown(sections["事件"]),
            title="[#cc6b3e]事件[/#cc6b3e]",
            border_style="#cc6b3e",
            box=box.SQUARE,
        ))

    # 状态
    if "状态" in sections:
        status_text = sections["状态"]
        left = ""
        right = ""
        extras = []
        player_match = re.search(r"玩家\s*:\s*(.+)", status_text)
        target_match = re.search(r"目标\s*:\s*(.+)", status_text)
        other_matches = re.findall(r"其他\s*:\s*(.+)", status_text)
        if player_match:
            left = player_match.group(1).strip()
        if target_match:
            right = target_match.group(1).strip()
        extras = [m.strip() for m in other_matches if m.strip() and m.strip() != "无"]

        def style_target(t: str) -> tuple:
            hostility_colors = {
                "敌对": "indian_red",
                "中立": "#c4b08a",
                "友方": "light_sea_green",
            }
            for tag, color in hostility_colors.items():
                label = f"[{tag}]"
                if label in t:
                    return t.replace(label, "").strip(), color
            return t, "grey58"

        if right and right != "无":
            main_text, main_color = style_target(right)
            panels = [
                Panel(left, title="[grey58]玩家[/grey58]", border_style="grey58", box=box.SQUARE),
                Panel(main_text, title=f"[{main_color}]目标[/{main_color}]", border_style=main_color, box=box.SQUARE),
            ]
            for extra in extras:
                extra_text, extra_color = style_target(extra)
                panels.append(Panel(extra_text, title=f"[{extra_color}]其他[/{extra_color}]", border_style=extra_color, box=box.SQUARE))
            console.print(Columns(panels, equal=False, expand=False))
        else:
            console.print(Columns([Panel(left, title="[grey58]玩家[/grey58]", border_style="grey58", box=box.SQUARE)], equal=False, expand=False))

    # 行动
    if "选择" in sections:
        lines = sections["选择"].strip().split("\n")
        choice_text = ""
        for line in lines:
            line = line.strip()
            if re.match(r"^\d+[.)]", line):
                # 去掉"无需检定"类括号标记
                line = re.sub(r'[（(]\s*无需[^）)]*[）)]', '', line).strip()
                line_colored = re.sub(
                    r'([（(][^）)]*(?:(?:力量|敏捷|体质|智力|感知|魅力)|检定|击骰)[^）)]*[）)])',
                    r'[#5DCCCC]\1[/#5DCCCC]',
                    line,
                )
                choice_text += f"[#F9F1A5]{line_colored}[/#F9F1A5]\n"
            elif line:
                choice_text += f"{line}\n"
        if choice_text:
            console.print(Panel(choice_text.strip(), title="[dark_sea_green]行动[/dark_sea_green]", border_style="dark_sea_green", box=box.SQUARE))

    # 历史 - 由 game_loop 处理，不在 DM 输出中显示


# ---------- 存档/读档 ----------

def list_saves():
    saves = sorted(SAVE_DIR.glob("*.json"))
    if not saves:
        return []
    console.print("\n[bold]存档列表:[/bold]")
    for i, save in enumerate(saves, 1):
        size = save.stat().st_size
        console.print(f"  {i}. {save.stem} ({size}B)")
    return saves


def save_game(gm: GameMaster, name: str = None):
    if not name:
        name = gm.character.name
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    path = SAVE_DIR / f"{name}.json"
    path.write_text(json.dumps(gm.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[grey50]已保存: {path}[/grey50]")


def load_game(path: str) -> GameMaster:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    char = Character(**data["character"])
    gm = GameMaster(char)
    gm.set_history(data.get("history", []))
    if "last_scene" in data:
        gm.last_scene = data["last_scene"]
    if "last_scene_detail" in data:
        gm.last_scene_detail = data["last_scene_detail"]
    if "last_time" in data:
        gm.last_time = data["last_time"]
    console.print(f"[grey50]已加载: {Path(path).stem}[/grey50]")
    return gm


# ---------- 日志 ----------

def log_dm_response(round_num: int, player_input: str, response_text: str):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    import time as _time
    ts = _time.strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"round_{round_num:03d}_{ts}.txt"
    content = f">>> 玩家: {player_input}\n\n{response_text}\n"
    path.write_text(content, encoding="utf-8")


# ---------- 帮助 ----------

def show_help():
    console.print(f"\n[steel_blue]命令[/steel_blue]")
    console.print(f"  [grey82]数字[/grey82]    选择[选择]中的选项")
    console.print(f"  [grey82]文字[/grey82]    自由行动")
    console.print(f"  [grey82]/roll 表达式[/grey82]  投骰子，例：/roll d20+5、/roll 2d8+3")
    console.print(f"  [grey82]/roll 属性[/grey82]    属性检定，例：/roll 力量、/roll 敏捷 DC 15")
    console.print(f"  [grey82]/status[/grey82]  角色状态")
    console.print(f"  [grey82]/info[/grey82]    详细角色信息")
    console.print(f"  [grey82]/scene[/grey82]   详细场景信息")
    console.print(f"  [grey82]/equip[/grey82]    查看装备")
    console.print(f"  [grey82]/skill[/grey82]    查看技能")
    console.print(f"  [grey82]/time[/grey82]    查看当前时间")
    console.print(f"  [grey82]/save[/grey82]    保存")
    console.print(f"  [grey82]/load[/grey82]    读档")
    console.print(f"  [grey82]/new[/grey82]     新建角色")
    console.print(f"  [grey82]/help[/grey82]    帮助")
    console.print(f"  [grey82]/quit[/grey82]    退出")


def show_status(char: Character):
    from character import mod_str
    console.print(f"\n[steel_blue]{char.name}[/steel_blue]  Lv.{char.level} {char.race} {char.char_class}")
    console.print(f"[grey50]HP:[/grey50] {char.hp}/{char.max_hp}  [grey50]AC:[/grey50] {char.ac}  [grey50]熟练:[/grey50] {char.prof_bonus:+d}")
    console.print(f"[grey50]力:[/grey50]{mod_str(char.strength)} [grey50]敏:[/grey50]{mod_str(char.dexterity)} [grey50]体:[/grey50]{mod_str(char.constitution)} [grey50]智:[/grey50]{mod_str(char.intelligence)} [grey50]感:[/grey50]{mod_str(char.wisdom)} [grey50]魅:[/grey50]{mod_str(char.charisma)}")
    if char.inventory:
        console.print(f"[grey50]物品: {', '.join(char.inventory)}[/grey50]")


def show_info(char: Character):
    from character import mod_str
    console.print(Panel(
        f"名称: {char.name}\n"
        f"性别: {char.gender}  年龄: {char.age}\n"
        f"种族: {char.race}  职业: {char.char_class}  背景: {char.background}\n"
        f"等级: {char.level}  HP: {char.hp}/{char.max_hp}  AC: {char.ac}\n"
        f"熟练加值: {char.prof_bonus:+d}  金币: {char.gold}\n"
        f"力量: {char.strength}{mod_str(char.strength)}  "
        f"敏捷: {char.dexterity}{mod_str(char.dexterity)}  "
        f"体质: {char.constitution}{mod_str(char.constitution)}\n"
        f"智力: {char.intelligence}{mod_str(char.intelligence)}  "
        f"感知: {char.wisdom}{mod_str(char.wisdom)}  "
        f"魅力: {char.charisma}{mod_str(char.charisma)}\n"
        f"物品: {', '.join(char.inventory) if char.inventory else '无'}",
        title="[grey58]角色信息[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


def show_equip(char: Character):
    if not char.inventory:
        console.print("[grey50]无装备[/grey50]")
        return
    items = "\n".join(f"  • {item}" for item in char.inventory)
    console.print(Panel(
        items,
        title="[grey58]装备[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


def show_skills(char: Character):
    if not char.skills:
        console.print("[grey50]未习得技能[/grey50]")
        return
    from character import mod_str
    skill_lines = []
    for s in char.skills:
        skill_lines.append(f"  • {s}")
    console.print(Panel(
        "\n".join(skill_lines),
        title="[grey58]技能[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


def show_time(gm):
    text = gm.last_time if gm.last_time else "时间不详"
    console.print(Panel(
        text,
        title="[grey58]当前时间[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


# ---------- 投骰与检定 ----------

import random as dice_random


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
            console.print("冒险结束！")
            break
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
        elif cmd == "/new":
            if Prompt.ask(escape("确定新建？进度将丢失 [y/n]")) == "y":
                return "new_game"
            continue
        elif cmd == "/equip":
            show_equip(gm.character)
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

        # 记录上轮选择
        last_was_option = False
        if not cmd.startswith("/"):
            raw = player_input.strip()
            if raw in gm.last_choices_map:
                last_choice_record = gm.last_choices_map[raw]
                last_was_option = True
            else:
                last_choice_record = raw

        # 显示上轮选择记录
        if last_choice_record:
            record_display = last_choice_record
            if last_was_option:
                record_display = re.sub(
                    r'([（(][^）)]*(?:(?:力量|敏捷|体质|智力|感知|魅力)|检定|击骰)[^）)]*[）)])',
                    r'[#5DCCCC]\1[/#5DCCCC]',
                    record_display,
                )
                record_text = f"[#F9F1A5]{record_display}[/#F9F1A5]"
            else:
                record_text = record_display
            console.print(Panel(
                record_text,
                title="[#9b87c4]上轮记录[/#9b87c4]",
                border_style="#9b87c4",
                box=box.SQUARE,
            ))

        # 如果是纯数字，带上选择上下文给 AI
        if player_input.strip().isdigit():
            selected_num = player_input.strip()
            option_text = gm.last_choices_map.get(selected_num, "")
            check_info = parse_check_from_text(option_text) if option_text else None
            if check_info:
                ability_cn, ability_key, dc = check_info
                r, m, t, success = _interactive_check(gm.character, ability_cn, ability_key, dc)
                rw = "成功" if success else "失败"
                player_input = f"[选择选项{selected_num}] {option_text} | [检定] d20({r})+({m:+d})={t} {rw}"
            else:
                player_input = f"[选择选项{selected_num}] {option_text or selected_num}"

        # 发送给 DM
        try:
            response_parts = []
            import time as _time
            _t0 = _time.time()
            console.print("[grey50]DM 思考中...[/grey50]")
            for chunk in gm.send_message_stream(player_input):
                response_parts.append(chunk)
            _elapsed = _time.time() - _t0

            full = "".join(response_parts)

            log_dm_response(_round_counter + 1, player_input, full)

            if not gm.history:
                gm.set_history([])

            # 检查[状态]是否缺目标信息，缺则反问DM
            if gm.needs_repair(full):
                full = gm.repair_status(full)
                log_dm_response(_round_counter + 1, "（修复状态）", full)

            render_dm_output(full, gm, _elapsed)

        except KeyboardInterrupt:
            console.print("\n[grey50]中断[/grey50]")
        except Exception as e:
            console.print(f"[indian_red]错误: {e}[/indian_red]")


# ---------- 入口 ----------

def _show_round_recap(gm):
    """加载存档后展示上一轮的输出，让玩家知道当前进度"""
    global _round_counter
    assistant_msgs = [m for m in gm.history if m["role"] == "assistant"]
    if not assistant_msgs:
        return
    _round_counter = len(assistant_msgs) - 1
    last_response = assistant_msgs[-1]["content"]
    render_dm_output(last_response, gm)


def main():
    Config.load()
    check_config()

    console.print(Panel(
        "[bold]大模型地下城[/bold]\n"
        "一个由 AI 驱动的 D&D 5e 终端游戏",
        title="[steel_blue]LLM DND[/steel_blue]",
        border_style="steel_blue",
        box=box.SQUARE,
    ))

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    saves = list(SAVE_DIR.glob("*.json"))

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
        saves = list_saves()
        try:
            idx = int(Prompt.ask("选择编号")) - 1
            if 0 <= idx < len(saves):
                gm = load_game(str(saves[idx]))
                _show_round_recap(gm)
                game_loop(gm)
                return
        except ValueError:
            console.print("[grey50]请输入有效数字[/grey50]")
        except:
            pass

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
    gm = GameMaster(char, template_map[tpl])

    console.print("\n[grey62]冒险即将开始...[/grey62]")
    try:
        import time as _time2
        _t0 = _time2.time()
        parts = []
        for chunk in gm.send_message_stream("DM，请开始我的冒险吧！"):
            parts.append(chunk)
        _elapsed = _time2.time() - _t0
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
