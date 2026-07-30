from __future__ import annotations
import re
from typing import Optional
from resource.manager import ResourceManager, ResourceResult
from resource.item_db import item_db

# Chinese -> English slot mapping (reverse lookup from loc table)
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

        gold_m = re.match(r'金币\s*[:：]\s*([+-])(\d+)', line)
        if gold_m:
            sign = 1 if gold_m.group(1) == "+" else -1
            amount = int(gold_m.group(2)) * 100
            requests.append({
                "action": "currency_add" if sign > 0 else "currency_remove",
                "amount": abs(amount),
            })
            continue

        silver_m = re.match(r'银币\s*[:：]\s*([+-])(\d+)', line)
        if silver_m:
            sign = 1 if silver_m.group(1) == "+" else -1
            amount = int(silver_m.group(2)) * 10
            requests.append({
                "action": "currency_add" if sign > 0 else "currency_remove",
                "amount": abs(amount),
            })
            continue

        copper_m = re.match(r'铜币\s*[:：]\s*([+-])(\d+)', line)
        if copper_m:
            sign = 1 if copper_m.group(1) == "+" else -1
            amount = int(copper_m.group(2))
            requests.append({
                "action": "currency_add" if sign > 0 else "currency_remove",
                "amount": abs(amount),
            })
            continue

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


def try_process_changes(manager: ResourceManager, text: str, max_retries: int = 3) -> tuple[str, list[ResourceResult]]:
    requests = parse_item_changes(text)
    if requests is None:
        return text, []
    unknown = [r for r in requests if r["action"] == "unknown"]
    if unknown:
        missing_names = [r["name"] for r in unknown]
        msg = "未找到的物品: " + ", ".join(missing_names)
        return text, [ResourceResult.fail(msg)]
    results = manager.process_requests(requests)
    clean = re.sub(
        r'\n?\[物品变更\].*?(?=\n\[|\Z)',
        '', text, count=1, flags=re.DOTALL
    ).strip()
    return clean, results
