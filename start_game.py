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
from character import Character, RACES, CLASSES, BACKGROUNDS, ARMOR_BY_CLASS, Combatant
from game_master import GameMaster

theme = Theme({
    "prompt": "grey82",
    "prompt.default": "grey82",
    "prompt.choices": "grey50",
})
console = Console(theme=theme)
SAVE_DIR = Path("./saves")


# ---------- 配置检查 ----------

def check_config():
    if Config.is_ready():
        return
    console.print("\n[steel_blue]欢迎来到大模型地下城！[/steel_blue]")
    console.print("\n[indian_red]错误: 缺少 API 配置[/indian_red]")
    console.print("\n请将 [bold].env.example[/bold] 复制为 [bold].env[/bold]，填入以下内容后重新运行：\n")
    console.print("  API_BASE_URL=https://api.deepseek.com")
    console.print("  API_KEY=sk-你的密钥")
    console.print("  MODEL_NAME=deepseek-v4-flash")
    console.print("\n或用其它兼容 OpenAI API 的服务，修改对应值即可。")
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
    name = Prompt.ask("角色名称", default="无名冒险者")
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


def parse_sections(text: str) -> dict:
    sections = {}
    pattern = r"\[(场景|事件|状态|选择|历史)\]\s*(.*?)(?=\[.*?\]|\Z)"
    matches = re.findall(pattern, text, re.DOTALL)
    for name, content in matches:
        sections[name] = content.strip()

    # 如果没有任何匹配但文本不为空，全当成事件显示
    if not sections and text.strip():
        sections["事件"] = text.strip()

    return sections


_round_counter = 0


def render_dm_output(full_text: str, elapsed: float = 0):
    global _round_counter
    _round_counter += 1

    timing = f" [{elapsed:.1f}s]" if elapsed else ""
    console.print(f"[grey50]━━━ 第{_round_counter}轮{timing} ━━━[/grey50]")

    sections = parse_sections(full_text)

    # 场景
    if "场景" in sections:
        console.print(Panel(
            sections["场景"],
            title="[dark_cyan]场景[/dark_cyan]",
            border_style="dark_cyan",
            box=box.SQUARE,
        ))

    # 事件
    if "事件" in sections:
        console.print(Panel(
            Markdown(sections["事件"]),
            title="[steel_blue]事件[/steel_blue]",
            border_style="steel_blue",
            box=box.SQUARE,
        ))

    # 状态
    if "状态" in sections:
        status_text = sections["状态"]
        left = right = ""
        if "|" in status_text:
            parts = status_text.split("|", 1)
            left = parts[0].strip()
            right = parts[1].strip()
        else:
            left = status_text

        if right:
            left_p = Panel(left, title="[grey58]玩家[/grey58]", border_style="grey58", box=box.SQUARE)
            right_p = Panel(right, title="[grey58]目标[/grey58]", border_style="grey58", box=box.SQUARE)
            console.print(Columns([left_p, right_p]))
        else:
            console.print(Panel(left, title="[grey58]状态[/grey58]", border_style="grey58", box=box.SQUARE))

    # 选择
    if "选择" in sections:
        lines = sections["选择"].strip().split("\n")
        choice_text = ""
        for line in lines:
            line = line.strip()
            if re.match(r"^\d+[.)]", line):
                choice_text += f"[dark_sea_green]{line}[/dark_sea_green]\n"
            elif line:
                choice_text += f"{line}\n"
        if choice_text:
            console.print(Panel(choice_text.strip(), title="[dark_sea_green]选择[/dark_sea_green]", border_style="dark_sea_green", box=box.SQUARE))

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
    console.print(f"[grey50]已加载: {Path(path).stem}[/grey50]")
    return gm


# ---------- 帮助 ----------

def show_help():
    console.print(f"\n[steel_blue]命令[/steel_blue]")
    console.print(f"  [grey82]数字[/grey82]    选择[选择]中的选项")
    console.print(f"  [grey82]文字[/grey82]    自由行动")
    console.print(f"  [grey82]/roll d20+5[/grey82]  投骰子")
    console.print(f"  [grey82]/status[/grey82]  角色状态")
    console.print(f"  [grey82]/info[/grey82]    详细角色信息")
    console.print(f"  [grey82]/scene[/grey82]   详细场景信息")
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
        title="[steel_blue]角色信息[/steel_blue]",
        border_style="steel_blue",
        box=box.SQUARE,
    ))


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
        elif cmd == "/help":
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
                console.print(Panel(
                    gm.last_scene,
                    title="[steel_blue]详细场景信息[/steel_blue]",
                    border_style="steel_blue",
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
                idx = IntPrompt.ask("选择编号") - 1
                if 0 <= idx < len(saves):
                    gm = load_game(str(saves[idx]))
                    show_status(gm.character)
            except:
                console.print("[grey50]无效选择[/grey50]")
            continue
        elif cmd == "/new":
            if Prompt.ask(escape("确定新建？进度将丢失 [y/n]")) == "y":
                return "new_game"
            continue

        # 记录上轮选择
        if not cmd.startswith("/"):
            last_choice_record = player_input.strip()

        # 如果是纯数字，带上选择上下文给 AI
        if player_input.strip().isdigit():
            player_input = f"[选择选项{player_input.strip()}] {player_input.strip()}"

        # 显示上轮选择记录
        if last_choice_record:
            console.print(Panel(
                last_choice_record,
                title="[grey54]上轮记录[/grey54]",
                border_style="grey54",
                box=box.SQUARE,
            ))

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

            if not gm.history:
                gm.set_history([])

            # 保存场景信息供 /scene 使用
            sections = parse_sections(full)
            if "场景" in sections:
                gm.last_scene = sections["场景"]

            render_dm_output(full, _elapsed)

        except KeyboardInterrupt:
            console.print("\n[grey50]中断[/grey50]")
        except Exception as e:
            console.print(f"[indian_red]错误: {e}[/indian_red]")


# ---------- 入口 ----------

def main():
    Config.load()
    check_config()

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    saves = list(SAVE_DIR.glob("*.json"))

    if saves:
        console.print("[grey62]检测到存档[/grey62]")
        console.print("1. 继续冒险")
        console.print("2. 创建新角色")
        choice = Prompt.ask(escape("选择 [1/2]"))
        if not choice or choice == "1":
            saves = list_saves()
            try:
                idx = IntPrompt.ask("选择编号") - 1
                if 0 <= idx < len(saves):
                    gm = load_game(str(saves[idx]))
                    game_loop(gm)
                    return
            except:
                pass

    char = create_character()
    gm = GameMaster(char)

    console.print("\n[grey62]冒险即将开始...[/grey62]")
    try:
        parts = []
        for chunk in gm.send_message_stream("DM，请开始我的冒险吧！"):
            parts.append(chunk)
        render_dm_output("".join(parts))
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
