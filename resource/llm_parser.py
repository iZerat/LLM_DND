from __future__ import annotations
import re
from typing import Optional
from resource.manager import ResourceManager, ResourceResult
from resource.item_db import item_db

_SLOT_CN_TO_EN: dict[str, str] = {
    "武器": "weapon",
    "副手": "off_hand",
    "头部": "head",
    "身体": "body",
    "背部": "back",
    "项链": "neck",
    "戒指1": "ring1",
    "戒指2": "ring2",
}

PARSED = list[dict]


def _resolve_slot(slot_cn: str) -> Optional[str]:
    return _SLOT_CN_TO_EN.get(slot_cn)


# ── [物品变更] 解析：物品 + 货币 ──

def parse_item_add_value(value: str) -> dict:
    """解析 item_add 行，转换为字段字典。"""
    fields = parse_key_value_form(value)
    return {"action": "item_add", "fields": fields}


def parse_item_changes(text: str) -> Optional[list[dict]]:
    m = re.search(
        r'\[物品变更\]\s*\n(.*?)(?=\n\[|\Z)',
        text, re.DOTALL
    )
    if not m:
        return None
    block = m.group(1).strip()
    requests = []

    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue

        item_add_m = re.match(r"item_add\s*[:：]\s*(.+)", line, re.IGNORECASE)
        if item_add_m:
            requests.append(parse_item_add_value(item_add_m.group(1)))
            continue

        # ── gold ──
        gold_m = re.match(r'金币\s*[:：]\s*([+-])(\d+)', line)
        if gold_m:
            sign = 1 if gold_m.group(1) == "+" else -1
            requests.append({
                "action": "currency_add" if sign > 0 else "currency_remove",
                "amount": abs(int(gold_m.group(2))) * 10000,
            })
            continue

        silver_m = re.match(r'银币\s*[:：]\s*([+-])(\d+)', line)
        if silver_m:
            sign = 1 if silver_m.group(1) == "+" else -1
            requests.append({
                "action": "currency_add" if sign > 0 else "currency_remove",
                "amount": abs(int(silver_m.group(2))) * 100,
            })
            continue

        copper_m = re.match(r'铜[币板]\s*[:：]\s*([+-])(\d+)', line)
        if copper_m:
            sign = 1 if copper_m.group(1) == "+" else -1
            requests.append({
                "action": "currency_add" if sign > 0 else "currency_remove",
                "amount": abs(int(copper_m.group(2))),
            })
            continue

        cp_m = re.match(r'cp\s*[:：]\s*([+-])(\d+)', line, re.IGNORECASE)
        if cp_m:
            sign = 1 if cp_m.group(1) == "+" else -1
            requests.append({
                "action": "currency_add" if sign > 0 else "currency_remove",
                "amount": abs(int(cp_m.group(2))),
            })
            continue

        # ── items ──
        item_m = re.match(r'([+-])\s*(.+?)(?:\s*x(\d+))?\s*(?:（(.+?)）)?\s*$', line)
        if item_m:
            sign = item_m.group(1)
            name = item_m.group(2).strip()
            qty = int(item_m.group(3)) if item_m.group(3) else 1
            slot_cn = item_m.group(4)

            item_def = item_db.find_by_name(name) or item_db.find_by_alias(name) or item_db.find_best(name)
            if not item_def:
                requests.append({"action": "unknown", "name": name, "quantity": qty})
                continue

            if sign == "+":
                req = {"action": "add", "guid": item_def.guid, "quantity": qty}
                if slot_cn:
                    slot_en = _resolve_slot(slot_cn)
                    if slot_en is None:
                        requests.append({"action": "unknown", "name": f"未知槽位: {slot_cn}"})
                        continue
                    requests.append(req)
                    requests.append({"action": "equip", "slot": slot_en, "guid": item_def.guid})
                else:
                    requests.append(req)
            else:
                requests.append({"action": "remove", "guid": item_def.guid, "quantity": qty})

    return requests


# ── [状态变更] 解析：HP / NPC / target ──

_FORM_KEY_ALIASES: dict[str, str] = {
    "名称": "name", "英文名": "name_en", "种族": "species", "职业": "char_class",
    "等级": "level", "生命值": "hp", "最大生命值": "max_hp", "护甲": "ac", "护甲等级": "ac",
    "力量": "strength", "敏捷": "dexterity", "体质": "constitution",
    "智力": "intelligence", "感知": "wisdom", "魅力": "charisma",
    "熟练加值": "proficiency_bonus", "技能": "skills", "豁免": "saving_throws",
    "态度": "attitude", "携带物品": "items", "物品": "items",
    "标签": "tags", "描述": "description", "别名": "aliases",
    "类型": "type", "价值": "value_cp", "价值(铜币)": "value_cp",
    "伤害骰": "damage_dice", "伤害类型": "damage_type", "武器类别": "weapon_category",
    "武器射程": "weapon_range", "特性": "properties", "基础护甲": "base_ac",
    "敏捷上限": "dex_cap", "力量需求": "strength_req", "护甲类别": "armor_category",
    "治疗骰": "heal_dice", "治疗加成": "heal_bonus", "效果": "effect",
}

