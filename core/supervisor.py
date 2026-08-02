from __future__ import annotations
import re

from core.config import Config
from core.prompt_lib import build_prompt_suffix
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


class AuditResult:
    """监督者方向B 一轮审核的结果。

    - messages：结构化变更记录（工具落账/状态同步），只进 [变更] 块；
    - notices：监督者诊断（修复提示/系统提醒），不进终端，仅落日志与 LLM 历史。
    """

    def __init__(self):
        self.text: str = ""
        self.messages: list[str] = []
        self.notices: list[str] = []
        self.repaired: bool = False
        self.changed_npcs: set[str] = set()


class Supervisor:
    """双向审核器（监督者）。

    方向A — prepare_player_input：玩家输入 → 行为分类（触发词）→ 附加提示词片段
             + 注入世界状态上下文。
    方向B — audit：LLM 输出 → 剥离残余文本变更区块（不落账，数据变更只能经工具）
              → [状态] 区块校验/同步 → 结构不合格时发起修复对话 → 返回可显示文本。

    不做任何数据落账：所有写入统一交给调节器（Regulator）。
    """

    SECTION_NAMES = "环境|场景|场景细节|事件|副事件|状态|选择|历史|时间"
    REPAIR_SECTION_NAMES = "环境|场景|场景细节|事件|副事件|状态|选择|历史"

    def __init__(self, gm, regulator, max_retries: int = 3):
        self.gm = gm
        self.regulator = regulator
        self.max_retries = max_retries

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
        return errors

    # ── 方向B：LLM 输出 → 审核 ──

    def audit(self, raw_text: str, protected_npcs: set | None = None,
              mode: str = "full") -> AuditResult:
        result = AuditResult()

        # 0. 工具通道：已通过工具落账的变更直接展示
        if getattr(self.gm, "last_tool_results", None):
            result.messages.extend(self.gm.last_tool_results)

        # 1. [物品变更]/[状态变更] 文本区块已废除（D6）：数据变更只能经工具。
        #    若 LLM 仍输出这些区块，一律剥离且不落账，防止双重结算与幻影落账。
        text = _ITEM_BLOCK_RE.sub("", raw_text.replace("（无需检定）", ""), count=1)
        text = _STATUS_CHANGE_BLOCK_RE.sub("", text, count=1)

        # 轻量模式：段内叙事（战斗已由系统机械结算）——只剥离变更区块，不落账，
        # 不校验/修复结构，避免短调用被反复打回。
        if mode == "light":
            result.text = text
            return result

        # 2. [状态] 区块：名称规范校验 → 不合格打回重写 → 同步 WorldState
        retries = 0
        while True:
            status_issues = self.regulator.validate_status_block(text)
            if not status_issues:
                break
            retries += 1
            if retries > self.max_retries:
                result.notices.append(
                    f"状态名称格式异常: {'；'.join(status_issues)}，已保留原状"
                )
                break
            result.notices.append(f"状态格式需修正: {'；'.join(status_issues)}，DM 正在调整…")
            new_text = self.repair(text, hint="；".join(status_issues))
            result.repaired = True
            if new_text == text:
                break
            text = new_text

        report = self.regulator.sync_status_block(text, protected_npcs or set())
        result.messages.extend(report.messages)
        result.changed_npcs |= report.changed_npcs

        # 数值复核：以调节器落账为准覆盖 [状态] 块中的 HP/AC，
        # 让玩家看到的“目标”面板永远与落账一致（允许大模型圆故事，不允许数值裸冲突）
        text = self.regulator.reconcile_status_block(text)

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

        # 3. 结构校验：缺目标信息 → 修复对话
        if self.needs_repair(text):
            text = self.repair(text)
            result.repaired = True

        # 4. 兜底：剥离本轮选项中残留的括号技术标注（提示词已要求 LLM 不输出，
        #    这里再兜一层，保证玩家看到的选择项只含纯描述文本）
        m = getattr(self.regulator, "manager", None)
        for c in getattr(m, "choices", None) or []:
            c["label"] = strip_choice_annotation(c.get("label", ""))

        result.text = text
        self.gm.last_changed_npcs = result.changed_npcs
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

    def needs_repair(self, response_text: str) -> bool:
        """检测 [状态] 是否缺少目标行，且 [事件] 疑似发生了战斗/冲突。"""
        sections = {}
        for name, content in re.findall(
            rf"\[({self.REPAIR_SECTION_NAMES})\]\s*(.*?)(?=\[(?:{self.REPAIR_SECTION_NAMES})\]|\Z)",
            response_text, re.DOTALL,
        ):
            sections[name] = content.strip()
        status_text = sections.get("状态", "")
        event_text = sections.get("事件", "")
        has_target = bool(re.search(r"目标\s*:", status_text))
        has_enemy = any(
            w in event_text for w in ["攻击", "敌人", "敌对", "战斗", "拔刀", "挥剑", "追", "冲突"]
        )
        return not has_target and has_enemy

    def repair(self, response_text: str, hint: str = "") -> str:
        """反问 DM 修正 [状态] 区块，返回修补后的完整文本。

        hint 为空表示「缺少目标信息」；否则作为名称规范等具体问题提示。
        """
        if hint:
            follow_up = (
                f"你上一轮回复中[状态]的目标名称不合规范：{hint}。"
                "请只输出修正后的[状态]区块。"
            )
        else:
            follow_up = "你上一轮回复中[状态]缺少目标信息。请只输出补充后的[状态]区块。"
        if not self.gm.client:
            return response_text
        try:
            r = self.gm.client.chat.completions.create(
                model=Config.MODEL_NAME,
                messages=[{"role": "user", "content": follow_up}],
                stream=False,
                temperature=0.3,
                max_tokens=300,
            )
        except Exception:
            return response_text
        repair_text = r.choices[0].message.content or ""
        m = re.search(
            rf"\[状态\](.*?)(?=\[(?:{self.REPAIR_SECTION_NAMES})\]|\Z)",
            repair_text, re.DOTALL,
        )
        if m:
            raw = m.group(0)
            if not raw.startswith("[状态]"):
                raw = "[状态]" + raw
            response_text = re.sub(
                rf"\[状态\](.*?)(?=\[(?:{self.REPAIR_SECTION_NAMES})\]|\Z)",
                raw.strip(), response_text, count=1, flags=re.DOTALL,
            )
            self.gm.history.append(
                {"role": "assistant", "content": "\n（补全的目标信息）\n" + repair_text}
            )
        return response_text
