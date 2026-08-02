import re
from pathlib import Path

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.columns import Columns
from rich.markup import escape
from rich.text import Text
from rich.theme import Theme
from rich.rule import Rule
from rich.table import Table
from rich import box

from core.config import Config
from core.character import Character, mod_str, strip_en_parens
from core.game_master import GameMaster, ABILITY_CN_TO_EN, parse_check_from_text
from resource.attitude import level

theme = Theme({
    "prompt": "grey82",
    "prompt.default": "grey82",
    "prompt.choices": "grey50",
})
console = Console(theme=theme)

SECTION_ORDER = ["环境", "事件", "副事件", "状态", "选择", "历史"]
ENV_BASIC_FIELDS = {"地点", "时间", "温度"}
_round_counter = 0

_HP_GREEN = "#6CB77A"      # API 连接成功的绿：满血
_HP_DSEAGREEN = "#8FBC8F"  # 选择块边框的暗海绿：血量不满（仍过半）
_HP_YELLOW = "#F9F1A5"     # 对话选项的黄：半血及以下
_HP_RED = "#E08E8E"        # 偏亮灰的红：仅剩 1 滴血
_HP_RE = re.compile(r"HP:\s*(\d+)/(\d+)")


def _hp_color(hp: int, max_hp: int) -> str:
    if hp <= 0:
        return "grey50"
    if hp == 1:
        return _HP_RED
    if hp * 2 <= max_hp:
        return _HP_YELLOW
    if hp >= max_hp:
        return _HP_GREEN
    return _HP_DSEAGREEN


def _hp_markup(hp: int, max_hp: int) -> str:
    color = _hp_color(hp, max_hp)
    return f"[{color}]{hp}[/{color}]"


def _hp_full_markup(hp: int, max_hp: int) -> str:
    return f"{_hp_markup(hp, max_hp)}[{_HP_GREEN}]/{max_hp}[/{_HP_GREEN}]"


def _colorize_hp_in_text(text: str) -> str:
    def repl(m):
        hp, max_hp = int(m.group(1)), int(m.group(2))
        return f"HP:{_hp_full_markup(hp, max_hp)}"
    return _HP_RE.sub(repl, text)


def set_round_counter(val: int):
    global _round_counter
    _round_counter = val


def get_round_counter() -> int:
    global _round_counter
    return _round_counter


def parse_sections(text: str) -> dict:
    sections = {}
    _SEC = "环境|场景|场景细节|事件|副事件|状态|选择|历史|时间"
    pattern = rf"\[({_SEC})\]\s*(.*?)(?=\[(?:{_SEC})\]|\Z)"
    matches = re.findall(pattern, text, re.DOTALL)
    for name, content in matches:
        if name == "副事件" and name in sections:
            sections[name] += "\n" + content.strip()
        else:
            sections[name] = content.strip()
    if "场景细节" in sections:
        if "场景" in sections:
            sections["场景"] += "\n" + sections["场景细节"]
        else:
            sections["场景"] = sections["场景细节"]
        del sections["场景细节"]
    if "场景" in sections:
        if "环境" in sections:
            sections["环境"] += "\n" + sections["场景"]
        else:
            sections["环境"] = sections["场景"]
        del sections["场景"]
    if not sections and text.strip():
        sections["事件"] = text.strip()
    return sections


def _filter_env_fields(text: str, basic_only: bool = True) -> str:
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if basic_only:
            key = line.split("：")[0].split(":")[0].strip()
            if key in ENV_BASIC_FIELDS:
                lines.append(line)
        else:
            lines.append(line)
    if basic_only:
        return "    ".join(lines)
    return "\n".join(lines)


def render_round_header(round_num: int, kind: str = ""):
    """回合头：=== 第 n 轮 · 战斗/非战斗 ===。由 GameRound 每轮调用一次，段内共享同一轮号。"""
    console.print()
    label = f"第{round_num}轮"
    if kind:
        color = "indian_red" if kind == "战斗" else "steel_blue"
        label += f" · [{color}]{kind}[/{color}]"
    console.rule(f"─── [grey50]{label}[/grey50]", style="grey50", align="left")


