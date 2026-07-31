import re
import sys
import time as _time
from pathlib import Path

from rich.panel import Panel
from rich.prompt import Prompt
from rich.markup import escape
from rich import box

from core.config import Config
from core.character import Character, RACES, CLASSES, BACKGROUNDS, HIT_DICE
from rules.srd_data import (
    find_species, find_class, find_background,
)
from core.game_master import GameMaster
from core.ui import console, render_dm_output, render_character_sheet
from core import char_gen
from core.game_loop import (
    game_loop, save_game, load_game, log_dm_response,
    list_saves, SAVE_DIR, LOG_DIR, _show_round_recap,
)
from core.world_bg import list_world_backgrounds, load_world_background
from core.opening_templates import list_opening_templates


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
        console.print("[#6CB77A]API 连接成功[/#6CB77A]")
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
        name = _ask_quick_name()
        while True:
            console.print("\n[grey50]正在随机生成角色...[/grey50]")
            char, roll_log = char_gen.roll_character(name=name)
            _init_equipment(char)
            result = _confirm_character(char, roll_log=roll_log)
            if result == "yes":
                break
            if result == "cancel":
                return None
        _offer_save_template(char)
        return char

    while True:
        char = _detailed_character()
        result = _confirm_character(char)
        if result == "yes":
            break
        if result == "cancel":
            return None
    _offer_save_template(char)
    return char


def _ask_quick_name() -> str:
    name = Prompt.ask("角色名称（留空回车随机）")
    if not name:
        confirm = Prompt.ask("是否随机生成名字？（再次回车确认随机，或直接输入名字）")
        name = char_gen.random_name() if not confirm else confirm
    return name


def _confirm_character(char: Character, roll_log: str = "") -> str:
    """统一预览确认：渲染角色卡并请求采用。
    返回 'yes'（采用）/ 'reroll'（重新生成/重新创建）/ 'cancel'（取消）。"""
    while True:
        render_character_sheet(char, roll_log)
        choice = Prompt.ask(escape("采用？ [1]确认 [2]重新生成 [3]取消"))
        if choice in ("1", "y", "yes", ""):
            return "yes"
        if choice in ("2", "n", "no"):
            return "reroll"
        if choice in ("3", "q", "quit", "c"):
            return "cancel"


def _equipment_choice(label: str, a_items: list, b_gp: int) -> bool:
    """选择装备包(A) 或 金币(B)。返回 True=A 装备包。"""
    console.print(f"\n[bold]选择 {label} 起始装备[/bold]")
    console.print(f"  1. 装备包: {'、'.join(a_items)}")
    console.print(f"  2. 换成 {b_gp} 金币")
    pick = Prompt.ask(escape("选择 [1/2]"))
    return pick != "2"


def _offer_save_template(char: Character):
    ans = Prompt.ask(escape(f"是否将「{char.name}」保存为角色模板？ [1]不保存 [2]保存"))
    if ans not in ("2", "y", "yes"):
        return
    from core.templates import save_template
    path = save_template(char)
    console.print(f"[grey50]角色模板已保存: {path.name}[/grey50]")


def _offer_template_import() -> Character:
    """检测本地角色模板，询问是否导入。返回 Character 或 None。"""
    from core.templates import list_templates, load_template
    stems = list_templates()
    if not stems:
        return None
    console.print(f"\n[steel_blue]检测到角色模板 {len(stems)} 个[/steel_blue]")
    ans = Prompt.ask(escape("是否导入模板开始新冒险？ [1]否 [2]是"))
    if ans not in ("2", "y", "yes"):
        return None
    for i, s in enumerate(stems, 1):
        console.print(f"  {i}. {s}")
    try:
        idx = int(Prompt.ask(escape(f"选择编号 [1-{len(stems)}]"))) - 1
        if 0 <= idx < len(stems):
            char = load_template(stems[idx])
            console.print(f"[grey50]已导入: {char.name}[/grey50]")
            render_character_sheet(char)
            return char
    except (ValueError, IndexError):
        pass
    console.print("[grey50]导入取消[/grey50]")
    return None


