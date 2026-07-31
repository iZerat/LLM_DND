"""资源调节工具箱：把调节器（Regulator）暴露为 OpenAI function-calling 工具。

所有数据变更仍由调节器唯一执行；工具只是让大模型以结构化参数主动调用
调节器（银行柜台），替代手写 [物品变更]/[状态变更] 文本区块。
参数 schema 由 ResourceSchema 自动生成（create_npc / create_item）。
"""

from __future__ import annotations
import json
import random
from typing import Optional

from resource.models import ItemDef
from resource.objects import NPCTemplate, ResourceSchema
from resource.packs import RESOURCE_MODE_PACK
from resource.manager import ResourceResult
from core.character import modifier

_ABILITY_KEYS = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
_ABILITY_CN = {
    "strength": "力量", "dexterity": "敏捷", "constitution": "体质",
    "intelligence": "智力", "wisdom": "感知", "charisma": "魅力",
}
_KIND_CN = {"attack": "攻击", "save": "豁免", "check": "检定"}


def _tool(name: str, description: str, parameters: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def _tool_reply(success: bool, message: str, data: dict | None = None) -> str:
    payload = {"ok": success, "message": message}
    if data:
        payload.update(data)
    return json.dumps(payload, ensure_ascii=False)


_SLOTS = ["weapon", "body", "off_hand", "head", "back", "neck", "ring1", "ring2"]


class ResourceToolbox:
    def __init__(self, regulator):
        self.regulator = regulator
        self.manager = regulator.manager
        self.results: list[str] = []
        self.check_results: list[dict] = []

    # ── 工具定义（由 ResourceSchema 自动生成）──

    def schemas(self) -> list[dict]:
        mode = self.manager.resource_mode
        npc_params = NPCTemplate.schema().to_json_schema()
        item_params = ItemDef.schema().to_json_schema()
        npc_desc = (
            "创建 NPC。查表创建模式：按 name 在资源库查询生成，name 必须真实存在；"
            "填表创建模式：按表单字段创建，属性需贴合世界背景设定。创建后会自动设为目标。"
        )
        return [
            _tool("create_npc", npc_desc, npc_params),
            _tool("create_item",
                  "填表创建新物品（仅填表创建模式可用）。创建后如需放进背包，再调用 grant_item。",
                  item_params),
            _tool("grant_item",
                  "给玩家添加物品（物品名需存在于资源库，或用 create_item 创建过的名称）。",
                  {"type": "object", "properties": {
                      "item": {"type": "string", "description": "物品名称"},
                      "quantity": {"type": "integer", "minimum": 1, "default": 1},
                      "slot": {"type": "string", "description": "可选装备槽位",
                               "enum": _SLOTS},
                  }, "required": ["item"]}),
            _tool("remove_item",
                  "从玩家背包移除物品。",
                  {"type": "object", "properties": {
                      "item": {"type": "string", "description": "物品名称"},
                      "quantity": {"type": "integer", "minimum": 1, "default": 1},
                  }, "required": ["item"]}),
            _tool("change_currency",
                  "增减玩家金钱，单位统一为铜币（cp）。正数加钱，负数扣钱。",
                  {"type": "object", "properties": {
                      "amount_cp": {"type": "integer",
                                    "description": "增减量（铜币），正数加钱，负数扣钱"},
                  }, "required": ["amount_cp"]}),
            _tool("set_target",
                  "指定当前战斗/交互目标 NPC。对目标改动前请先调用。",
                  {"type": "object", "properties": {
                      "name": {"type": "string"},
                  }, "required": ["name"]}),
            _tool("change_status",
                  "修改玩家或 NPC 的生命值。target 传「玩家」或 NPC 名称。",
                  {"type": "object", "properties": {
                      "target": {"type": "string", "description": "玩家 或 NPC 名称"},
                      "hp": {"type": "integer", "description": "HP 增减量：正数治疗、负数伤害"},
                      "max_hp": {"type": "integer", "description": "最大HP 增减量"},
                  }, "required": ["target"]}),
            _tool("target_check",
                  "为目标NPC执行本地检定（攻击/豁免/属性检定），骰子由系统在本机掷出并直接判定。"
                  "攻击检定对玩家AC；豁免/属性检定对给定DC。收到返回的判定结果后，"
                  "必须在[副事件]区块中描述结果。",
                  {"type": "object", "properties": {
                      "checks": {"type": "array", "items": {
                          "type": "object",
                          "properties": {
                              "target": {"type": "string", "description": "目标NPC名称"},
                              "kind": {"type": "string", "enum": ["attack", "save", "check"],
                                       "description": "attack=攻击检定（对玩家AC）；save=豁免检定；check=属性检定"},
                              "ability": {"type": "string", "enum": _ABILITY_KEYS,
                                          "description": "所用属性（save/check 必填；attack 缺省取力量/敏捷较高者）"},
                              "dc": {"type": "integer", "minimum": 1,
                                     "description": "save/check 的目标DC"},
                              "note": {"type": "string",
                                       "description": "检定说明（如：对玩家发动攻击、躲避落石）"},
                          },
                          "required": ["target", "kind"],
                      }},
                  }, "required": ["checks"]}),
        ]

    # ── 执行入口 ──

    def execute(self, name: str, arguments: dict) -> str:
        m = self.manager
        try:
            if name == "create_npc":
                result = m.npc_add(arguments)
            elif name == "create_item":
                result = m.item_add(arguments)
            elif name == "grant_item":
                result = self._grant_item(arguments)
            elif name == "remove_item":
                result = self._remove_item(arguments)
            elif name == "change_currency":
                result = self._change_currency(arguments)
            elif name == "set_target":
                result = m.set_target(str(arguments.get("name", "")).strip())
            elif name == "change_status":
                result = self._change_status(arguments)
            elif name == "target_check":
                result = self._target_check(arguments)
            else:
                return _tool_reply(False, f"未知工具: {name}")
        except Exception as e:
            return _tool_reply(False, f"工具执行异常: {e}")
        if result.success and result.visible and result.message:
            self.results.append(result.message)
        return _tool_reply(result.success, result.message, result.data)

    # ── 具体工具实现 ──

    def _grant_item(self, arguments: dict) -> ResourceResult:
        name = str(arguments.get("item", "")).strip()
        qty = int(arguments.get("quantity") or 1)
        item = self.manager.resolve_item(name)
        if not item:
            return ResourceResult.fail(f"物品「{name}」不在资源库中")
        result = self.manager.add_item(item.guid, qty)
        slot = arguments.get("slot")
        if slot and result.success:
            eq = self.manager.equip(str(slot).strip(), item.guid)
            if eq.success:
                return ResourceResult.ok(f"{result.message}（{eq.message}）")
        return result

    def _remove_item(self, arguments: dict) -> ResourceResult:
        name = str(arguments.get("item", "")).strip()
        qty = int(arguments.get("quantity") or 1)
        item = self.manager.resolve_item(name)
        if not item:
            return ResourceResult.fail(f"物品「{name}」不在资源库中")
        return self.manager.remove_item(item.guid, qty)

    def _change_currency(self, arguments: dict) -> ResourceResult:
        amount = int(arguments.get("amount_cp") or 0)
        if amount == 0:
            return ResourceResult.fail("amount_cp 不能为 0")
        if amount > 0:
            return self.manager.add_currency(amount)
        return self.manager.remove_currency(-amount)

    def _change_status(self, arguments: dict) -> ResourceResult:
        target = str(arguments.get("target", "")).strip()
        hp = int(arguments.get("hp") or 0)
        max_hp = int(arguments.get("max_hp") or 0)
        m = self.manager
        if target == "玩家":
            parts = []
            if hp:
                res = m.add_hp(hp) if hp > 0 else m.remove_hp(-hp)
                if res.success:
                    parts.append(res.message)
                else:
                    return res
            if max_hp:
                res = m.add_maxhp(max_hp) if max_hp > 0 else m.remove_maxhp(-max_hp)
                if res.success:
                    parts.append(res.message)
                else:
                    return res
            return ResourceResult.ok("，".join(parts) if parts else "无变化")
        npc = m.world.get_by_name(target) if m.world else None
        if not npc:
            return ResourceResult.fail(f"未找到目标 NPC「{target}」，请先用 create_npc / set_target")
        parts = []
        if hp:
            npc.hp = max(min(npc.hp + hp, npc.max_hp), 0)
            parts.append(f"目标 {npc.name} HP {hp:+d}点")
        if max_hp:
            npc.max_hp = max(npc.max_hp + max_hp, 1)
            npc.hp = min(npc.hp, npc.max_hp)
            parts.append(f"目标 {npc.name} 最大HP {max_hp:+d}点")
        return ResourceResult.ok("，".join(parts) if parts else "无变化")

    # ── 目标检定：本地掷骰，结果回填 LLM（副事件块）──

    def _target_check(self, arguments: dict) -> ResourceResult:
        checks = arguments.get("checks") or []
        if not checks:
            return ResourceResult.fail("target_check 缺少 checks")
        player = self.manager.character
        payload: list[dict] = []
        for c in checks:
            name = str(c.get("target", "")).strip()
            kind = str(c.get("kind", "check")).strip().lower()
            if kind not in _KIND_CN:
                kind = "check"
            ability = str(c.get("ability", "")).strip().lower()
            note = str(c.get("note", "")).strip()
            dc = c.get("dc")
            npc = self.manager.world.get_by_name(name) if self.manager.world else None
            if not npc:
                payload.append({"ok": False, "target": name, "message": f"未找到目标 NPC「{name}」"})
                continue
            if ability not in _ABILITY_KEYS:
                if kind == "attack":
                    ability = "strength" if npc.strength >= npc.dexterity else "dexterity"
                else:
                    ability = "dexterity"
            ab_mod = modifier(getattr(npc, ability))
            prof = npc.proficiency_bonus or 0
            has_prof = kind == "attack" or (kind == "save" and ability in (npc.saving_throws or []))
            mod = ab_mod + prof if has_prof else ab_mod
            if kind == "attack":
                dc_value = player.ac if player else 10
                dc_kind = "AC"
            else:
                try:
                    dc_value = int(dc) if dc else 10
                except (TypeError, ValueError):
                    dc_value = 10
                dc_kind = "DC"
            roll = random.randint(1, 20)
            total = roll + mod
            nat20 = roll == 20
            nat1 = roll == 1
            success = nat20 or (not nat1 and total >= dc_value)
            if total == dc_value:
                op = "≥"
            elif success:
                op = ">"
            else:
                op = "<"
            if nat20:
                word, word_color = ("暴击" if kind == "attack" else "大成功"), "yellow"
            elif nat1:
                word, word_color = "大失败", "red"
            elif success:
                word, word_color = ("命中" if kind == "attack" else "成功"), "green"
            else:
                word, word_color = ("未命中" if kind == "attack" else "失败"), "red"
            kind_cn = _KIND_CN[kind]
            ability_cn = _ABILITY_CN.get(ability, ability)
            prefix = f"{npc.name} {ability_cn}{kind_cn}" if kind != "attack" else f"{npc.name} 攻击"
            label = "" if kind == "attack" else dc_kind
            text = f"{prefix}: d20({roll}) + ({mod:+d}) = {total} {op} {label}{dc_value} [{word_color}]{word}[/{word_color}]"
            if note:
                text += f"\n[grey50]{note}[/grey50]"
            self.check_results.append({"target": npc.name, "text": text, "success": success})
            payload.append({
                "ok": True,
                "target": npc.name, "kind": kind, "kind_cn": kind_cn,
                "ability": ability, "ability_cn": ability_cn,
                "dc": dc_value, "dc_kind": dc_kind,
                "roll": roll, "modifier": mod, "total": total,
                "success": success, "natural_20": nat20, "natural_1": nat1,
                "note": note,
            })
        return ResourceResult(True, "", {"checks": payload}, visible=False)