def render_env_block(env_text: str, gm=None):
    scene_text = _filter_env_fields(env_text, basic_only=True)
    console.print(Panel(
        scene_text,
        title="[steel_blue]环境[/steel_blue]",
        border_style="steel_blue",
        box=box.SQUARE,
    ))
    if gm:
        gm.last_scene = env_text


def render_event_block(event_text: str):
    console.print(Panel(
        Markdown(event_text),
        title="[#cc6b3e]事件[/#cc6b3e]",
        border_style="#cc6b3e",
        box=box.SQUARE,
    ))


def render_action_block(check_blocks: list[dict] | None):
    """行动块：每个全宽，不再一行多个。"""
    for cb in check_blocks or []:
        if cb.get("text"):
            console.print(Panel(
                cb["text"],
                title="[#E06C75]行动[/#E06C75]",
                border_style="#E06C75",
                box=box.SQUARE,
            ))


def render_narration_block(narration_text: str):
    """副事件块：内部与主事件区分，打印统一显示「事件」。"""
    console.print(Panel(
        Markdown(narration_text),
        title="[#d4946b]事件[/#d4946b]",
        border_style="#d4946b",
        box=box.SQUARE,
    ))


def render_change_block(change_messages: list[str] | None):
    if change_messages:
        console.print(Panel(
            "\n".join(change_messages),
            title="[#d4a0a0]变更[/#d4a0a0]",
            border_style="#d4a0a0",
            box=box.SQUARE,
        ))


def _hostility_color(attitude) -> str:
    from resource.attitude import level
    return {
        "hostile": "indian_red",
        "neutral": "#c4b08a",
        "friendly": "light_sea_green",
    }.get(level(attitude), "grey58")


def render_status_row(character, world_state=None, targets=None):
    """目标块：一排等宽块，玩家永远在最前，其后每个在场 NPC 一块（无目标则只有玩家块）。

    数据源为 WorldState（等级/生命值/AC/态度），不再依赖 DM 每段重写 [状态]。
    玩家昏迷/稳定/死亡有独立标记；NPC 倒地（HP 0）标灰[倒地]、即死标灰[死亡]。
    targets 可选覆盖：用于按先攻过滤当前在场目标。
    """
    from world.entity import NPC
    cond = character.condition_cn
    cond_color = "grey50" if character.dead else ("grey62" if character.unconscious else "grey50")
    player_panel_body = (
        f"[grey50]等级[/grey50] {character.level}  "
        f"[grey50]生命[/grey50] {_hp_full_markup(character.hp, character.max_hp)}  "
        f"[grey50]AC[/grey50] {character.ac}"
    )
    if character.unconscious or character.dead:
        player_panel_body += f"\n[grey50]状态[/grey50] [{cond_color}]{cond}[/{cond_color}]"
    panels = [
        Panel(
            player_panel_body,
            title=f"[grey58]{character.name}[/grey58]",
            border_style="grey58",
            box=box.SQUARE,
        )
    ]
    entities = targets if targets is not None else list(getattr(world_state, "active", {}).values() or [])
    for e in entities:
        if not isinstance(e, NPC):
            continue
        attitude = getattr(e, "attitude", 0)
        dead = bool(getattr(e, "dead", False))
        downed = not dead and getattr(e, "hp", 0) <= 0
        if dead:
            tag, color = "死亡", "grey50"
        elif downed:
            tag, color = "倒地", "grey50"
        else:
            color = _hostility_color(attitude)
            tag = None
        hp_text = _hp_full_markup(e.hp, e.max_hp)
        if tag:
            body = f"[{color}]{tag}[/{color}]  [grey50]生命[/grey50] {hp_text}  [grey50]AC[/grey50] {e.ac}"
        else:
            body = (
                f"[grey50]等级[/grey50] {e.level}  "
                f"[grey50]生命[/grey50] {hp_text}  [grey50]AC[/grey50] {e.ac}"
            )
        panels.append(Panel(
            body,
            title=f"[{color}]{e.name}[/{color}]",
            border_style=color,
            box=box.SQUARE,
        ))
    console.print(Columns(panels, equal=False, expand=False))