def _create_world() -> GameMaster:
    """世界启动入口：三种创建世界的方式，当前仅方式一可用。"""
    from resource.packs import RESOURCE_MODE_PACK, RESOURCE_MODE_FREE, configure_resource_catalogs
    while True:
        console.print("\n[steel_blue]创建世界[/steel_blue]")
        console.print("1. 让大模型创建世界（世界背景 + 开场模板 + 对象资源策略）")
        console.print("2. 选择故事包（规划中）")
        console.print("3. 程序化生成世界（规划中）")
        choice = Prompt.ask(escape("选择 [1/2/3]"))
        if choice == "2":
            console.print("[grey50]方式二（选择故事包）尚未开放，敬请期待[/grey50]")
            continue
        if choice == "3":
            console.print("[grey50]方式三（程序化生成世界）尚未开放，敬请期待[/grey50]")
            continue

        # ── 方式一：选择世界背景 ──
        bg_list = list_world_backgrounds()
        console.print("\n[steel_blue]选择世界背景[/steel_blue]")
        if bg_list:
            for i, (display, stem) in enumerate(bg_list, 1):
                console.print(f"  {i}. {display}")
            bg_choice = Prompt.ask(escape(f"选择 [1-{len(bg_list)}]"))
            try:
                idx = int(bg_choice) - 1
                setting_stem = bg_list[idx][1] if 0 <= idx < len(bg_list) else bg_list[0][1]
            except (ValueError, IndexError):
                setting_stem = bg_list[0][1]
        else:
            setting_stem = "default-dnd"
        setting_content = load_world_background(setting_stem)

        # ── 对象资源策略（互斥：查表创建 或 填表创建）──
        console.print("\n[steel_blue]选择对象资源策略[/steel_blue]")
        console.print("1. 查表创建（使用默认资源包，所有对象从资源库检索）")
        console.print("2. 填表创建（不使用任何资源包，大模型按表单自由创建一切对象）")
        mode_choice = Prompt.ask(escape("选择 [1/2]"))
        resource_mode = RESOURCE_MODE_PACK if mode_choice != "2" else RESOURCE_MODE_FREE
        configure_resource_catalogs(resource_mode)
        if resource_mode == RESOURCE_MODE_FREE:
            console.print("[grey50]已启用填表创建：不使用任何资源包，对象将按表单创建并随存档保存。[/grey50]")

        char = _offer_template_import()
        if char is None:
            char = create_character()
        while char is None:
            console.print("\n[grey50]角色未创建，请重新创建[/grey50]")
            char = create_character()

        console.print("\n[steel_blue]选择开场模板[/steel_blue]")
        tpl_list = list_opening_templates()
        console.print("  1. 随机世界（无开场模板，完全随机生成）")
        for i, (display, stem) in enumerate(tpl_list, 1):
            console.print(f"  {i + 1}. {display}")
        tpl = Prompt.ask(escape(f"选择 [1-{len(tpl_list) + 1}]"))
        try:
            idx = int(tpl) - 2
            opening_stem = tpl_list[idx][1] if 0 <= idx < len(tpl_list) else ""
        except (ValueError, IndexError):
            opening_stem = ""

        return GameMaster(
            char, opening_stem,
            setting_content=setting_content, setting_stem=setting_stem,
            resource_mode=resource_mode,
        )


def _choose_lineage(species_name_cn: str) -> str:
    sp = find_species(species_name_cn)
    if not sp or not sp.lineages:
        return ""
    console.print(f"\n[bold]选择 {species_name_cn} 的流派:[/bold]")
    for i, lin in enumerate(sp.lineages, 1):
        console.print(f"  {i}. {lin.name}")
        for t in lin.traits:
            console.print(f"     - {t}")
    lin = _menu_choice([l.name for l in sp.lineages], "流派")
    for l in sp.lineages:
        if l.name == lin:
            return l.name_en or l.name
    return lin


def _choose_skills(prompt_label: str, options_cn: list, count: int, already_chosen_cn: list = None) -> list:
    """从 options_cn 中新增挑选 count 项（不计 already_chosen_cn），返回 已有+新增 的英文技能 key 列表。"""
    from rules.srd_data import SKILL_BY_EN
    base = list(already_chosen_cn) if already_chosen_cn else []
    available = [s for s in options_cn if s not in base]
    picked = []
    while len(picked) < count and available:
        console.print(f"\n[bold]{prompt_label}（还需选 {count - len(picked)} 项）[/bold]")
        for i, s in enumerate(available, 1):
            console.print(f"  {i}. {s}")
        pick = _menu_choice(available, "技能")
        picked.append(pick)
        available.remove(pick)
    return [SKILL_BY_EN.get(s, s) for s in base + picked]


