import json
import os
import re
import time as _time
from pathlib import Path

from rich.prompt import Prompt

from core.character import Character
from core.game_master import GameMaster
from world.state import WorldState
from core.ui import console

SAVE_DIR = Path("./saves")
LOG_DIR = Path("./logs")


# ---------- 存档 ----------

def _atomic_write(path: Path, text: str) -> None:
    """原子写入：同目录临时文件 + os.replace，避免中途崩溃留下半截存档。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _is_shell_dir(name: str) -> bool:
    """空壳目录：存档目录却缺 info.json（如历史遗留的「我的档」）。"""
    return not (SAVE_DIR / name / "info.json").exists()


def list_saves():
    """列出存档槽位（用 os.scandir/entry.name，避免 Path 往返导致的 Unicode 问题）。

    跳过空壳目录（无 info.json）与旧格式单文件 .json。返回 (str 名列表)。
    """
    if not SAVE_DIR.is_dir():
        return []
    saves: list[str] = []
    dirs: list[str] = []
    with os.scandir(SAVE_DIR) as it:
        for entry in it:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if _is_shell_dir(entry.name):
                        continue
                    dirs.append(entry.name)
                elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".json"):
                    saves.append(entry.name)
            except OSError:
                continue
    saves.sort()
    dirs.sort()
    if not saves and not dirs:
        return []
    console.print("\n[bold]存档列表:[/bold]")
    for i, s in enumerate(saves, 1):
        size = (SAVE_DIR / s).stat().st_size
        console.print(f"  {i}. {Path(s).stem} ({size}B) [grey50]旧格式[/grey50]")
    for i, d in enumerate(dirs, len(saves) + 1):
        console.print(f"  {i}. {d}")
    return saves + dirs


def _safe_slot_name(name: str) -> str:
    """存档槽位名安全化：去非法路径字符/首尾空白，防止路径穿越。"""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", (name or "").strip())
    if cleaned in (".", "..", ""):
        return ""
    return cleaned


def save_game(gm: GameMaster, name: str = None) -> bool:
    """保存游戏，返回是否真正写入。

    - 首次存档（尚无绑定槽位）：提示玩家输入存档名称。
    - 只要目标存档已存在（含当前绑定槽位、另存为新槽位）：都先询问是否覆盖。
    - 槽位绑定用于把"匿名 /save"定位到本会话已使用的存档，避免串到别的存档。
    """
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    target = _safe_slot_name(name) if name else ""
    if not target:
        target = gm.save_slot or ""
    if not target:
        target = _safe_slot_name(Prompt.ask("为本次冒险命名存档"))
        if not target:
            console.print("[grey50]存档名称无效，已取消保存[/grey50]")
            return False
    char_dir = SAVE_DIR / target

    # 只要目标已存在，一律询问覆盖
    if char_dir.exists() or (SAVE_DIR / f"{target}.json").exists():
        confirm = Prompt.ask(f"存档「{target}」已存在，是否覆盖？y/n")
        if confirm not in ("y", "yes", ""):
            console.print("[grey50]已取消保存[/grey50]")
            return False
    char_dir.mkdir(parents=True, exist_ok=True)

    # info.json — character static stats only
    info_data = gm.character.to_dict()
    _atomic_write(char_dir / "info.json", json.dumps(info_data, ensure_ascii=False, indent=2))

    # bag.json — inventory items (instance_id + guid)
    bag_data = [
        {"instance_id": inst.instance_id, "guid": inst.guid}
        for inst in gm.character.inventory.all_instances()
    ]
    _atomic_write(char_dir / "bag.json", json.dumps(bag_data, ensure_ascii=False, indent=2))

    # equip.json — equipped items (slot -> guid)
    equip_data = {
        slot: guid for slot, guid in gm.character.inventory.equipped.items() if guid
    }
    _atomic_write(char_dir / "equip.json", json.dumps(equip_data, ensure_ascii=False, indent=2))

    # money.json — currency (copper only)
    money_data = {"copper": gm.character.inventory.currency.copper}
    _atomic_write(char_dir / "money.json", json.dumps(money_data, ensure_ascii=False, indent=2))

    # skill.json — skills（主存储为 info.json，此文件保留英文 key 可读副本）
    _skills_json = [
        (s.name_en or s.name) if hasattr(s, "name_en") else s
        for s in (gm.character.skills or [])
    ]
    _atomic_write(char_dir / "skill.json", json.dumps(_skills_json, ensure_ascii=False, indent=2))

    # history.json — game history
    initiative_data = []
    init = getattr(gm, "initiative", None)
    if init:
        initiative_data = init.to_dict()
    history_meta = {
        "last_scene": gm.last_scene,
        "last_scene_detail": gm.last_scene_detail,
        "last_time": gm.last_time,
        "setting_stem": gm.setting_stem,
        "resource_mode": getattr(gm, "resource_mode", "pack"),
        "resource_pack": getattr(gm, "resource_pack", ""),
        "story_pack_id": getattr(gm, "story_pack_id", ""),
        "story_pack_content": getattr(gm, "story_pack_content", ""),
        "world_source": getattr(gm, "world_source", "llm"),
        "initiative": initiative_data,
    }
    _atomic_write(char_dir / "history.json", json.dumps({
        "meta": history_meta,
        "compressed": gm.compressed_history,
        "last_assistant": gm.last_assistant,
    }, ensure_ascii=False, indent=2))

    # world.json — NPC / entity state
    if hasattr(gm, 'world_state') and gm.world_state:
        _atomic_write(char_dir / "world.json", json.dumps(
            gm.world_state.to_dict(), ensure_ascii=False, indent=2))

    # character_template.json — 角色创建时的快照（角色模板，含初始背包/装备/金钱）
    tmpl = getattr(gm, "character_template", None)
    if tmpl:
        _atomic_write(char_dir / "character_template.json", json.dumps(
            tmpl, ensure_ascii=False, indent=2))

    # runtime_defs/ — 填表创建的对象定义（随存档保存，重启可恢复）
    _save_runtime_defs(char_dir)

    gm.save_slot = target
    console.print(f"[grey50]已保存: {target}[/grey50]")
    console.print()
    return True


def _save_runtime_defs(char_dir: Path):
    """把运行时目录（填表创建的对象定义）分类写入存档子文件夹。"""
    from resource.item_db import item_db
    from world.npc_templates import npc_catalog
    runtime_items = item_db.runtime_items()
    runtime_npcs = npc_catalog.runtime_templates()
    if not runtime_items and not runtime_npcs:
        return
    runtime_dir = char_dir / "runtime_defs"
    if runtime_items:
        items_dir = runtime_dir / "items"
        items_dir.mkdir(parents=True, exist_ok=True)
        for guid, item in runtime_items.items():
            _atomic_write(items_dir / f"{guid}.json", json.dumps(item.to_dict(), ensure_ascii=False, indent=2))
    if runtime_npcs:
        npcs_dir = runtime_dir / "npcs"
        npcs_dir.mkdir(parents=True, exist_ok=True)
        for tid, entry in runtime_npcs.items():
            _atomic_write(npcs_dir / f"{tid}.json", json.dumps(entry, ensure_ascii=False, indent=2))


def _restore_runtime_defs(char_dir: Path):
    """从存档恢复运行时目录（先于背包迁移，保证运行时 guid 可解析）。"""
    from resource.item_db import item_db
    from resource.models import ItemDef, item_def_from_dict
    from world.npc_templates import npc_catalog
    runtime_dir = char_dir / "runtime_defs"
    if not runtime_dir.exists():
        return
    items_dir = runtime_dir / "items"
    if items_dir.exists():
        defs: dict[str, ItemDef] = {}
        for fpath in items_dir.glob("*.json"):
            entry = json.loads(fpath.read_text(encoding="utf-8"))
            entry["guid"] = fpath.stem
            defs[entry["guid"]] = item_def_from_dict(entry)
        item_db.replace_runtime(defs)
    npcs_dir = runtime_dir / "npcs"
    if npcs_dir.exists():
        entries: dict[str, dict] = {}
        for fpath in npcs_dir.glob("*.json"):
            d = json.loads(fpath.read_text(encoding="utf-8"))
            d["id"] = fpath.stem
            entries[d["id"]] = d
        npc_catalog.replace_runtime(entries)


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

    # skills / saving_throws — 旧格式为字符串名；新格式已结构化（dict），直接保留
    def _migrate_skill_entry(s):
        return s if isinstance(s, dict) else _cn_to_en(s, _SKILL_CN_TO_EN)

    if "skills" in info and isinstance(info["skills"], list):
        info["skills"] = [_migrate_skill_entry(s) for s in info["skills"]]

    # saving_throws
    if "saving_throws" in info and isinstance(info["saving_throws"], list):
        info["saving_throws"] = [_migrate_skill_entry(s) for s in info["saving_throws"]]

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
        info_path = path / "info.json"
        if not info_path.exists():
            raise ValueError(f"存档「{path.name}」缺少 info.json（空壳存档），无法读取")
        info = json.loads(info_path.read_text(encoding="utf-8"))
        info = _migrate_char_data(info)
        char = Character(**info)

        # 先读资源策略并恢复目录（运行时定义先于背包迁移加载，guid 才可解析）
        history_path = path / "history.json"
        history_data = None
        resource_mode = "pack"
        resource_pack = ""
        if history_path.exists():
            data = json.loads(history_path.read_text(encoding="utf-8"))
            history_data = data
            meta = data.get("meta") or {}
            resource_mode = meta.get("resource_mode", "pack")
            resource_pack = meta.get("resource_pack", "")
        from resource.packs import configure_resource_catalogs
        configure_resource_catalogs(resource_mode, resource_pack or "default-dnd")
        _restore_runtime_defs(path)

        _migrate_load_inventory(path, char)
        gm = GameMaster(char)
        tmpl_path = path / "character_template.json"
        if tmpl_path.exists():
            gm.character_template = json.loads(tmpl_path.read_text(encoding="utf-8"))
        gm.resource_mode = resource_mode
        gm.resource_pack = resource_pack
        if history_data:
            gm.compressed_history = history_data.get("compressed", [])
            gm.last_assistant = history_data.get("last_assistant", "")
            meta = history_data.get("meta", {})
            gm.last_scene = meta.get("last_scene", "")
            gm.last_scene_detail = meta.get("last_scene_detail", "")
            gm.last_time = meta.get("last_time", "")
            setting_stem = meta.get("setting_stem", "")
            if setting_stem:
                gm.setting_stem = setting_stem
                from core.world_bg import load_world_background
                gm.setting_content = load_world_background(setting_stem)
            gm.story_pack_id = meta.get("story_pack_id", "")
            gm.story_pack_content = meta.get("story_pack_content", "")
            gm.world_source = meta.get("world_source", "llm")
        from world.world import world_from_dict, World
        world_path = path / "world.json"
        gm.world_state = world_from_dict(
            json.loads(world_path.read_text(encoding="utf-8"))
        ) if world_path.exists() else World()
        from core.rounds.initiative import Initiative
        init_meta = (history_data.get("meta", {}) if history_data else {}).get("initiative")
        gm.initiative = Initiative.from_dict(init_meta, gm.character)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        char_data = _migrate_char_data(data.get("character", data))
        char = Character(**char_data)
        _migrate_old_inventory(char)
        gm = GameMaster(char)
        from resource.packs import configure_resource_catalogs
        configure_resource_catalogs("pack")
        if "history" in data:
            gm.set_history(data["history"])
        if "last_scene" in data:
            gm.last_scene = data["last_scene"]
        if "last_scene_detail" in data:
            gm.last_scene_detail = data["last_scene_detail"]
        if "last_time" in data:
            gm.last_time = data["last_time"]
        from world.state import WorldState
        gm.world_state = WorldState()
    gm.save_slot = path.name if path.is_dir() else path.stem
    console.print(f"[grey50]已加载: {path.stem}[/grey50]")
    return gm


# ---------- 日志 ----------

def format_elapsed(seconds: float) -> str:
    """耗时格式化：<60s 显示秒，否则分秒，≥1h 加小时。"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    minutes = int(seconds // 60)
    secs = round(seconds - minutes * 60)
    if minutes < 60:
        return f"{minutes}分{secs}秒"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}小时{mins}分{secs}秒"