def render_death_save_block(text: str):
    """死亡豁免块：玩家回合起手的系统自动豁免结果。"""
    console.print(Panel(
        text,
        title="[indian_red]死亡豁免[/indian_red]",
        border_style="indian_red",
        box=box.SQUARE,
    ))


def render_death_block(name: str):
    """死亡结算块：死亡豁免 3 败或即死后的游戏结束提示。"""
    console.print(Panel(
        f"[bold indian_red]{name} 死亡了……[/bold indian_red]\n\n"
        "[grey62]冒险就此结束。你可以读档重来，或返回主菜单创建新角色。[/grey62]",
        title="[indian_red]死亡[/indian_red]",
        border_style="indian_red",
        box=box.SQUARE,
    ))


def render_choice_block(choice_text: str):
    lines = choice_text.strip().split("\n")
    out = ""
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
                out += f"[white]{m.group(1)}[/white] [#F9F1A5]{m.group(2)}[/#F9F1A5]\n"
            else:
                out += f"[white]{line_colored}[/white]\n"
        elif line:
            out += f"{line}\n"
    if out:
        console.print(Panel(out.strip(), title="[dark_sea_green]选择[/dark_sea_green]", border_style="dark_sea_green", box=box.SQUARE))


def render_decision_block(record_text: str):
    """决定块：仅记录玩家本轮选择，不给判定和结果（判定与结果在下轮事件块/行动块说明）。"""
    console.print(Panel(
        record_text,
        title="[#9b87c4]决定[/#9b87c4]",
        border_style="#9b87c4",
        box=box.SQUARE,
    ))


def render_dm_output(full_text: str, gm=None, elapsed: float = 0, change_messages: list[str] | None = None, check_blocks: list[dict] | None = None, round_num: int | None = None):
    """兼容入口：仍按旧顺序渲染整轮（非战斗回合用）。round_num 传入则不再自增。"""
    full_text = full_text.replace("（无需检定）", "")
    global _round_counter
    if round_num is None:
        _round_counter += 1
    else:
        _round_counter = round_num

    render_round_header(_round_counter)

    sections = parse_sections(full_text)

    if gm and "选择" in sections:
        mapping = {}
        for line in sections["选择"].strip().split("\n"):
            line = line.strip()
            m = re.match(r"^(\d+)[.)]\s*(.+)", line)
            if m:
                mapping[m.group(1)] = line
        gm.last_choices_map = mapping

    if "环境" in sections:
        render_env_block(sections["环境"], gm)

    if gm and "时间" in sections:
        gm.last_time = sections["时间"]

    if "事件" in sections:
        render_event_block(sections["事件"])

    render_action_block(check_blocks)

    if "副事件" in sections:
        render_narration_block(sections["副事件"])

    render_change_block(change_messages)

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
            cut = re.search(r",?\s*目标\s*:", left)
            if cut:
                left = left[:cut.start()].strip()
            left = _colorize_hp_in_text(left)
        if target_match:
            right = _colorize_hp_in_text(target_match.group(1).strip())
        extras = [_colorize_hp_in_text(m.strip()) for m in other_matches if m.strip() and m.strip() != "无"]

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
                panels.append(Panel(extra_text, title=f"[{extra_color}]目标[/{extra_color}]", border_style=extra_color, box=box.SQUARE))
            console.print(Columns(panels, equal=False, expand=False))
        elif extras:
            panels = [Panel(left, title="[grey58]玩家[/grey58]", border_style="grey58", box=box.SQUARE)]
            for extra in extras:
                extra_text, extra_color = style_target(extra)
                panels.append(Panel(extra_text, title=f"[{extra_color}]目标[/{extra_color}]", border_style=extra_color, box=box.SQUARE))
            console.print(Columns(panels, equal=False, expand=False))
        else:
            console.print(Columns([Panel(left, title="[grey58]玩家[/grey58]", border_style="grey58", box=box.SQUARE)], equal=False, expand=False))

    if "选择" in sections:
        render_choice_block(sections["选择"])


