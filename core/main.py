import re
import sys
import threading
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
    game_loop, load_game, list_saves, SAVE_DIR, LOG_DIR,
)
from core.world_bg import list_world_backgrounds, load_world_background
from core.opening_templates import list_opening_templates


# ---------- 版本更新检查 ----------

def _start_update_check():
    result = {}

    def _worker():
        try:
            from core.version_check import check_update
            result["value"] = check_update()
        except Exception:
            result["value"] = None

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread, result


def _print_update_status(thread, result):
    """API 成功后调用：git 已出结果就打印，未完成则不等，直接进入游戏。"""
    thread.join(timeout=2)
    value = result.get("value")
    if not value:
        return
    if value["status"] == "update_available":
        console.print(
            f"[gold3]游戏有更新可用：落后 {value['behind']} 个提交"
            f"（最新 {value['new_commit']}）({value.get('remote_url', '')})[/gold3]")
        console.print("[grey50]可 git pull 更新，不自动拉取[/grey50]")
    else:
        console.print(
            f"[grey50]游戏版本已是最新版本 ({value.get('remote_url', '')})[/grey50]")
    console.print()


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
        console.print()
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

    save_key = Prompt.ask(
        "是否将 API 密钥保存到 .env 文件？\n"
        "[grey50]选择否将只在本次会话生效，重启需重新输入；保存为明文，请注意保管[/grey50]",
        choices=["y", "n"],
        default="n",
    )
    save_key = save_key in ("y", "yes", "是", "")

    lines = [
        f"API_BASE_URL={base_url}",
        f"MODEL_NAME={model}",
    ]
    if save_key:
        lines.append(f"API_KEY={api_key}")
    Path(".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    Config.load()
    if not save_key:
        Config.API_KEY = api_key

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

def create_character(story_roles: list = None) -> Character:
    story_roles = story_roles or []
    while True:
        console.print(f"\n[steel_blue]创建你的角色[/steel_blue]")
        console.print("  1. 快速创建（随机生成，直接开玩）")
        console.print("  2. 详细创建（手动分配属性）")
        if story_roles:
            console.print("  3. 使用故事包内的角色")
        max_choice = 3 if story_roles else 2
        # 模式菜单是角色创建的最顶层：此处 /back 穿透，返回上一级（创建世界菜单）
        mode = _pre_game_ask(escape(f"选择 [1/{max_choice}]"))
        try:
            if mode == "3" and story_roles:
                char = _pick_story_role(story_roles)
                if char is not None:
                    _offer_save_template(char)
                return char

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
        except _BackSignal:
            # 快速/详细/故事角色的内部步骤按了 /back → 返回本模式菜单重选
            continue


def _ask_quick_name() -> str:
    name = _pre_game_ask("角色名称（留空回车随机生成角色名称）")
    if not name:
        confirm = _pre_game_ask("是否随机生成名字？（再次回车确认随机生成角色名称，或直接输入名字）")
        name = char_gen.random_name() if not confirm else confirm
    return name


def _confirm_character(char: Character, roll_log: str = "") -> str:
    """统一预览确认：渲染角色卡并请求采用。
    返回 'yes'（采用）/ 'reroll'（重新生成/重新创建）/ 'cancel'（取消）。"""
    while True:
        render_character_sheet(char, roll_log)
        choice = _pre_game_ask(escape("采用？ [1]确认 [2]重新生成 [3]取消"))
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
    pick = _pre_game_ask(escape("选择 [1/2]"))
    return pick != "2"


def _offer_save_template(char: Character):
    ans = _pre_game_ask(escape(f"是否将「{char.name}」保存为角色模板？y/n"))
    if ans.strip().lower() not in ("y", "yes"):
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
    ans = _pre_game_ask(escape("是否导入模板开始新冒险？y/n"))
    if ans.strip().lower() not in ("y", "yes"):
        return None
    for i, s in enumerate(stems, 1):
        console.print(f"  {i}. {s}")
    try:
        range_txt = f"[1-{len(stems)}]" if len(stems) > 1 else "[1]"
        idx = int(_pre_game_ask(escape(f"选择编号 {range_txt}"))) - 1
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
    """世界启动入口：预设组合 / 让大模型创建世界 / 本地完整世界（已有的完整世界 / 程序化生成世界，规划中）。"""
    from resource.packs import RESOURCE_MODE_PACK, RESOURCE_MODE_FREE, configure_resource_catalogs
    from mods.presets import list_presets, load_preset
    from mods.story_packs import list_story_packs, load_story_pack, load_story_roles
    from mods.story_roles import StoryRole
    while True:
        console.print("\n[steel_blue]创建世界[/steel_blue]")
        console.print("  1. 使用预设组合")
        console.print("  2. 让大模型创建世界")
        console.print("  3. 本地完整世界（开发中）")
        # 创建世界菜单是 B 级：此处 /back 直接穿透，由 main() 返回主菜单
        choice = _pre_game_ask(escape("选择 [1/2/3]"))
        if not choice:
            choice = "1"
        if choice == "3":
            # 本地完整世界子菜单（C 级：/back 回到创建世界菜单）
            try:
                console.print("\n[steel_blue]本地完整世界[/steel_blue]")
                console.print("  1. 已有的完整世界（开发中）")
                console.print("  2. 程序化生成世界（开发中）")
                sub = _pre_game_ask(escape("选择 [1/2]（/back 返回创建世界菜单）"))
            except _BackSignal:
                continue
            if sub == "1":
                console.print("[grey50]本地完整世界（已有的完整世界）尚未开放，敬请期待[/grey50]")
            elif sub == "2":
                console.print("[grey50]程序化生成世界尚未开放，敬请期待[/grey50]")
            else:
                console.print("[grey50]无效选择[/grey50]")
            continue

        # ── 方式一：预设组合（C 级：/back 回到创建世界菜单） ──
        if choice == "1":
            try:
                preset_list = list_presets()
                if not preset_list:
                    console.print("[grey50]暂无可用的预设组合，请先添加 mods/index/ 下的预设[/grey50]")
                    continue
                console.print("\n[steel_blue]选择预设组合[/steel_blue]")
                for i, (display, pid) in enumerate(preset_list, 1):
                    console.print(f"  {i}. {display}")
                range_txt = f"[1-{len(preset_list)}]" if len(preset_list) > 1 else "[1]"
                p_choice = _pre_game_ask(escape(f"选择 {range_txt}"))
                try:
                    idx = int(p_choice) - 1
                    preset = load_preset(preset_list[idx][1] if 0 <= idx < len(preset_list) else preset_list[0][1])
                except (ValueError, IndexError):
                    preset = load_preset(preset_list[0][1])
                if preset is None:
                    console.print("[grey50]预设加载失败[/grey50]")
                    continue

                # 应用预设组件
                setting_stem = preset.background or "default-dnd"
                setting_content = load_world_background(setting_stem)
                resource_mode = preset.resource_strategy or RESOURCE_MODE_PACK
                if resource_mode not in (RESOURCE_MODE_PACK, RESOURCE_MODE_FREE):
                    resource_mode = RESOURCE_MODE_PACK
                configure_resource_catalogs(resource_mode, preset.resource_pack or "default-dnd")

                story_pack = None
                if preset.story_pack:
                    story_pack = load_story_pack(preset.story_pack)
                story_roles = load_story_roles(story_pack) if story_pack else []

                opening_stem = preset.opening or ""

                # 角色：先检测本地角色模板；预设若带故事包角色，创建菜单会提供"使用故事包内的角色"选项
                char = _offer_template_import()
                if char is None:
                    char = create_character(story_roles)
                while char is None:
                    console.print("\n[grey50]角色未创建，请重新创建[/grey50]")
                    char = create_character(story_roles)

                # 若扮演的是故事角色且该角色声明了专属开场，则覆盖预设默认开场（如叛乱方角色用叛乱开场）
                role = getattr(char, "story_role", None)
                if role and role.opening:
                    opening_stem = role.opening

                return GameMaster(
                    char, opening_stem,
                    setting_content=setting_content, setting_stem=setting_stem,
                    resource_mode=resource_mode,
                    resource_pack=preset.resource_pack or "default-dnd",
                    story_pack_id=story_pack.pack_id if story_pack else "",
                    story_pack_content=story_pack.content if story_pack else "",
                    world_source="preset",
                )
            except _BackSignal:
                continue

        # ── 方式二：自定义（大模型创建世界） ──
        # 选择世界背景（C 级：/back 回到创建世界菜单）
        try:
            bg_list = list_world_backgrounds()
            console.print("\n[steel_blue]选择世界背景[/steel_blue]")
            if bg_list:
                for i, (display, stem) in enumerate(bg_list, 1):
                    console.print(f"  {i}. {display}")
                bg_range = f"[1-{len(bg_list)}]" if len(bg_list) > 1 else "[1]"
                bg_choice = _pre_game_ask(escape(f"选择 {bg_range}"))
                try:
                    idx = int(bg_choice) - 1
                    setting_stem = bg_list[idx][1] if 0 <= idx < len(bg_list) else bg_list[0][1]
                except (ValueError, IndexError):
                    setting_stem = bg_list[0][1]
            else:
                setting_stem = "default-dnd"
            setting_content = load_world_background(setting_stem)
        except _BackSignal:
            continue

        # 选择故事包（可选）
        try:
            pack_list = list_story_packs()
            story_pack = None
            if pack_list:
                console.print(f"\n[steel_blue]检测到故事包 {len(pack_list)} 个[/steel_blue]")
                want = _pre_game_ask(escape("是否使用故事包？y/n"))
                if want.strip().lower() in ("y", "yes"):
                    for i, (display, pid) in enumerate(pack_list, 1):
                        console.print(f"  {i}. {display}")
                    p_range = f"[1-{len(pack_list)}]" if len(pack_list) > 1 else "[1]"
                    p_choice = _pre_game_ask(escape(f"选择 {p_range}"))
                    try:
                        idx = int(p_choice) - 1
                        story_pack = load_story_pack(pack_list[idx][1]) if 0 <= idx < len(pack_list) else None
                    except (ValueError, IndexError):
                        story_pack = None
            story_roles = load_story_roles(story_pack) if story_pack else []
        except _BackSignal:
            continue

        # 对象资源策略（查表创建会再选资源包；填表创建不使用资源包）
        try:
            console.print("\n[steel_blue]选择对象资源策略[/steel_blue]")
            console.print("  1. 查表创建（从资源包检索，所有对象来自资源库）")
            console.print("  2. 填表创建（不使用任何资源包，大模型通过填写表单自由创建一切对象）")
            mode_choice = _pre_game_ask(escape("选择 [1/2]"))
            if mode_choice == "2":
                resource_mode = RESOURCE_MODE_FREE
                configure_resource_catalogs(resource_mode)
                console.print("[grey50]已启用填表创建：不使用任何资源包，对象将按表单创建并随存档保存。[/grey50]")
            else:
                resource_mode = RESOURCE_MODE_PACK
                configure_resource_catalogs(resource_mode, _choose_resource_pack())
        except _BackSignal:
            continue

        try:
            char = _offer_template_import()
            if char is None:
                char = create_character(story_roles)
            while char is None:
                console.print("\n[grey50]角色未创建，请重新创建[/grey50]")
                char = create_character(story_roles)
        except _BackSignal:
            continue

        role = getattr(char, "story_role", None)
        if role and role.opening:
            opening_stem = role.opening
            console.print(f"[grey50]已使用故事角色的专属开场: {opening_stem}[/grey50]")
        else:
            try:
                console.print("\n[steel_blue]选择开场模板[/steel_blue]")
                tpl_list = list_opening_templates()
                console.print("  1. 随机世界（无开场模板，完全随机生成）")
                for i, (display, stem) in enumerate(tpl_list, 1):
                    console.print(f"  {i + 1}. {display}")
                tpl = _pre_game_ask(escape(f"选择 [1-{len(tpl_list) + 1}]"))
                try:
                    idx = int(tpl) - 2
                    opening_stem = tpl_list[idx][1] if 0 <= idx < len(tpl_list) else ""
                except (ValueError, IndexError):
                    opening_stem = ""
            except _BackSignal:
                continue

        return GameMaster(
            char, opening_stem,
            setting_content=setting_content, setting_stem=setting_stem,
            resource_mode=resource_mode,
            story_pack_id=story_pack.pack_id if story_pack else "",
            story_pack_content=story_pack.content if story_pack else "",
            world_source="llm",
        )


def _choose_resource_pack() -> str:
    """列出已安装资源包并让玩家选择，返回 pack_id。"""
    from mods.api import list_resource_packs
    packs = list_resource_packs()
    if not packs:
        console.print("[grey50]未安装任何资源包，回退默认 default-dnd。[/grey50]")
        return "default-dnd"
    console.print("\n[steel_blue]选择资源包[/steel_blue]")
    for i, pid in enumerate(packs, 1):
        console.print(f"  {i}. {pid}")
    range_txt = f"[1-{len(packs)}]" if len(packs) > 1 else "[1]"
    while True:
        p_choice = _pre_game_ask(escape(f"选择资源包 {range_txt}"))
        if not p_choice:
            return packs[0]
        try:
            idx = int(p_choice) - 1
            if 0 <= idx < len(packs):
                return packs[idx]
        except ValueError:
            pass
        console.print("[grey50]无效选择[/grey50]")


def _pick_story_role(story_roles: list) -> Character:
    """列出故事角色并让玩家选择扮演其一；返回 Character 或 None。"""
    while True:
        console.print("\n[steel_blue]选择你要扮演的故事角色[/steel_blue]")
        for i, r in enumerate(story_roles, 1):
            console.print(f"  {i}. {r.name}（{r.char_class}）")
            if r.description:
                console.print(f"     [grey50]{r.description}[/grey50]")
        r_range = f"[1-{len(story_roles)}]" if len(story_roles) > 1 else "[1]"
        r_choice = _pre_game_ask(escape(f"选择 {r_range}"))
        try:
            idx = int(r_choice) - 1
            if 0 <= idx < len(story_roles):
                role = story_roles[idx]
                char = build_character_from_role(role)
                char.story_role = role
                return char
        except (ValueError, IndexError):
            pass
        console.print("[grey50]无效选择[/grey50]")


def build_character_from_role(role) -> Character:
    """把故事角色（StoryRole）落成可用的 Character。"""
    from mods.story_roles import StoryRole
    from resource.models import Inventory, Currency
    from resource.item_db import item_db
    stats = dict(role.stats)
    char = Character(
        name=role.name or char_gen.random_name(),
        race=role.species, lineage=role.lineage, char_class=role.char_class,
        background=role.background, description=role.description or f"一位来自故事包的角色。",
        level=1, hp=role.hp, max_hp=role.max_hp or role.hp,
        strength=stats.get("力量", 10), dexterity=stats.get("敏捷", 10),
        constitution=stats.get("体质", 10), intelligence=stats.get("智力", 10),
        wisdom=stats.get("感知", 10), charisma=stats.get("魅力", 10),
        skills=list(role.skills), feats=[],
        gender="male", age=20,
    )
    inv = Inventory()
    cp = [3000]
    for entry in role.equipment:
        _grant_entry(inv, cp, entry)
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
    return char


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
    """详细创建向导：分步骤收集信息，输入 /back 可回退上一步（回到第一步再 /back 则上抛）。"""
    from rules.srd_data import SKILL_BY_EN
    step = 0
    st: dict = {}
    while True:
        try:
            if step == 0:
                while True:
                    name = _pre_game_ask("角色名称")
                    if name.strip():
                        break
                    console.print("[grey50]无效角色名称，请重新输入[/grey50]")
                st["name"] = name
                step = 1
            elif step == 1:
                console.print("\n[bold]选择种族:[/bold]")
                for i, s in enumerate(RACES, 1):
                    sp = find_species(s)
                    info = f"  {i}. {s}（速度{sp.speed}尺，{'/'.join(sp.size_options)}）" if sp else f"  {i}. {s}"
                    console.print(info)
                race_cn = _menu_choice(RACES, "种族")
                st["race_cn"] = race_cn
                st["sp"] = find_species(race_cn)
                st["race_en"] = st["sp"].name_en if st["sp"] else race_cn
                step = 2
            elif step == 2:
                st["lineage"] = _choose_lineage(st["race_cn"])
                step = 3
            elif step == 3:
                console.print("\n[bold]选择背景:[/bold]")
                for i, bg_name in enumerate(BACKGROUNDS, 1):
                    bg = find_background(bg_name)
                    if bg:
                        console.print(f"  {i}. {bg_name}（专长: {bg.feat}，技能: {'/'.join(bg.skill_proficiencies)}）")
                bg_cn = _menu_choice(BACKGROUNDS, "背景")
                st["bg_data"] = find_background(bg_cn)
                st["bg_en"] = st["bg_data"].name_en if st["bg_data"] else bg_cn
                step = 4
            elif step == 4:
                console.print("\n[bold]选择职业:[/bold]")
                for i, cn in enumerate(CLASSES, 1):
                    cd = find_class(cn)
                    if cd:
                        console.print(f"  {i}. {cn}（生命骰d{cd.hit_die}，豁免: {'/'.join(cd.saving_throws)}）")
                class_cn = _menu_choice(CLASSES, "职业")
                st["class_cn"] = class_cn
                st["cd"] = find_class(class_cn)
                st["class_en"] = st["cd"].name_en if st["cd"] else class_cn
                step = 5
            elif step == 5:
                console.print("\n[bold]选择性别:[/bold]")
                console.print("  1. 男")
                console.print("  2. 女")
                gender_cn = _menu_choice(["男", "女"], "性别")
                st["gender"] = "male" if gender_cn == "男" else "female"
                step = 6
            elif step == 6:
                while True:
                    try:
                        age = int(_pre_game_ask("年龄"))
                        if age > 0 and age < 200:
                            break
                        console.print("[grey50]请输入有效年龄(1-199)[/grey50]")
                    except ValueError:
                        pass
                st["age"] = age
                step = 7
            elif step == 7:
                st["desc"] = _pre_game_ask("角色描述（外貌、性格等）")
                step = 8
            elif step == 8:
                console.print("\n[bold]选择属性生成方式[/bold]")
                console.print("  1. 标准阵列（15,14,13,12,10,8 自由分配）")
                console.print("  2. 4d6掷骰（掷六组取最高3，可重掷）")
                st["method"] = _pre_game_ask("选择 [1/2]")
                step = 9
            elif step == 9:
                if st["method"] == "2":
                    attrs = ["力量", "敏捷", "体质", "智力", "感知", "魅力"]
                    while True:
                        stats, roll_log = char_gen.roll_stats_with_log("4d6")
                        console.print(f"[grey50]{roll_log}[/grey50]")
                        assigned = "  ".join(f"{k}:{v}" for k, v in stats.items())
                        console.print(f"  {assigned}")
                        choice = _pre_game_ask(escape("采用？ [1]确认 [2]重掷"))
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
                                val = int(_pre_game_ask(f"{attr} = "))
                                if val in remaining:
                                    stats[attr] = val
                                    remaining.remove(val)
                                    break
                                console.print(f"[grey50]数值 {val} 不在待分配列表中，请从 {remaining} 中选择[/grey50]")
                            except ValueError:
                                pass
                st["stats"] = stats
                step = 10
            elif step == 10:
                sp, cd, bg_data = st.get("sp"), st.get("cd"), st.get("bg_data")
                skills_cn = list(bg_data.skill_proficiencies) if bg_data else []
                if cd and cd.skill_choices:
                    skills_cn = _choose_skills(f"选择 {st['class_cn']} 的职业技能", list(cd.skill_options), cd.skill_choices, skills_cn)
                if sp and sp.skill_choices:
                    skills_cn = _choose_skills(f"选择 {st['race_cn']} 的附加技能", list(sp.skill_options), sp.skill_choices, skills_cn)
                st["skills"] = [SKILL_BY_EN.get(s, s) for s in skills_cn]
                step = 11
            elif step == 11:
                class_a, bg_a = True, True
                cd, bg_data = st.get("cd"), st.get("bg_data")
                if cd and cd.starting_equipment_a:
                    class_a = _equipment_choice(f"{cd.name}职业", cd.starting_equipment_a, cd.starting_equipment_b_gp)
                if bg_data and bg_data.equipment_a:
                    bg_a = _equipment_choice(f"{bg_data.name}背景", bg_data.equipment_a, bg_data.equipment_b_gp)
                st["class_a"], st["bg_a"] = class_a, bg_a
                step = 12
            elif step == 12:
                hd = HIT_DICE.get(st["class_cn"], 10)
                con_mod = (st["stats"]["体质"] - 10) // 2
                hp = hd + con_mod

                feats = [st["bg_data"].feat] if st.get("bg_data") else []
                saving_throws_cn = list(st["cd"].saving_throws) if st.get("cd") else []
                saving_throws = [SKILL_BY_EN.get(s, s) for s in saving_throws_cn]

                char = Character(
                    name=st["name"], race=st["race_en"], lineage=st["lineage"],
                    char_class=st["class_en"], background=st["bg_en"],
                    gender=st["gender"], age=st["age"],
                    description=st["desc"], level=1, hp=hp, max_hp=hp,
                    skills=st["skills"], saving_throws=saving_throws, feats=feats,
                    strength=st["stats"]["力量"], dexterity=st["stats"]["敏捷"],
                    constitution=st["stats"]["体质"], intelligence=st["stats"]["智力"],
                    wisdom=st["stats"]["感知"], charisma=st["stats"]["魅力"],
                )
                _init_equipment(char, class_a=st["class_a"], bg_a=st["bg_a"])
                return char
        except _BackSignal:
            # /back → 回退上一步；已回到第一步则继续上抛（由 create_character 回模式菜单）
            step -= 1
            if step < 0:
                raise


def _menu_choice(options: list, label: str) -> str:
    while True:
        try:
            choice = int(_pre_game_ask(f"请选择{label}"))
            if 1 <= choice <= len(options):
                return options[choice - 1]
        except ValueError:
            pass
        console.print("[grey50]无效选择[/grey50]")


def _place_item(inv, item_def):
    """把物品定义放入背包：优先装备到对应槽位，否则入包。"""
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


def _resolve_item(entry):
    """按条目解析物品：先精确名 → 再别名 → 最后模糊匹配。"""
    from resource.item_db import item_db
    return (item_db.find_by_name(entry)
            or item_db.find_by_alias(entry)
            or item_db.find_best(entry))


def _grant_entry(inv, cp, entry):
    """把一条起始装备条目解析进背包，保证实例数量正确。

    - 金额条目（15金币 / 钱包（20金））直接加钱。
    - 数量条目（2把匕首 / 20支箭 / 50尺绳子）：武器/护甲/盾第一件入对应槽位、
      其余进背包；弹药条目（箭矢/弩矢）的物品定义本身就是一束（如 Arrows (20)），
      数量前缀只是束内描述，只生成 1 个实例；其余类型按数量批量生成 N 个独立实例。
    """
    entry = entry.strip()
    m = re.match(r"^(\d+)金币$", entry)
    if m:
        cp[0] += int(m.group(1)) * 10000
        return
    m = re.match(r"^(\d+)银币$", entry)
    if m:
        cp[0] += int(m.group(1)) * 100
        return
    m = re.match(r"^钱包（(\d+)金）$", entry)
    if m:
        cp[0] += int(m.group(1)) * 10000
        return

    item_def = _resolve_item(entry)
    qty = 1
    if item_def is None:
        # 尺寸前缀（如 50尺绳子 / 10尺布料）：是物品属性，数量仍为 1
        m = re.match(r"^(\d+)尺(.+)$", entry)
        if m:
            item_def = _resolve_item(m.group(2))
        # 量词前缀：2把匕首 / 20支箭 / 8张羊皮纸
        if item_def is None:
            m = re.match(r"^(\d+)[个把支根张枚]?\s*(.+)$", entry)
            if m:
                qty = int(m.group(1))
                item_def = _resolve_item(m.group(2))
    if item_def is None:
        return

    t = item_def.type.value
    if t in ("armor", "shield", "weapon"):
        # 第一件尝试入槽，其余全部进背包
        _place_item(inv, item_def)
        if qty > 1:
            inv.add_item(item_def.guid, qty - 1)
    else:
        # 弹药物品定义即一束（箭矢=Arrows (20)），数量前缀是束内描述，只给 1 个实例
        if t == "ammunition":
            inv.add_item(item_def.guid)
        else:
            # 消耗品/工具/装备等：批量生成 qty 个独立实例
            inv.add_item(item_def.guid, qty)


def _init_equipment(char: Character, class_a: bool = True, bg_a: bool = True):
    """按 rules 生成起始装备与金币。
    class_a / bg_a：True=成套装备包(A)，False=换成金币(B)。
    职业+背景的装备与金币累加，另给 3000cp 基础资金。"""
    from resource.models import Inventory, Currency
    from resource.item_db import item_db
    inv = Inventory()
    cp = [3000]

    def grant(entry):
        _grant_entry(inv, cp, entry)

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

class _QuickStartSignal(Exception):
    """在任意前置菜单输入 /quickstart 或 /q 时抛出的快速开始信号。"""


class _BackSignal(Exception):
    """输入 /back 或 /b 时抛出：返回上一级菜单。"""


class _MenuSignal(Exception):
    """输入 /menu 或 /m 时抛出：返回最上级主菜单。"""


class _QuitSignal(Exception):
    """输入 /quit 时抛出：退出游戏。"""


def _print_commands():
    console.print(f"\n[steel_blue]命令[/steel_blue]")
    console.print(f"  [grey82]/help[/grey82]    显示此命令列表")
    console.print(f"  [grey82]/back[/grey82]    返回上一级菜单")
    console.print(f"  [grey82]/menu[/grey82]    返回主菜单")
    console.print(f"  [grey82]/quit[/grey82]    退出游戏")
    console.print(f"  [grey82]/quickstart[/grey82]  快速开始（随机角色直接进入游戏）")


def _menu_help(ctx, args):
    _print_commands()
    return None


def _menu_back(ctx, args):
    raise _BackSignal()


def _menu_menu(ctx, args):
    raise _MenuSignal()


def _menu_quit(ctx, args):
    raise _QuitSignal()


def _menu_quickstart(ctx, args):
    raise _QuickStartSignal()


def _build_menu_registry():
    from core.commands import build_registry
    reg = build_registry()
    reg.get("help").handler = _menu_help
    reg.get("back").handler = _menu_back
    reg.get("menu").handler = _menu_menu
    reg.get("quit").handler = _menu_quit
    reg.get("quickstart").handler = _menu_quickstart
    return reg


_MENU_REGISTRY = _build_menu_registry()


def _pre_game_ask(prompt_text: str, **kw) -> str:
    """游戏开始前的输入：识别 /help、/back、/menu、/quickstart 及中文等价命令。"""
    while True:
        val = Prompt.ask(prompt_text, **kw)
        if not val.strip():
            return val
        from core.commands import parse_command
        if parse_command(val) is not None:
            result = _MENU_REGISTRY.resolve(val, "menu")
            if result is not None:
                cmd, args = result
                if cmd.handler:
                    cmd.handler(None, args)
                continue
            console.print("[grey50]无效命令，输入 /help 查看可用命令[/grey50]")
            continue
        return val


def _start_adventure(gm: GameMaster):
    console.print("\n[grey62]冒险即将开始...[/grey62]")
    from core.rounds.game_round import GameRound
    result = GameRound(gm).run()
    if result == "menu":
        main(skip_api_test=True)


def _quickstart():
    """快速开始：使用默认预设（查表创建 + 默认世界背景 + 随机开场）+ 随机角色，直接进入游戏。"""
    from resource.packs import RESOURCE_MODE_PACK, configure_resource_catalogs
    from mods.presets import load_preset
    preset = load_preset("default") or load_preset("default-dnd")
    resource_mode = RESOURCE_MODE_PACK
    if preset:
        resource_mode = preset.resource_strategy or RESOURCE_MODE_PACK
    configure_resource_catalogs(resource_mode, preset.resource_pack if preset else "default-dnd")
    setting_stem = (preset.background if preset and preset.background else "default-dnd")
    setting_content = load_world_background(setting_stem)
    story_pack_id = preset.story_pack if preset else ""
    story_pack_content = ""
    if story_pack_id:
        from mods.story_packs import load_story_pack
        sp = load_story_pack(story_pack_id)
        story_pack_content = sp.content if sp else ""
    char, roll_log = char_gen.roll_character(name=char_gen.random_name())
    _init_equipment(char)
    console.print(f"\n[grey62]快速开始：随机角色 {char.name}（Lv.{char.level} {char.race_cn} {char.class_cn}）[/grey62]")
    gm = GameMaster(
        char, preset.opening if preset else "",
        setting_content=setting_content, setting_stem=setting_stem,
        resource_mode=resource_mode,
        story_pack_id=story_pack_id, story_pack_content=story_pack_content,
        world_source="preset",
    )
    _start_adventure(gm)


def main(skip_api_test=False):
    Config.load()
    update_thread = update_result = None
    if not skip_api_test:
        update_thread, update_result = _start_update_check()
        check_config()

    if not skip_api_test and Config.is_ready() and not _test_api_connection(Config.MODEL_NAME):
        console.print("[indian_red]API 连接失败，游戏需要 API 才能运行[/indian_red]")
        if Prompt.ask("重新配置 API？y/n") in ("y", "yes", ""):
            _setup_interactive()
            main()
        else:
            sys.exit(1)
        return

    if update_thread is not None:
        _print_update_status(update_thread, update_result)

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

    try:
        if saves:
            console.print("[grey62]检测到存档[/grey62]")
            console.print("  1. 继续游戏")
            console.print("  2. 新游戏")
            console.print("  3. 修改 API 配置")
            choice = _pre_game_ask(escape("选择 [1/2/3]"))
        else:
            console.print("  1. 新游戏")
            if Config.is_ready():
                console.print("  2. 修改 API 配置")
                choice = _pre_game_ask(escape("选择 [1/2]"))
            else:
                choice = "1"

        if (saves and choice == "3") or (not saves and choice == "2" and Config.is_ready()):
            _setup_interactive()
            main()
            return

        if saves and (not choice or choice == "1"):
            saves_list = list_saves()
            try:
                idx = int(_pre_game_ask("选择编号")) - 1
                if 0 <= idx < len(saves_list):
                    gm = load_game(str(saves_list[idx]))
                    game_loop(gm)
                    return
            except _QuickStartSignal:
                raise
            except (_BackSignal, _MenuSignal, _QuitSignal):
                raise
            except ValueError:
                console.print("[grey50]请输入有效数字[/grey50]")
            except:
                pass

        _start_adventure(_create_world())
    except _BackSignal:
        main(skip_api_test=True)
        return
    except _MenuSignal:
        main(skip_api_test=True)
        return
    except _QuitSignal:
        sys.exit(0)
    except _QuickStartSignal:
        _quickstart()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]再见！[/yellow]")
        sys.exit(0)
