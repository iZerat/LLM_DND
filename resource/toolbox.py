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
    "change_attitude", "create_npc", "create_item", "use_item",
    "create_scene", "create_object", "create_choice",
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
        # 工具落账范围："dm"=全权（默认）；"player"=玩家回合段——
        # 该段内禁止落账非玩家发起的伤害，防止 LLM 抢先结算 NPC 攻击、
        # 随后 NPC 段系统再结算一次（双重结算）。
        self._settle_scope = "dm"

    # ── 工具定义（由 ResourceSchema 自动生成）──

    def schemas(self) -> list[dict]:
        mode = self.manager.resource_mode
        npc_params = _with_reason(NPCTemplate.schema().to_json_schema())
        item_params = _with_reason(ItemDef.schema().to_json_schema())
        npc_desc = (
            "创建 NPC。查表创建模式：请先调用 search_resource 查询目录中存在的名称；"
            "确认 name 存在后调用本工具创建。未命中的名称会被拒绝，可换表述重试。"
            "若系统告知已达到重试上限且已开启自由创建回退，则允许填表直接创建。"
            "创建后自动设为目标。"
        )
        return [
            _tool("search_resource",
                  "查询本地资源目录（NPC/物品）。传入关键词进行模糊匹配，"
                  "返回匹配条目的名称、类型、简要信息，**不会倾倒全表**。"
                  "查不到时可换表述重试，或检查 kind 是否匹配。"
                  "创建 NPC 前请先在此确认名称是否存在于目录中。",
                  {"type": "object", "properties": {
                      "query": {"type": "string", "description": "搜索关键词（名称/种族/职业/类型等）"},
                      "kind": {"type": "string", "enum": ["npc", "item"],
                               "description": "限定类型，不传则搜全部"},
                  }, "required": ["query"]}),
            _tool("create_npc", npc_desc, npc_params),
            _tool("create_scene",
                  "建立新场景（位置粒度容器，如城镇/地牢/酒馆）。创建后该场景成为当前场景，"
                  "后续创建的对象/登记的目标归入其中。场景只用于承载与定位，不具备攻击/交易能力。",
                  _with_reason({
                      "type": "object", "properties": {
                          "name": {"type": "string", "description": "场景名称（稳定地名）"},
                          "location": {"type": "string", "description": "位置描述，缺省用名称"},
                          "description": {"type": "string", "description": "场景描述"},
                          "tags": {"type": "array", "items": {"type": "string"},
                                   "description": "标签"},
                      }, "required": ["name"]})),
            _tool("set_environment",
                  "更新当前场景的环境信息与当前世界时间。"
                  "场景字段（地点、温度、天气、氛围等）写入当前场景（/scene 展示）；"
                  "时间字段（年月日、季节、时分秒、时段）写入世界时间（/time 展示）。"
                  "把 DM 输出 [环境] 文字中的字段转为键值对传入，没有的字段不用传。",
                  {"type": "object", "properties": {
                      "fields": {"type": "object",
                                 "description": "环境字段，如 {'地点':'微风港','温度':'15℃（凉爽）','天气':'晴朗','氛围':'潮湿','年月日':'第三年·丰收之月15日','季节':'秋天','时分秒':'8:30','时段':'傍晚'}"},
                  }, "required": ["fields"]}),
            _tool("create_object",
                  "在当前场景创建非角色对象（物品/道具/机关等，非 NPC 非战斗单位）。"
                  "对象只存在于场景中，不影响目标列表，不可攻击/交易。",
                  _with_reason({
                      "type": "object", "properties": {
                          "name": {"type": "string", "description": "对象名称"},
                          "description": {"type": "string", "description": "对象描述"},
                          "tags": {"type": "array", "items": {"type": "string"},
                                   "description": "标签"},
                       }, "required": ["name"]})),
            _tool("create_choice",
                  "创建玩家选择选项。每轮至少创建 3 个选项，让玩家可以选编号或自由输入。"
                  "choice_type: attack=攻击(系统掷攻击检定vs目标AC)、"
                  "ability_check=属性/技能检定(系统掷d20+调整值vs DC)、"
                  "narrative=纯叙事(不掷骰)。target 仅 attack 类型必填。",
                  _with_reason({
                      "type": "object", "properties": {
                          "choice_type": {"type": "string",
                                          "enum": ["attack", "ability_check", "narrative"],
                                          "description": "选项类型"},
                          "label": {"type": "string", "description": "选项文本（如'拔出短剑正面迎战'），必须是中文纯描述，禁止英文整句与括号技术标注（检定类型/目标/DC 由系统渲染）"},
                          "ability": {"type": "string", "description": "所用属性: strength/dexterity/constitution/intelligence/wisdom/charisma"},
                          "dc": {"type": "integer", "minimum": 1,
                                 "description": "难度等级（ability_check 时使用，attack 时忽略）"},
                          "target": {"type": "string", "description": "攻击目标名称（仅 attack 类型填）"},
                          "skill": {"type": "string", "description": "技能名（可选，用于熟练项加成）"},
                      }, "required": ["choice_type", "label"]})),
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
            _tool("use_item",
                  "使用背包中的消耗品（治疗药水等）。自动掷骰计算效果并应用到目标（默认玩家），"
                  "同时从背包扣除对应数量。",
                  _with_reason({
                      "type": "object", "properties": {
                          "item": {"type": "string", "description": "消耗品名称"},
                          "target": {"type": "string",
                                     "description": "作用目标，默认「玩家」"},
                          "quantity": {"type": "integer", "minimum": 1, "default": 1},
                      }, "required": ["item"]})),
            _tool("set_target",
                  "指定当前战斗/交互目标 NPC。对目标改动前请先调用。",
                  {"type": "object", "properties": {
                      "name": {"type": "string"},
                  }, "required": ["name"]}),
            _tool("change_status",
                  "只修改生命值（HP / max_hp），绝不改变态度（态度请用 change_attitude）。"
                  "target 传「玩家」或 NPC 名称；hp 正数=治疗、负数=伤害。"
                  "伤害必须先经 d20_roll 攻击检定，数值必须与判定结果一致，"
                  "且一次攻击只允许落账一次（无检定/数值不符/重复落账都会被拒绝）；"
                  "治疗同一数值在同一轮内也只允许一次。",
                  _with_reason({
                      "type": "object", "properties": {
                          "target": {"type": "string", "description": "玩家 或 NPC 名称"},
                          "hp": {"type": "integer", "description": "HP 增减量：正数治疗、负数伤害"},
                          "max_hp": {"type": "integer", "description": "最大HP 增减量"},
                      }, "required": ["target"]})),
            _tool("change_attitude",
                  "只修改态度（-100..+100，负数=更敌对，正数=更友好），绝不改变生命值"
                  "（HP 请用 change_status）。攻击、威胁、偷窃、侮辱等敌对行为应传负数；"
                  "帮助、赠送、治疗应传正数。每次调用的 delta 为本次净变化量，累积超出 ±100 会被截断；"
                  "同一目标同一数值在一轮内重复调用会被拒绝。",
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
            elif name == "create_scene":
                result = m.create_scene(
                    str(arguments.get("name", "")).strip(),
                    location=str(arguments.get("location", "")).strip(),
                    description=str(arguments.get("description", "")).strip(),
                    tags=arguments.get("tags") or [],
                )
            elif name == "set_environment":
                result = m.set_environment(arguments.get("fields", {}))
            elif name == "create_object":
                result = m.create_object(
                    str(arguments.get("name", "")).strip(),
                    description=str(arguments.get("description", "")).strip(),
                    tags=arguments.get("tags") or [],
                )
            elif name == "create_choice":
                result = m.create_choice(arguments)
            elif name == "search_resource":
                result = m.search_resource(
                    query=str(arguments.get("query", "")).strip(),
                    kind=str(arguments.get("kind", "")).strip().lower(),
                )
            elif name == "create_item":
                result = m.item_add(arguments)
            elif name == "grant_item":
                result = self._grant_item(arguments)
            elif name == "remove_item":
                result = self._remove_item(arguments)
            elif name == "change_currency":
                result = self._change_currency(arguments)
            elif name == "use_item":
                result = m.use_item(
                    str(arguments.get("item", "")).strip(),
                    target=str(arguments.get("target", "") or "玩家").strip(),
                    quantity=int(arguments.get("quantity") or 1),
                )
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
                    err = m.check_change_repeat(tgt_name, "态度", delta)
                    if err:
                        result = err
                    else:
                        result = m.change_attitude(
                            tgt_name, delta,
                            reason=str(arguments.get("reason", "") or ""),
                        )
            elif name == "d20_roll":
                if self.checker is not None:
                    self.checker.settle_scope = self._settle_scope
                result = self.checker._d20_roll(arguments)
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
            return self.manager.grant_item_not_found(name)
        result = self.manager.add_item(item.guid, qty)
        slot = arguments.get("slot")
        if slot and result.success:
            eq = self.manager.equip(str(slot).strip(), item.guid)
            if eq.success:
                return ResourceResult.ok(f"{result.message} | {eq.message}")
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
            if self._settle_scope == "player":
                pending = m.pending_attacks.get(target) or {}
                attacker = pending.get("actor", "")
                if not attacker or not m.is_player_name(attacker):
                    return ResourceResult.fail(
                        f"「{target}」受到的伤害来自{attacker or '未知来源'}的攻击，"
                        f"应在对应 NPC 行动段由系统结算，玩家回合内请勿手动落账"
                    )
            err = m.consume_pending_damage(target, hp)
            if err:
                return err
        elif hp > 0:
            err = m.check_change_repeat(target, "治疗", hp)
            if err:
                return err
        if max_hp:
            err = m.check_change_repeat(target, "最大HP", max_hp)
            if err:
                return err
        return m.change_status(target, hp=hp, max_hp=max_hp)