def show_help():
    console.print(f"\n[steel_blue]命令[/steel_blue]")
    console.print(f"  [grey82]数字[/grey82]    选择[选择]中的选项")
    console.print(f"  [grey82]文字[/grey82]    自由行动")
    console.print(f"  [grey82]/roll 表达式[/grey82]  投骰子，例：/roll d20+5、/roll 2d8+3")
    console.print(f"  [grey82]/roll 属性[/grey82]    属性检定，例：/roll 力量、/roll 敏捷 DC 15")
    console.print(f"  [grey82]/status[/grey82]  角色状态")
    console.print(f"  [grey82]/info[/grey82]    详细角色信息")
    console.print(f"  [grey82]/scene[/grey82]  详细环境信息")
    console.print(f"  [grey82]/equip[/grey82]    查看装备栏")
    console.print(f"  [grey82]/bag[/grey82]      查看背包与金钱")
    console.print(f"  [grey82]/skill[/grey82]    查看技能")
    console.print(f"  [grey82]/time[/grey82]    查看当前时间")
    console.print(f"  [grey82]/help[/grey82]    帮助")
    console.print(f"  [grey82]/save[/grey82]    保存")
    console.print(f"  [grey82]/load[/grey82]    读档")
    console.print(f"  [grey82]/menu[/grey82]    返回主菜单")
    console.print(f"  [grey82]/quit[/grey82]    退出")


def show_status(char: Character):
    from loc import tr
    cond = char.condition_cn
    cond_color = "indian_red" if char.dead else ("grey82" if char.unconscious else "green")
    console.print(f"\n[steel_blue]{char.name}[/steel_blue]  Lv.{char.level} {char.race_cn} {char.class_cn}")
    console.print(f"[grey50]{tr('general:hp')}:[/grey50] {_hp_full_markup(char.hp, char.max_hp)}  "
                  f"[grey50]{tr('general:ac')}:[/grey50] {char.ac}  "
                  f"[grey50]{tr('general:prof_bonus')}:[/grey50] {char.prof_bonus:+d}")
    console.print(Panel(
        "[grey50]增益:[/grey50] 无\n"
        "[grey50]减益:[/grey50] 无\n"
        f"[grey50]状态:[/grey50] [{cond_color}]{cond}[/{cond_color}]"
        + (f"  [grey50]死亡豁免[/grey50] 失败 {char.death_fails}/3 · 成功 {char.death_successes}/3" if char.unconscious else "")
        + "\n[grey50]临时HP:[/grey50] 0",
        title="[steel_blue]" + tr("general:status_title") + "[/steel_blue]",
        border_style="steel_blue",
        box=box.SQUARE,
    ))