_FORM_LIST_KEYS = {"skills", "saving_throws", "items", "tags", "properties", "aliases"}


def parse_key_value_form(value: str) -> dict:
    """把一行 key=value / key:value 表单解析为字段字典。

    兼容 [敌意] 态度标签、以及紧跟列表字段的裸词片段（补全列表）。
    """
    fields: dict[str, str] = {}
    last_list_key: Optional[str] = None

    for seg in value.split(","):
        seg = seg.strip()
        if not seg:
            continue
        m = re.match(r"^(.+?)\s*=\s*(.+)$", seg)
        key = val = None
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
        else:
            m2 = re.match(r"^(.+?)\s*[:：]\s*(.+)$", seg)
            if m2:
                key, val = m2.group(1).strip(), m2.group(2).strip()
        if key and val:
            tag_m = re.match(r"^\[(.+)\]$", val)
            if tag_m:
                val = tag_m.group(1)
            key = _FORM_KEY_ALIASES.get(key, key).lower()
            if key == "ac":
                fields["ac"] = val
            elif key == "hp":
                if "/" in val:
                    hp_part, _, max_part = val.partition("/")
                    fields["hp"] = hp_part.strip()
                    fields.setdefault("max_hp", max_part.strip())
                else:
                    fields["hp"] = val
            elif key == "max_hp":
                fields["max_hp"] = val
            else:
                fields[key] = val
            last_list_key = key if key in _FORM_LIST_KEYS else None
            continue
        tag_m = re.match(r"^\[(.+)\]$", seg)
        if tag_m:
            fields["attitude"] = tag_m.group(1)
            continue
        if last_list_key and last_list_key in fields:
            fields[last_list_key] = fields[last_list_key] + "/" + seg
        else:
            fields.setdefault("name", seg)
            last_list_key = None

    return fields


def parse_npc_add_value(value: str) -> dict:
    """解析一行 npc_add 的取值部分，统一转换为字段字典。

    兼容两种写法：
      紧凑: 哥布林, AC: 15, HP: 7/7, [敌意]
      填表: name=凯拉, species=精灵, hp=24, skills=隐匿/察觉, attitude=友好
    """
    return {"action": "npc_add", "fields": parse_key_value_form(value)}


def parse_status_changes(text: str) -> Optional[list[dict]]:
    m = re.search(
        r'\[状态变更\]\s*\n(.*?)(?=\n\[|\Z)',
        text, re.DOTALL
    )
    if not m:
        return None
    block = m.group(1).strip()
    requests = []

    target_name: Optional[str] = None

    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue

        target_m = re.match(r'target\s*[:：]\s*(.+)', line, re.IGNORECASE)
        if target_m:
            target_name = target_m.group(1).strip()
            requests.append({"action": "set_target", "name": target_name})
            continue

        npc_add_m = re.match(r"npc_add\s*[:：]\s*(.+)", line, re.IGNORECASE)
        if npc_add_m:
            req = parse_npc_add_value(npc_add_m.group(1))
            name = req["fields"].get("name", "").strip()
            requests.append(req)
            target_name = name
            continue

        thp_m = re.match(r'target_hp\s*[:：]\s*([+-])(\d+)', line, re.IGNORECASE)
        if thp_m:
            sign = 1 if thp_m.group(1) == "+" else -1
            requests.append({
                "action": "target_hp_add" if sign > 0 else "target_hp_remove",
                "amount": abs(int(thp_m.group(2))),
                "target": target_name,
            })
            continue

        tcp_m = re.match(r'target_cp\s*[:：]\s*([+-])(\d+)', line, re.IGNORECASE)
        if tcp_m:
            sign = 1 if tcp_m.group(1) == "+" else -1
            requests.append({
                "action": "target_cp_add" if sign > 0 else "target_cp_remove",
                "amount": abs(int(tcp_m.group(2))),
                "target": target_name,
            })
            continue

        hp_m = re.match(r'hp\s*[:：]\s*([+-])(\d+)', line, re.IGNORECASE)
        if hp_m:
            sign = 1 if hp_m.group(1) == "+" else -1
            requests.append({
                "action": "hp_add" if sign > 0 else "hp_remove",
                "amount": abs(int(hp_m.group(2))),
            })
            continue

        maxhp_m = re.match(r'max_hp\s*[:：]\s*([+-])(\d+)', line, re.IGNORECASE)
        if maxhp_m:
            sign = 1 if maxhp_m.group(1) == "+" else -1
            requests.append({
                "action": "maxhp_add" if sign > 0 else "maxhp_remove",
                "amount": abs(int(maxhp_m.group(2))),
            })
            continue

    return requests