def log_dm_response(round_num: int, player_input: str, response_text: str,
                    raw_text: str = "", change_messages: str = "",
                    tool_log: str = "", tag: str = "",
                    system_prompt: str = "", tools_summary: str = ""):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = _time.strftime("%Y%m%d_%H%M%S")
    tag_part = f"_{tag}" if tag else ""
    path = LOG_DIR / f"round_{round_num:03d}{tag_part}_{ts}.txt"
    sep = "\n" + "-" * 70 + "\n"

    parts = [f"========== 第 {round_num} 轮 {tag} | {ts} =========="]

    # -------------- 上行：请求 --------------
    parts.append(sep + "[ ↑ 请求 ]" + sep)
    if system_prompt:
        prompt_short = "\n".join(system_prompt.splitlines()[:120])
        parts.append(f"系统提示词 ({len(system_prompt)} chars, 截取前120行):\n{prompt_short}")
    if tools_summary:
        parts.append(f"\n可用工具: {tools_summary}")
    parts.append(f"\n玩家输入: {player_input}")

    # -------------- 下行：LLM 原始返回 --------------
    parts.append(sep + "[ ↓ LLM 返回 ]" + sep)
    parts.append(raw_text if raw_text else "(空)")

    # -------------- 下行：工具调用 --------------
    if tool_log:
        parts.append(sep + "[ ↓ 工具调用 ]" + sep)
        for line in tool_log.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                import json as _json
                entry = _json.loads(line)
                tool_name = entry.get("tool", "?")
                params = entry.get("args", {})
                ok = entry.get("ok", False)
                reply = entry.get("reply", "")
                if reply:
                    try:
                        reply_data = _json.loads(reply)
                        reply = reply_data.get("message", reply[:80])
                    except Exception:
                        reply = reply[:80]
                status = "✓" if ok else "✗"
                params_short = ", ".join(
                    f"{k}={v}" for k, v in params.items()
                    if k not in ("reason", "note") and v
                )
                reason = params.get("reason", "")
                parts.append(f"  {status} {tool_name}({params_short})")
                if reason:
                    parts.append(f"         理由: {reason}")
                if reply:
                    parts.append(f"         结果: {reply}")
            except Exception:
                parts.append(f"  {line}")
    else:
        parts.append(sep + "[ ↓ 工具调用 ]" + sep + "(无)")

    # -------------- 下行：处理后文本 --------------
    parts.append(sep + "[ ↓ 处理后 ]" + sep)
    parts.append(response_text)

    # -------------- 结算日志 --------------
    if change_messages:
        parts.append(sep + "[ 结算 ]" + sep)
        parts.append(change_messages)

    path.write_text("\n".join(parts), encoding="utf-8")


# ---------- 游戏循环 ----------

def game_loop(gm: GameMaster):
    """入口壳：委托给 core/rounds 的 GameRound（回合大循环）。"""
    from core.rounds.game_round import GameRound
    return GameRound(gm).run()
