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

theme = Theme({
    "prompt": "grey82",
    "prompt.default": "grey82",
    "prompt.choices": "grey50",
})
console = Console(theme=theme)

SECTION_ORDER = ["环境", "事件", "副事件", "状态", "选择", "历史"]
ENV_BASIC_FIELDS = {"地点", "时间", "温度"}
_round_counter = 0


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


def render_dm_output(full_text: str, gm=None, elapsed: float = 0, change_messages: list[str] | None = None, check_blocks: list[dict] | None = None):
    full_text = full_text.replace("（无需检定）", "")
    global _round_counter
    _round_counter += 1

    console.print()
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

    if "环境" in sections:
        scene_text = _filter_env_fields(sections["环境"], basic_only=True)
        console.print(Panel(
            scene_text,
            title="[steel_blue]环境[/steel_blue]",
            border_style="steel_blue",
            box=box.SQUARE,
        ))
        if gm:
            gm.last_scene = sections["环境"]

    if gm and "时间" in sections:
        gm.last_time = sections["时间"]

    if "事件" in sections:
        console.print(Panel(
            Markdown(sections["事件"]),
            title="[#cc6b3e]事件[/#cc6b3e]",
            border_style="#cc6b3e",
            box=box.SQUARE,
        ))

    if check_blocks:
        panels = [
            Panel(
                cb["text"],
                title="[#9b87c4]行动[/#9b87c4]",
                border_style="#9b87c4",
                box=box.SQUARE,
            )
            for cb in check_blocks if cb.get("text")
        ]
        if panels:
            console.print(Columns(panels, equal=False, expand=False))

    if "副事件" in sections:
        console.print(Panel(
            Markdown(sections["副事件"]),
            title="[#d4946b]事件[/#d4946b]",
            border_style="#d4946b",
            box=box.SQUARE,
        ))

    if change_messages:
        console.print(Panel(
            "\n".join(change_messages),
            title="[#d4a0a0]变更[/#d4a0a0]",
            border_style="#d4a0a0",
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
    console.print(f"\n[steel_blue]{char.name}[/steel_blue]  Lv.{char.level} {char.race_cn} {char.class_cn}")
    console.print(f"[grey50]{tr('general:hp')}:[/grey50] {char.hp}/{char.max_hp}  "
                  f"[grey50]{tr('general:ac')}:[/grey50] {char.ac}  "
                  f"[grey50]{tr('general:prof_bonus')}:[/grey50] {char.prof_bonus:+d}")
    console.print(Panel(
        "[grey50]增益:[/grey50] 无\n"
        "[grey50]减益:[/grey50] 无\n"
        "[grey50]状态:[/grey50] 正常\n"
        "[grey50]临时HP:[/grey50] 0",
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
        f"{tr('general:hp')}: {char.hp}/{char.max_hp}  "
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


def show_bag(char: Character):
    from loc import tr
    money = f"  {tr('general:money')}: {char.currency_str()}"
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
        _l("金钱"), f"[bold]{char.currency_str()}[/bold]",
    )

    header_parts = [hdr]
    if char.description:
        header_parts.append(f"{_l('描述')}  {char.description}")
    header = Group(*header_parts)

    stat_rows = []
    for cn, en in _STAT_KEYS:
        val = getattr(char, en)
        stat_rows.append(f"[{_MUTED}]{cn}[/{_MUTED}]  [bold]{val:>2}[/bold]  ({mod_str(val)})")

    skill_rows = [f"• {tr(f'skill:{s}')}" for s in char.skills]
    if not skill_rows:
        skill_rows = [f"[{_MUTED}]{tr('general:none')}[/{_MUTED}]"]

    save_str = "、".join(tr(f"skill:{s}") for s in char.saving_throws) or tr("general:none")
    feat_str = "、".join(strip_en_parens(f) for f in char.feats) if char.feats else tr("general:none")
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
