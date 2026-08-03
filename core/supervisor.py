from __future__ import annotations
import re

from core.config import Config
from core.prompt_lib import build_prompt_suffix
from core.ui import console
from resource.regulator import _ITEM_BLOCK_RE, _STATUS_CHANGE_BLOCK_RE
from resource.manager import strip_choice_annotation


def _insert_reminder(text: str, reminder: str) -> str:
    """把 [系统提醒] 插到 [选择] 之前（无 [选择] 则追加到末尾）。"""
    m = re.search(r"\[选择\]", text)
    if m:
        return text[:m.start()] + reminder + "\n\n" + text[m.start():]
    return text.rstrip() + "\n\n" + reminder


# 叙事数值核验：捕获「名称 + 生命/HP/AC/态度 + 数字」的紧邻声明形式
# （如「灰袍老者 生命 24」「目标A AC 15」），数字在关键字之后才算声明；
# 「还剩 24 点生命」这类数字在前的说法不触发，避免把「战前值」误判为冲突。
_NARR_VALUE_RE = re.compile(
    r"(?P<name>[\u4e00-\u9fa5A-Za-z·0-9]{1,8}?)\s*[（(]?\s*"
    r"(?P<kind>HP|最大生命值|最大HP|最大生命|生命值|生命|护甲等级|护甲|AC|态度)\s*[:：]?\s*"
    r"(?P<num>-?\d+)\s*[）)]?"
)

_NARR_KIND_FIELD = {
    "HP": "hp",
    "生命值": "hp",
    "生命": "hp",
    "最大HP": "max_hp",
    "最大生命值": "max_hp",
    "最大生命": "max_hp",
    "AC": "ac",
    "护甲": "ac",
    "护甲等级": "ac",
    "态度": "attitude",
}

# [状态] 已彻底废除（见 design/监督与数据修改路径调查-2026-08-03.md）：
# 目标面板由本地系统从 WorldState 渲染，LLM 输出中残留的 [状态] 一律剥离且不落账。
_STATUS_BLOCK_RE = re.compile(r"\n?\[状态\].*?(?=\n\[|\Z)", re.DOTALL)


class AuditResult:
    """监督者方向B 一轮审核的结果。

    - messages：结构化变更记录（工具落账），只进 [变更] 块；
    - notices：监督者诊断（修复提示/系统提醒），不进终端，仅落日志与 LLM 历史；
    - defects：本轮缺失的关键块（事件/选择），由 dm_call 据此发起补写重试。
    """

    def __init__(self):
        self.text: str = ""
        self.messages: list[str] = []
        self.notices: list[str] = []
        self.repaired: bool = False
        self.defects: list[str] = []


