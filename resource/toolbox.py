"""资源调节工具箱：把调节器（Regulator）暴露为 OpenAI function-calling 工具。

所有数据变更仍由调节器唯一执行；工具只是让大模型以结构化参数主动调用
调节器（银行柜台），[物品变更]/[状态变更] 文本区块已彻底废除（D6）。
参数 schema 由 ResourceSchema 自动生成（create_npc / create_item）。
"""

from __future__ import annotations
import json

from resource.models import ItemDef
from resource.objects import NPCTemplate, ResourceSchema
from resource.packs import RESOURCE_MODE_PACK
from resource.manager import ResourceResult
from resource.checker import Checker, _tool, _tool_reply

_SLOTS = ["weapon", "body", "off_hand", "head", "back", "neck", "ring1", "ring2"]


# 数据变更工具：必须携带 reason（叙事理由），缺失 → 拒绝执行（D5/T5/T7）
_REASON_REQUIRED_TOOLS = {
    "change_status", "grant_item", "remove_item", "change_currency",
    "change_attitude", "create_npc", "create_item",
}
_REASON_DESC = "本次数据变更的叙事理由（必填，用于审计与结算日志）"


def _with_reason(schema: dict) -> dict:
    """给工具 schema 追加必填 reason 参数（就地修改并返回）。"""
    props = schema.setdefault("properties", {})
    props["reason"] = {"type": "string", "description": _REASON_DESC}
    req = schema.setdefault("required", [])
    if "reason" not in req:
        req.append("reason")
    return schema


def _reason_error(name: str) -> str:
    return _tool_reply(False, f"{name} 缺少必填的 reason（数据变更理由），已拒绝执行")


class ResourceToolbox:
    def __init__(self, regulator, checker: Checker | None = None):
        self.regulator = regulator
        self.manager = regulator.manager
        self.checker = checker or Checker(
            self.manager.character, self.manager.world, self.manager,
        )
        self.results: list[str] = []
        self.check_results: list[dict] = []
        self.tool_call_log: list[str] = []

    # ── 工具定义（由 ResourceSchema 自动生成）──

    def schemas(self) -> list[dict]:
        mode = self.manager.resource_mode
        npc_params = _with_reason(NPCTemplate.schema().to_json_schema())
        item_params = _with_reason(ItemDef.schema().to_json_schema())
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
                  _with_reason({
                      "type": "object", "properties": {
                          "item": {"type": "string", "description": "物品名称"},
                          "quantity": {"type": "integer", "minimum": 1, "default": 1},
                          "slot": {"type": "string", "description": "可选装备槽位",
                                   "enum": _SLOTS},
                      }, "required": ["item"]})),
            _tool("remove_item",
                  "从玩家背包移除物品。",
                  _with_reason({
                      "type": "object", "properties": {
                          "item": {"type": "string", "description": "物品名称"},
                          "quantity": {"type": "integer", "minimum": 1, "default": 1},
                      }, "required": ["item"]})),
            _tool("change_currency",
                  "增减玩家金钱，单位统一为铜币（cp）。正数加钱，负数扣钱。",
                  _with_reason({
                      "type": "object", "properties": {
                          "amount_cp": {"type": "integer",
                                        "description": "增减量（铜币），正数加钱，负数扣钱"},
                      }, "required": ["amount_cp"]})),
            _tool("set_target",
                  "指定当前战斗/交互目标 NPC。对目标改动前请先调用。",
                  {"type": "object", "properties": {
                      "name": {"type": "string"},
                  }, "required": ["name"]}),
            _tool("change_status",
                  "修改玩家或 NPC 的生命值。target 传「玩家」或 NPC 名称。",
                  _with_reason({
                      "type": "object", "properties": {
                          "target": {"type": "string", "description": "玩家 或 NPC 名称"},
                          "hp": {"type": "integer", "description": "HP 增减量：正数治疗、负数伤害"},
                          "max_hp": {"type": "integer", "description": "最大HP 增减量"},
                      }, "required": ["target"]})),
            _tool("change_attitude",
                  "调整某 NPC 对玩家的敌对/友好态度（-100..+100：负数=变敌对，正数=变友好）。"
                  "攻击、威胁、偷窃、侮辱等敌对行为应传负数；帮助、赠送、治疗应传正数。",
                  _with_reason({
                      "type": "object", "properties": {
                          "target": {"type": "string", "description": "NPC 名称"},
                          "delta": {"type": "integer",
                                    "description": "态度变化量，负=更敌对，正=更友好"},
                      }, "required": ["target", "delta"]})),
            self.checker.tool_schema(),
        ]

    # ── 执行入口 ──

    def execute(self, name: str, arguments: dict) -> str:
        m = self.manager
        try:
            if name in _REASON_REQUIRED_TOOLS and not str(arguments.get("reason", "") or "").strip():
                reply = _reason_error(name)
                self._log_call(name, arguments, False, reply)
                return reply
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
            elif name == "change_attitude":
                tgt_name = str(arguments.get("target", "")).strip()
                delta = int(arguments.get("delta") or 0)
                err = m.consume_pending_baseline(tgt_name, delta)
                if err:
                    result = err
                else:
                    result = m.change_attitude(
                        tgt_name, delta,
                        reason=str(arguments.get("reason", "") or ""),
                    )
            elif name == "d20_test":
                result = self.checker._d20_test(arguments)
                if result.success and result.data:
                    test = (result.data.get("test") or {})
                    if test.get("display"):
                        self.check_results.append({
                            "target": test.get("actor", ""),
                            "text": test["display"],
                            "success": bool(test.get("success", False)),
                        })
                    for msg in (test.get("changes") or []):
                        self.results.append(msg)
            else:
                return _tool_reply(False, f"未知工具: {name}")
        except Exception as e:
            reply = _tool_reply(False, f"工具执行异常: {e}")
            self._log_call(name, arguments, False, reply)
            return reply
        if result.success and result.visible and result.message:
            self.results.append(result.message)
        reply = _tool_reply(result.success, result.message, result.data)
        self._log_call(name, arguments, result.success, reply)
        return reply

    def _log_call(self, name: str, arguments: dict, ok: bool, reply: str) -> None:
        """记录一次工具调用（含参数与 reason），供审计日志（T7）。"""
        self.tool_call_log.append(
            json.dumps(
                {"tool": name, "args": arguments, "ok": ok, "reply": reply},
                ensure_ascii=False,
            )
        )

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
        if hp < 0:
            err = m.consume_pending_damage(target, hp)
            if err:
                return err
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
        return m.npc_change_status(target, hp=hp, max_hp=max_hp)