def _detailed_character() -> Character:
    name = Prompt.ask("角色名称")

    from rules.srd_data import SKILL_BY_EN

    console.print("\n[bold]选择种族:[/bold]")
    for i, s in enumerate(RACES, 1):
        sp = find_species(s)
        info = f"  {i}. {s}（速度{sp.speed}尺，{'/'.join(sp.size_options)}）" if sp else f"  {i}. {s}"
        console.print(info)
    race_cn = _menu_choice(RACES, "种族")
    sp = find_species(race_cn)
    race_en = sp.name_en if sp else race_cn
    lineage = _choose_lineage(race_cn)

    console.print("\n[bold]选择背景:[/bold]")
    for i, bg_name in enumerate(BACKGROUNDS, 1):
        bg = find_background(bg_name)
        if bg:
            console.print(f"  {i}. {bg_name}（专长: {bg.feat}，技能: {'/'.join(bg.skill_proficiencies)}）")
    bg_cn = _menu_choice(BACKGROUNDS, "背景")
    bg_data = find_background(bg_cn)
    bg_en = bg_data.name_en if bg_data else bg_cn

    console.print("\n[bold]选择职业:[/bold]")
    for i, cn in enumerate(CLASSES, 1):
        cd = find_class(cn)
        if cd:
            console.print(f"  {i}. {cn}（生命骰d{cd.hit_die}，豁免: {'/'.join(cd.saving_throws)}）")
    class_cn = _menu_choice(CLASSES, "职业")
    cd = find_class(class_cn)
    class_en = cd.name_en if cd else class_cn

    console.print("\n[bold]选择性别:[/bold]")
    console.print("  1. 男")
    console.print("  2. 女")
    gender_cn = _menu_choice(["男", "女"], "性别")
    gender = "male" if gender_cn == "男" else "female"

    while True:
        try:
            age = int(Prompt.ask("年龄"))
            if age > 0 and age < 200:
                break
            console.print("[grey50]请输入有效年龄(1-199)[/grey50]")
        except ValueError:
            pass

    desc = Prompt.ask("角色描述（外貌、性格等）")

    console.print("\n[bold]选择属性生成方式[/bold]")
    console.print("  1. 标准阵列（15,14,13,12,10,8 自由分配）")
    console.print("  2. 4d6掷骰（掷六组取最高3，可重掷）")
    method = Prompt.ask("选择 [1/2]")

    stats = {}
    if method == "2":
        attrs = ["力量", "敏捷", "体质", "智力", "感知", "魅力"]
        while True:
            stats, roll_log = char_gen.roll_stats_with_log("4d6")
            console.print(f"[grey50]{roll_log}[/grey50]")
            assigned = "  ".join(f"{k}:{v}" for k, v in stats.items())
            console.print(f"  {assigned}")
            choice = Prompt.ask(escape("采用？ [1]确认 [2]重掷"))
            if choice in ("1", "y", "yes", ""):
                break
    else:
        console.print("\n[bold]分配属性点（标准阵列: 15,14,13,12,10,8）[/bold]")
        console.print("[grey50]将以下数值依次分配到各项属性中[/grey50]")
        stats = {"力量": 0, "敏捷": 0, "体质": 0, "智力": 0, "感知": 0, "魅力": 0}
        remaining = [15, 14, 13, 12, 10, 8]
        for attr in stats:
            console.print(f"\n  待分配: {remaining}")
            while True:
                try:
                    val = int(Prompt.ask(f"{attr} = "))
                    if val in remaining:
                        stats[attr] = val
                        remaining.remove(val)
                        break
                    console.print(f"[grey50]数值 {val} 不在待分配列表中，请从 {remaining} 中选择[/grey50]")
                except ValueError:
                    pass

    skills_cn = list(bg_data.skill_proficiencies) if bg_data else []
    if cd and cd.skill_choices:
        skills_cn = _choose_skills(f"选择 {class_cn} 的职业技能", list(cd.skill_options), cd.skill_choices, skills_cn)
    if sp and sp.skill_choices:
        skills_cn = _choose_skills(f"选择 {race_cn} 的附加技能", list(sp.skill_options), sp.skill_choices, skills_cn)
    skills = [SKILL_BY_EN.get(s, s) for s in skills_cn]

    class_a, bg_a = True, True
    if cd and cd.starting_equipment_a:
        class_a = _equipment_choice(f"{cd.name}职业", cd.starting_equipment_a, cd.starting_equipment_b_gp)
    if bg_data and bg_data.equipment_a:
        bg_a = _equipment_choice(f"{bg_data.name}背景", bg_data.equipment_a, bg_data.equipment_b_gp)

    hd = HIT_DICE.get(class_cn, 10)
    con_mod = (stats["体质"] - 10) // 2
    hp = hd + con_mod

    feats = [bg_data.feat] if bg_data else []
    saving_throws_cn = list(cd.saving_throws) if cd else []
    saving_throws = [SKILL_BY_EN.get(s, s) for s in saving_throws_cn]

    char = Character(
        name=name, race=race_en, lineage=lineage, char_class=class_en,
        background=bg_en, gender=gender, age=age,
        description=desc, level=1, hp=hp, max_hp=hp,
        skills=skills, saving_throws=saving_throws, feats=feats,
        strength=stats["力量"], dexterity=stats["敏捷"],
        constitution=stats["体质"], intelligence=stats["智力"],
        wisdom=stats["感知"], charisma=stats["魅力"],
    )
    _init_equipment(char, class_a=class_a, bg_a=bg_a)
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