class Supervisor:
    """双向审核器（监督者）。

    方向A — prepare_player_input：玩家输入 → 行为分类（触发词）→ 附加提示词片段
             + 注入世界状态上下文。
    方向B — audit：LLM 输出 → 剥离残余文本变更区块（不落账，数据变更只能经工具）
              → 叙事数值核验 → [事件] 缺块补写 → 返回可显示文本。

    不做任何数据落账：所有写入统一交给调节器（Regulator）。
    """

    REPAIR_SECTION_NAMES = "环境|场景|场景细节|事件|副事件|状态|选择|历史"

    def __init__(self, gm, regulator):
        self.gm = gm
        self.regulator = regulator

    # ── 方向A：玩家输入 → 增强 ──

    def prepare_player_input(self, raw: str) -> str:
        enriched = raw
        suffix = build_prompt_suffix(enriched)
        if suffix:
            enriched += suffix
        ws = self.regulator.world
        if ws:
            ctx = ws.render_context_for_llm(
                self.gm.character.name,
                self.gm.character.ac,
                self.gm.character.hp,
                self.gm.character.max_hp,
                pc_dead=getattr(self.gm.character, "dead", False),
            )
            if ctx:
                enriched += "\n\n" + ctx
        return enriched

    # ── 回合完整性检查 ──

    def check_round_integrity(self, rendered: list[str], round_kind: str,
                               round_num: int, node: str = "") -> list[str]:
        errors = []
        if round_kind == "非战斗":
            required = ["环境", "事件", "状态", "选择"]
        elif node == "prelude":
            required = ["环境", "事件"]  # prelude 只输出这两个
        elif node == "segment":
            required = ["副事件", "状态"]  # 每个 segment 必须输出副事件+状态
        elif node == "player":
            required = ["选择", "状态"]  # 玩家段必须输出选择+状态
        else:
            required = []
        for block in required:
            if block not in rendered:
                label = f"{node} " if node else ""
                errors.append(
                    f"第 {round_num} 轮（{round_kind}）{label}缺少块：{block}"
                )
        # prelude 段完整性：渲染了行动/变更块后必须以目标块（状态）收尾，
        # 否则会与下一个行动段的行动块紧接（小循环要求一段一处理）。
        if node == "prelude" and (
            "行动" in rendered or "变更" in rendered
        ) and "状态" not in rendered:
            errors.append(
                f"第 {round_num} 轮（{round_kind}）prelude 渲染了行动/变更块后缺少目标块（状态）"
            )
        return errors

    def check_player_choice_ready(self, rendered: list[str], round_num: int) -> list[str]:
        """玩家输入前检查：选择块必须已渲染（每次玩家行动前都要有选项可选）。"""
        if "选择" not in rendered:
            return [f"第 {round_num} 轮（战斗）玩家输入前缺少选择块"]
        return []

    # ── 方向B：LLM 输出 → 审核 ──

    def audit(self, raw_text: str, mode: str = "full",
              require_event: bool = False, require_choices: bool = False) -> AuditResult:
        result = AuditResult()

        # 0. 工具通道：已通过工具落账的变更直接展示
        if getattr(self.gm, "last_tool_results", None):
            result.messages.extend(self.gm.last_tool_results)

        # 1. [物品变更]/[状态变更]/[状态] 文本区块已废除（D6）：数据变更只能经工具。
        #    若 LLM 仍输出这些区块，一律剥离且不落账，防止双重结算与幻影落账。
        text = _ITEM_BLOCK_RE.sub("", raw_text.replace("（无需检定）", ""), count=1)
        text = _STATUS_CHANGE_BLOCK_RE.sub("", text, count=1)
        text = _STATUS_BLOCK_RE.sub("", text, count=1)

        # 轻量模式：段内叙事（战斗已由系统机械结算）——只剥离变更区块，不落账，
        # 不校验/修复结构，避免短调用被反复打回。
        if mode == "light":
            result.text = text
            return result

        # 叙事数值核验：[事件]/[副事件] 中若出现「名称 + 生命/AC/态度 + 数字」的
        # 声明形式，必须与真实落账一致；不一致 → [系统提醒] 打回 LLM 改措辞。
        narr_issues = self.verify_narrative_numbers(text)
        if narr_issues:
            reminder = (
                "[系统提醒] 你叙事中的数值与真实数据不符：" + "；".join(narr_issues)
                + "。请按真实数据调整措辞（不得修改真实数值，只能改写叙事）。"
            )
            result.notices.append(reminder)
            text = _insert_reminder(text, reminder)
            self._record_reminder(reminder)

        # 块缺陷检测：只标记缺失，不做修复（修复重试由 dm_call 统一调度）。
        result.defects = self.detect_defects(text, require_event, require_choices)

        # 4. 兜底：剥离本轮选项中残留的括号技术标注（提示词已要求 LLM 不输出，
        #    这里再兜一层，保证玩家看到的选择项只含纯描述文本）
        m = getattr(self.regulator, "manager", None)
        for c in getattr(m, "choices", None) or []:
            c["label"] = strip_choice_annotation(c.get("label", ""))

        result.text = text
        return result

    # ── 叙事数值核验 ──

    def verify_narrative_numbers(self, response_text: str) -> list[str]:
        """核验 [事件]/[副事件] 叙事中声明的 HP/AC/态度数值与真实落账是否一致。

        只检查「名称 + 关键字 + 数字」的紧邻声明形式，返回不一致的问题列表；
        名称无法解析或数值声明形式不标准的一律跳过（避免误伤正常叙事）。
        """
        issues: list[str] = []
        body = ""
        for content in re.findall(
            r"\[(?:事件|副事件)\]\s*(.*?)(?=\[(?:环境|场景|场景细节|事件|副事件|状态|选择|历史|时间)\]|\Z)",
            response_text, re.DOTALL,
        ):
            body += content
        if not body.strip():
            return issues
        for m in _NARR_VALUE_RE.finditer(body):
            name, kind = m.group("name").strip(), m.group("kind")
            claimed = int(m.group("num"))
            field = _NARR_KIND_FIELD.get(kind)
            if field is None:
                continue
            actor = self._resolve_actor(name)
            if actor is None:
                continue
            actual = getattr(actor, field, None)
            if actual is not None and claimed != int(actual):
                issues.append(
                    f"叙事称「{name} {kind} {claimed}」，真实为 {actual}"
                )
        return issues

    def _resolve_actor(self, name: str):
        m = self.regulator.manager
        if not m or not name:
            return None
        return m._resolve_actor(name)

    def _record_reminder(self, reminder: str) -> None:
        """把 [系统提醒] 写回 LLM 历史，下一轮 DM 能读到并自纠措辞。"""
        if not self.gm.history:
            return
        last = self.gm.history[-1]
        if last.get("role") == "assistant":
            last["content"] = (last.get("content") or "") + "\n\n" + reminder

    def _split_sections(self, response_text: str) -> dict:
        """按区块标题切分 LLM 输出（与 REPAIR_SECTION_NAMES 对齐）。"""
        sections = {}
        for name, content in re.findall(
            rf"\[({self.REPAIR_SECTION_NAMES})\]\s*(.*?)(?=\[(?:{self.REPAIR_SECTION_NAMES})\]|\Z)",
            response_text, re.DOTALL,
        ):
            sections[name] = content.strip()
        return sections

    def _has_event(self, response_text: str) -> bool:
        """[事件] 区块是否非空（面向玩家展示的叙事核心）。"""
        return bool(self._split_sections(response_text).get("事件", "").strip())

    def detect_defects(self, response_text: str, require_event: bool = False,
                       require_choices: bool = False) -> list[str]:
        """检测本轮缺失的关键块（事件/选择）。供 audit 与 dm_call 补写循环共用。"""
        defects = []
        if require_event and not self._has_event(response_text):
            defects.append("事件")
        if require_choices:
            m = getattr(self.regulator, "manager", None)
            if m is None or not getattr(m, "choices", None):
                defects.append("选择")
        return defects

    def report_repair_exhausted(self, defects: list[str], retries: int,
                                tokens_used: int) -> None:
        """补写重试耗尽后，监督者打印错误原因（玩家/日志双通道）。

        只有当补写次数超限或累计 token 超过预算时才触发——即判定该模型已无法
        正常产出关键块，属于「模型确实不可用」的兜底报错，而非普通缺失。
        """
        reasons = []
        if retries > Config.REPAIR_MAX_RETRIES:
            reasons.append(
                f"经 {Config.REPAIR_MAX_RETRIES} 次补写仍未产出"
            )
        if tokens_used >= Config.REPAIR_TOKEN_BUDGET:
            reasons.append(
                f"累计消耗 {tokens_used} tokens 超过预算 {Config.REPAIR_TOKEN_BUDGET}"
            )
        reason = "；".join(reasons) or "补写失败"
        msg = (
            f"监督者：块缺失（{'、'.join(defects)}）——{reason}，"
            "判定当前模型已无法正常完成关键块产出。请检查模型服务或更换模型后重试。"
        )
        console.print(f"[indian_red]{msg}[/indian_red]")
        self._record_reminder("[系统提醒] " + msg)
