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
                requests.append({"action": "unknown", "name": name})
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

        npc_add_m = re.match(
            r'npc_add\s*[:：]\s*(.+?)(?:,\s*AC:\s*(\d+))?(?:,\s*HP:\s*(\d+)/(\d+))?(?:,\s*\[(.+?)\])?$',
            line, re.IGNORECASE
        )
        if npc_add_m:
            name = npc_add_m.group(1).strip()
            ac = int(npc_add_m.group(2)) if npc_add_m.group(2) else 10
            hp = int(npc_add_m.group(3)) if npc_add_m.group(3) else 8
            max_hp = int(npc_add_m.group(4)) if npc_add_m.group(4) else hp
            tag = npc_add_m.group(5) or "中立"
            requests.append({
                "action": "npc_add",
                "name": name, "ac": ac,
                "hp": hp, "max_hp": max_hp,
                "attitude": tag,
            })
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