def show_info(char: Character):
    from loc import tr
    gender_cn = tr(f"gender:{char.gender}")
    race_cn = char.race_cn
    class_cn = char.class_cn
    bg_cn = char.bg_cn
    console.print(Panel(
        f"{tr('general:name')}: {char.name}\n"
        f"{tr('general:gender')}: {gender_cn}  {tr('general:age')}: {char.age}\n"
        f"{tr('general:race')}: {race_cn}  {tr('general:class')}: {class_cn}  "
        f"{tr('general:bg')}: {bg_cn}\n"
        f"{tr('general:level')}: {char.level}  "
        f"{tr('general:hp')}: {_hp_full_markup(char.hp, char.max_hp)}  "
        f"{tr('general:ac')}: {char.ac}\n"
        f"{tr('general:prof_bonus')}: {char.prof_bonus:+d}\n"
        f"{tr('stat:strength')}: {char.strength} ({mod_str(char.strength)})  "
        f"{tr('stat:dexterity')}: {char.dexterity} ({mod_str(char.dexterity)})  "
        f"{tr('stat:constitution')}: {char.constitution} ({mod_str(char.constitution)})\n"
        f"{tr('stat:intelligence')}: {char.intelligence} ({mod_str(char.intelligence)})  "
        f"{tr('stat:wisdom')}: {char.wisdom} ({mod_str(char.wisdom)})  "
        f"{tr('stat:charisma')}: {char.charisma} ({mod_str(char.charisma)})",
        title="[grey58]" + tr("general:info_title") + "[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


def _bag_summary(char: Character) -> list[str]:
    """把背包实例按 guid 合并叠放显示：箭矢 x20（数据层仍为独立实例）。"""
    from resource.item_db import item_db
    counts: dict[str, int] = {}
    for inst in char.inventory.all_instances():
        counts[inst.guid] = counts.get(inst.guid, 0) + 1
    lines = []
    for guid, n in counts.items():
        item_def = item_db.get(guid)
        name = item_def.name if item_def else guid
        lines.append(f"• {name}" + (f" x{n}" if n > 1 else ""))
    return lines


def _currency_rich(cur) -> str:
    """金钱富文本：前导连续为 0 的单位数字用灰色（grey50，与背包空位同色）。"""
    leading = True
    parts = []
    for value, unit in ((cur.gold, "金"), (cur.silver, "银"), (cur.copper_display, "铜")):
        if value == 0 and leading:
            parts.append(f"[grey50]0[/grey50]{unit}")
        else:
            parts.append(f"{value}{unit}")
            leading = False
    return " ".join(parts)


def show_bag(char: Character):
    from loc import tr
    money = f"  {tr('general:money')}: {_currency_rich(char.inventory.currency)}"
    lines = _bag_summary(char)
    if lines:
        items = "\n".join(lines)
    else:
        items = "  [grey50]" + tr("general:empty") + "[/grey50]"
    console.print(Panel(
        f"{money}\n\n{items}",
        title="[grey58]" + tr("general:bag") + "[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


def show_equip(char: Character):
    from loc import tr
    from resource.item_db import item_db
    lines = []
    for slot_key in ["weapon", "off_hand", "head", "body", "back", "neck", "ring1", "ring2"]:
        slot_cn = tr(f"slot:{slot_key}")
        guid = char.inventory.equipped.get(slot_key)
        if guid:
            item_def = item_db.get(guid)
            name = item_def.name if item_def else guid
        else:
            name = f"[grey50]{tr('general:empty')}[/grey50]"
        lines.append(f"  {slot_cn}: {name}")
    console.print(Panel(
        "\n".join(lines),
        title="[grey58]" + tr("general:equip") + "[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


def show_skills(char: Character):
    from loc import tr
    if not char.skills:
        console.print("[grey50]" + tr("general:no_skill") + "[/grey50]")
        return
    skill_lines = []
    for s in char.skills:
        if hasattr(s, "name_en") and s.name_en:
            cn = s.name
        else:
            cn = tr(f"skill:{s}")
        skill_lines.append(f"  • {cn}")
    console.print(Panel(
        "\n".join(skill_lines),
        title="[grey58]" + tr("general:skill") + "[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))


_STAT_KEYS = [
    ("力量", "strength"), ("敏捷", "dexterity"), ("体质", "constitution"),
    ("智力", "intelligence"), ("感知", "wisdom"), ("魅力", "charisma"),
]
_SLOT_KEYS = ["weapon", "off_hand", "head", "body", "back", "neck", "ring1", "ring2"]

_CARD_BORDER = "#60a5fa"
_CARD_TITLE = "#93c5fd"
_BLOCK_BORDER = "#64748b"
_BLOCK_TITLE = "#cbd5e1"
_ACCENT = "#fbbf24"
_MUTED = "grey62"


def _sheet_block(title: str, body, width: int = None, height: int = None) -> Panel:
    return Panel(
        body,
        title=f"[bold {_BLOCK_TITLE}]{title}[/bold {_BLOCK_TITLE}]",
        border_style=_BLOCK_BORDER,
        box=box.SQUARE,
        padding=(0, 1),
        width=width,
        height=height,
    )


def _measure_h(renderable, width: int) -> int:
    """测量一个 renderable 在指定宽度下占多少终端行。"""
    import io as _io
    from rich.console import Console as _MeasureConsole
    buf = _io.StringIO()
    _MeasureConsole(width=width, file=buf, color_system=None, force_terminal=False).print(renderable)
    return len(buf.getvalue().splitlines())


def _row_grid(blocks: list, widths: list, gap: int = 1) -> Table:
    """同行若干子块：先按各自宽度测高，取最大值强制等高，再排成对齐网格。"""
    measured = [_measure_h(_sheet_block(t, b, width=w), w) for (t, b), w in zip(blocks, widths)]
    target = max(measured)
    grid = Table.grid(padding=(0, gap))
    for w in widths:
        grid.add_column(width=w)
    grid.add_row(*[_sheet_block(t, b, width=w, height=target) for (t, b), w in zip(blocks, widths)])
    return grid


def render_character_sheet(char: Character, roll_log: str = ""):
    """统一角色卡：一块大卡包裹 /info + /equip + /bag + /skill 全部子块（创建角色预览用）。"""
    from loc import tr
    from resource.item_db import item_db

    lineage = f"（{char.lineage_cn}）" if char.lineage else ""
    gender_cn = tr(f"gender:{char.gender}")
    _l = lambda t: f"[{_MUTED}]{t}[/{_MUTED}]"

    # ── 头部：名称/等级/职业等 逐项带标签分行 ──
    hdr = Table.grid(expand=True, padding=(0, 1))
    hdr.add_column(width=6)
    hdr.add_column(min_width=6)
    hdr.add_column(width=6)
    hdr.add_column(min_width=6)
    hdr.add_column(width=10)
    hdr.add_column(min_width=8)
    hdr.add_row(
        _l("名称"), f"[bold {_ACCENT}]{char.name}[/bold {_ACCENT}]",
        _l("种族"), f"[bold]{char.race_cn}{lineage}[/bold]",
        _l("背景"), f"[bold]{char.bg_cn}[/bold]",
    )
    hdr.add_row(
        _l("职业"), f"[bold]{char.class_cn}[/bold]",
        _l("性别"), f"[bold]{gender_cn}[/bold]",
        _l("年龄"), f"[bold]{char.age}[/bold]",
    )
    hdr.add_row(
        _l("等级"), f"[bold]{char.level}[/bold]",
        _l("HP"), f"[bold]{char.hp}/{char.max_hp}[/bold]",
        _l("AC"), f"[bold]{char.ac}[/bold]",
    )
    hdr.add_row(
        _l(""), "",
        _l("熟练加值"), f"[bold]{char.prof_bonus:+d}[/bold]",
        _l("金钱"), f"[bold]{_currency_rich(char.inventory.currency)}[/bold]",
    )

    header_parts = [hdr]
    if char.description:
        header_parts.append(f"{_l('描述')}  {char.description}")
    header = Group(*header_parts)

    stat_rows = []
    for cn, en in _STAT_KEYS:
        val = getattr(char, en)
        stat_rows.append(f"[{_MUTED}]{cn}[/{_MUTED}]  [bold]{val:>2}[/bold]  ({mod_str(val)})")

    skill_rows = []
    for s in char.skills:
        if hasattr(s, "name_en") and s.name_en:
            skill_rows.append(f"• {s.name}")
        else:
            skill_rows.append(f"• {tr(f'skill:{s}')}")
    if not skill_rows:
        skill_rows = [f"[{_MUTED}]{tr('general:none')}[/{_MUTED}]"]

    save_str = "、".join(tr(f"skill:{s}") for s in char.saving_throws) or tr("general:none")
    feat_str = "、".join(strip_en_parens(f.name if hasattr(f, "name") else f) for f in char.feats) if char.feats else tr("general:none")
    bonus_rows = [
        f"[{_MUTED}]{tr('general:save')}[/{_MUTED}]  {save_str}",
        f"[{_MUTED}]{tr('general:feats')}[/{_MUTED}]  {feat_str}",
        f"[{_MUTED}]{tr('general:traits')}[/{_MUTED}]",
    ]
    trait_lines = []
    for line in char.species_trait_lines():
        trait_lines += [t.strip() for t in line.split("；") if t.strip()]
    trait_grid = None
    if trait_lines:
        trait_grid = Table.grid(padding=(0, 1))
        trait_grid.add_column("b", width=1)
        trait_grid.add_column("t")
        for t in trait_lines:
            trait_grid.add_row("•", t)
    else:
        bonus_rows.append(f"  [{_MUTED}]{tr('general:none')}[/{_MUTED}]")
    bonus_body = Group("\n".join(bonus_rows), trait_grid) if trait_grid else "\n".join(bonus_rows)

    equip_grid = Table.grid(padding=(0, 2))
    equip_grid.add_column("slot")
    equip_grid.add_column("item")
    for slot_key in _SLOT_KEYS:
        guid = char.inventory.equipped.get(slot_key)
        item_def = item_db.get(guid) if guid else None
        slot_cn = tr(f"slot:{slot_key}")
        if item_def:
            equip_grid.add_row(f"[{_MUTED}]{slot_cn}[/{_MUTED}]", f"[bold]{item_def.name}[/bold]")
        else:
            equip_grid.add_row(f"[{_MUTED}]{slot_cn}[/{_MUTED}]", f"[{_MUTED}]{tr('general:empty')}[/{_MUTED}]")

    bag_rows = _bag_summary(char)
    if not bag_rows:
        bag_rows = [f"[{_MUTED}]{tr('general:empty')}[/{_MUTED}]"]

    # ── 布局：定宽卡片，同行块强制等高 ──
    card_w = min(console.width - 2, 112)
    inner_w = card_w - 4

    base1 = (inner_w - 6) // 7
    widths1 = [base1 * 2, base1 * 2, inner_w - 6 - base1 * 4]
    row1 = _row_grid(
        [
            ("属性", "\n".join(stat_rows)),
            (tr("general:skill"), "\n".join(skill_rows)),
            ("豁免 / 专长 / 特性", bonus_body),
        ],
        widths1,
    )

    base2 = (inner_w - 4) // 2
    widths2 = [base2, inner_w - 4 - base2]
    row2 = _row_grid(
        [
            (tr("general:equip"), equip_grid),
            (tr("general:bag"), "\n".join(bag_rows)),
        ],
        widths2,
    )

    inner = Group(header, Rule(style="#3f4a5a"), row1, row2)
    if roll_log:
        inner = Group(header, Rule(style="#3f4a5a"), row1, row2, f"  [{_MUTED}]↳ {roll_log}[/{_MUTED}]")

    card = Panel(
        inner,
        title=f"[bold {_CARD_TITLE}]角色卡[/bold {_CARD_TITLE}]",
        border_style=_CARD_BORDER,
        box=box.SQUARE,
        padding=(1, 1),
        width=card_w,
    )
    console.print()
    console.print(card)


def show_time(gm):
    text = gm.last_time if gm.last_time else "时间不详"
    console.print(Panel(
        text,
        title="[grey58]当前时间[/grey58]",
        border_style="grey58",
        box=box.SQUARE,
    ))
