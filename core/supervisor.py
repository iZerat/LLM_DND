from __future__ import annotations
import re

from core.config import Config
from core.prompt_lib import build_prompt_suffix
from resource.regulator import _ITEM_BLOCK_RE, _STATUS_CHANGE_BLOCK_RE


class AuditResult:
    """监督者方向B 一轮审核的结果：最终文本 + 可见变更消息 + 是否修复过。"""

    def __init__(self):
        self.text: str = ""
        self.messages: list[str] = []
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
                result.messages.append(
                    f"状态名称格式异常: {'；'.join(status_issues)}，已保留原状"
                )
                break
            result.messages.append(f"状态格式需修正: {'；'.join(status_issues)}，DM 正在调整…")
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

        # 3. 结构校验：缺目标信息 → 修复对话
        if self.needs_repair(text):
            text = self.repair(text)
            result.repaired = True

        result.text = text
        self.gm.last_changed_npcs = result.changed_npcs
        return result

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