def _init_equipment(char: Character, class_a: bool = True, bg_a: bool = True):
    """按 rules 生成起始装备与金币。
    class_a / bg_a：True=成套装备包(A)，False=换成金币(B)。
    职业+背景的装备与金币累加，另给 3000cp 基础资金。"""
    from resource.models import Inventory, Currency
    from resource.item_db import item_db
    inv = Inventory()
    cp = [3000]

    def place(item_def):
        t = item_def.type.value
        if t == "armor" and not inv.equipped.get("body"):
            inv.equipped["body"] = item_def.guid
            return
        if t == "shield" or ("盾" in item_def.name and not inv.equipped.get("off_hand")):
            inv.equipped["off_hand"] = item_def.guid
            return
        if t == "weapon" and not inv.equipped.get("weapon"):
            inv.equipped["weapon"] = item_def.guid
            return
        inv.add_item(item_def.guid)

    def grant(entry):
        entry = entry.strip()
        m = re.match(r"^(\d+)金币$", entry)
        if m:
            cp[0] += int(m.group(1)) * 10000
            return
        m = re.match(r"^(\d+)银币$", entry)
        if m:
            cp[0] += int(m.group(1)) * 100
            return
        item_def = item_db.find_by_name(entry) or item_db.find_best(entry)
        qty = 1
        if item_def is None:
            m = re.match(r"^(\d+)\s*(.+)$", entry)
            if m:
                qty = int(m.group(1))
                item_def = item_db.find_by_name(m.group(2)) or item_db.find_best(m.group(2))
        if item_def is None:
            return
        for _ in range(qty):
            place(item_def)

    cd = find_class(char.char_class)
    if cd:
        if class_a:
            for entry in cd.starting_equipment_a:
                grant(entry)
        else:
            cp[0] += cd.starting_equipment_b_gp * 10000
    bg = find_background(char.background)
    if bg:
        if bg_a:
            for entry in bg.equipment_a:
                grant(entry)
        else:
            cp[0] += bg.equipment_b_gp * 10000

    if not inv.equipped.get("body"):
        travel = item_db.find_by_name("旅行者服装") or item_db.find_by_name("棉甲")
        if travel:
            inv.equipped["body"] = travel.guid

    for gear_name in ["背包", "水袋"]:
        d = item_db.find_by_name(gear_name)
        if d:
            inv.add_item(d.guid)

    inv.currency = Currency(copper=cp[0])
    char.inventory = inv


# ---------- 主菜单 ----------

def main(skip_api_test=False):
    Config.load()
    if not skip_api_test:
        check_config()

    if not skip_api_test and Config.is_ready() and not _test_api_connection(Config.MODEL_NAME):
        console.print("[indian_red]API 连接失败，游戏需要 API 才能运行[/indian_red]")
        if Prompt.ask("重新配置 API？y/n") in ("y", "yes", ""):
            _setup_interactive()
            main()
        else:
            sys.exit(1)
        return

    logo = (
        "  ██╗     ██╗     ███╗   ███╗  ██████╗   ███╗   ██╗  ██████╗ \n"
        "  ██║     ██║     ████╗ ████║  ██╔══██╗  ████╗  ██║  ██╔══██╗\n"
        "  ██║     ██║     ██╔████╔██║  ██║  ██║  ██╔██╗ ██║  ██║  ██║\n"
        "  ██║     ██║     ██║╚██╔╝██║  ██║  ██║  ██║╚██╗██║  ██║  ██║\n"
        "  ██████╗ ██████╗ ██║ ╚═╝ ██║  ██████╔╝  ██║ ╚████║  ██████╔╝\n"
        "  ╚═════╝ ╚═════╝ ╚═╝     ╚═╝  ╚═════╝   ╚═╝  ╚═══╝  ╚═════╝ \n"
        "\n"
        "                   [grey50]由 AI 驱动的 D&D 终端游戏[/grey50]"
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

    gm = _create_world()

    console.print("\n[grey62]冒险即将开始...[/grey62]")
    try:
        _t0 = _time.time()
        parts = []
        for chunk in gm.send_message_stream("DM，请开始我的冒险吧！"):
            parts.append(chunk)
        _elapsed = _time.time() - _t0
        console.print(f"[grey62]生成耗时: {_elapsed:.1f}s{gm.usage_summary()}[/grey62]")
        console.print()
        initial_text = "".join(parts)
        log_dm_response(0, "（游戏开始）", initial_text)
        render_dm_output(initial_text, gm, _elapsed)
    except Exception as e:
        console.print(f"[indian_red]错误: {e}[/indian_red]")

    result = game_loop(gm)
    if result == "menu":
        main(skip_api_test=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]再见！[/yellow]")
        sys.exit(0)
