import re
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.columns import Columns
from rich.markup import escape
from rich.text import Text
from rich.theme import Theme
from rich import box

from config import Config
from character import Character, mod_str
from game_master import GameMaster, ABILITY_CN_TO_EN, parse_check_from_text

theme = Theme({
    "prompt": "grey82",
    "prompt.default": "grey82",
    "prompt.choices": "grey50",
})
console = Console(theme=theme)

SECTION_ORDER = ["场景", "事件", "状态", "选择", "历史"]
SCENE_BASIC_FIELDS = {"地点", "时间", "温度"}
_round_counter = 0


def set_round_counter(val: int):
    global _round_counter
    _round_counter = val


def get_round_counter() -> int:
    global _round_counter
    return _round_counter


def parse_sections(text: str) -> dict:
    sections = {}
    pattern = r"\[(场景|场景细节|事件|状态|选择|历史|时间)\]\s*(.*?)(?=\[(?:场景|场景细节|事件|状态|选择|历史|时间)\]|\Z)"
    matches = re.findall(pattern, text, re.DOTALL)
    for name, content in matches:
        sections[name] = content.strip()
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


def render_dm_output(full_text: str, gm=None, elapsed: float = 0):
    full_text = full_text.replace("（无需检定）", "")
    global _round_counter
    _round_counter += 1

    console.rule(f"─── [grey50]第{_round_counter}轮[/grey50]", style="grey50", align="left")

    sections = parse_sections(full_text)

    if gm and "选择" in sections:
        mapping = {}
        for line in sections["选择"].strip().split("\n"):
            line = line.strip()
            m = re.match(r"^(\d+)[.)]\s*(.+)", line)
            if m:
                mapping[m.group(1)] = line
        gm.last_choices_map = mapping

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

    if gm and "时间" in sections:
        gm.last_time = sections["时间"]

    if "事件" in sections:
        console.print(Panel(
            Markdown(sections["事件"]),
            title="[#cc6b3e]事件[/#cc6b3e]",
            border_style="#cc6b3e",
            box=box.SQUARE,
        ))

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

    if "选择" in sections:
        lines = sections["选择"].strip().split("\n")
        choice_text = ""
        for line in lines:
            line = line.strip()
            if re.match(r"^\d+[.)]", line):
                line = re.sub(r'[（(]\s*无需[^）)]*[）)]', '', line).strip()
                line_colored = re.sub(
                    r'([（(][^）)]*(?:(?:力量|敏捷|体质|智力|感知|魅力)|检定|击骰)[^）)]*[）)])',
                    r'[#5DCCCC]\1[/#5DCCCC]',
                    line,
                )
                m = re.match(r"^(\d+[.)])\s*(.*)", line_colored)
                if m:
                    choice_text += f"[white]{m.group(1)}[/white] [#F9F1A5]{m.group(2)}[/#F9F1A5]\n"
                else:
                    choice_text += f"[white]{line_colored}[/white]\n"
            elif line:
                choice_text += f"{line}\n"
        if choice_text:
            console.print(Panel(choice_text.strip(), title="[dark_sea_green]选择[/dark_sea_green]", border_style="dark_sea_green", box=box.SQUARE))


def show_help():
    console.print(f"\n[steel_blue]命令[/steel_blue]")
    console.print(f"  [grey82]数字[/grey82]    选择[选择]中的选项")
    console.print(f"  [grey82]文字[/grey82]    自由行动")
    console.print(f"  [grey82]/roll 表达式[/grey82]  投骰子，例：/roll d20+5、/roll 2d8+3")
    console.print(f"  [grey82]/roll 属性[/grey82]    属性检定，例：/roll 力量、/roll 敏捷 DC 15")
    console.print(f"  [grey82]/status[/grey82]  角色状态")
    console.print(f"  [grey82]/info[/grey82]    详细角色信息")
    console.print(f"  [grey82]/scene[/grey82]   详细场景信息")
    console.print(f"  [grey82]/equip[/grey82]    查看装备栏")
    console.print(f"  [grey82]/item[/grey82]     查看背包物品")
    console.print(f"  [grey82]/skill[/grey82]    查看技能")
    console.print(f"  [grey82]/time[/grey82]    查看当前时间")
    console.print(f"  [grey82]/save[/grey82]    保存")
    console.print(f"  [grey82]/load[/grey82]    读档")
    console.print(f"  [grey82]/new[/grey82]     新建角色")
    console.print(f"  [grey82]/help[/grey82]    帮助")
    console.print(f"  [grey82]/quit[/grey82]    退出")


def show_status(char: Character):
    console.print(f"\n[steel_blue]{char.name}[/steel_blue]  Lv.{char.level} {char.race} {char.char_class}")
    console.print(f"[grey50]HP:[/grey50] {char.hp}/{char.max_hp}  [grey50]AC:[/grey50] {char.ac}  [grey50]熟练:[/grey50] {char.prof_bonus:+d}")
    console.print(f"[grey50]力:[/grey50]{mod_str(char.strength)} [grey50]敏:[/grey50]{mod_str(char.dexterity)} [grey50]体:[/grey50]{mod_str(char.constitution)} [grey50]智:[/grey50]{mod_str(char.intelligence)} [grey50]感:[/grey50]{mod_str(char.wisdom)} [grey50]魅:[/grey50]{mod_str(char.charisma)}")
    if char.inventory:
        console.print(f"[grey50]物品: {', '.join(char.inventory)}[/grey50]")


def show_info(char: Character):
    console.print(Panel(
        f"名称: {char.name}\n"
        f"性别: {char.gender}  年龄: {char.age}\n"
        f"种族: {char.race}  职业: {char.char_class}  背景: {char.background}\n"
        f"等级: {char.level}  HP: {char.hp}/{char.max_hp}  AC: {char.ac}\n"
        f"熟练加值: {char.prof_bonus:+d}  金币: {char.currency_str()}\n"
        f"力量: {char.strength} ({mod_str(char.strength)})  "
        f"敏捷: {char.dexterity} ({mod_str(char.dexterity)})  "
        f"体质: {char.constitution} ({mod_str(char.constitution)})\n"
        f"智力: {char.intelligence} ({mod_str(char.intelligence)})  "
        f"感知: {char.wisdom} ({mod_str(char.wisdom)})  "
        f"魅力: {char.charisma} ({mod_str(char.charisma)})",
        title="[grey58]角色信息[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


def show_equip(char: Character):
    slots_lines = []
    for slot in ["武器", "副手", "头部", "身体", "背部", "项链", "戒指1", "戒指2"]:
        item = char.equipment.get(slot, "")
        if item:
            slots_lines.append(f"  {slot}: {item}")
        else:
            slots_lines.append(f"  [grey50]{slot}: 空[/grey50]")
    console.print(Panel(
        "\n".join(slots_lines),
        title="[grey58]装备[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


def show_inventory(char: Character):
    if not char.inventory:
        console.print("[grey50]背包为空[/grey50]")
        return
    items = "\n".join(f"  • {item}" for item in char.inventory)
    console.print(Panel(
        items,
        title="[grey58]背包[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


def show_item(char: Character):
    items = "\n".join(f"  • {item}" for item in char.inventory) if char.inventory else "  [grey50]空[/grey50]"
    console.print(Panel(
        items,
        title="[grey58]物品[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


def show_skills(char: Character):
    if not char.skills:
        console.print("[grey50]未习得技能[/grey50]")
        return
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
