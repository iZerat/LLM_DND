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


class Supervisor:
    """双向审核器（监督者）。

    方向A — prepare_player_input：玩家输入 → 行为分类（触发词）→ 附加提示词片段
             + 注入世界状态上下文。
    方向B — audit：LLM 输出 → 结构校验 → 经调节器落账 → 剥离变更区块 →
             库外物品/缺目标等不合格时发起多轮修复对话 → 返回可显示文本。

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
            )
            if ctx:
                enriched += "\n\n" + ctx
        return enriched

    # ── 方向B：LLM 输出 → 审核 ──

    def audit(self, raw_text: str) -> AuditResult:
        result = AuditResult()
        text = raw_text.replace("（无需检定）", "")

        # 0. 工具通道：已通过工具落账的变更直接展示；
        #    若本轮用了工具，叙事中残余的文本区块仅作兜底，剥离以防双重落账
        if getattr(self.gm, "last_tool_results", None):
            result.messages.extend(self.gm.last_tool_results)
        if getattr(self.gm, "_used_tools", False):
            text = _ITEM_BLOCK_RE.sub("", text, count=1)
            text = _STATUS_CHANGE_BLOCK_RE.sub("", text, count=1)

        # 1. [物品变更]：落账；库外物品触发重写对话
        retries = 0
        while True:
            report = self.regulator.submit_item_changes(text)
            result.messages.extend(report.messages)
            if report.applied or not report.issues:
                text = report.text
                break
            missing = "、".join(report.issues)
            retries += 1
            if retries >= self.max_retries:
                result.messages.append(
                    f"物品变更失败: {missing}，已忽略相关变更，故事由 DM 自行圆场"
                )
                text = report.text
                break
            result.messages.append(f"物品变更失败: {missing}，DM 正在调整故事…")
            text = self._ask_rewrite(missing, "item")

        # 2. [状态变更]：HP / 目标 / NPC；npc_add 校验失败整块重写
        retries = 0
        while True:
            report = self.regulator.submit_status_changes(text)
            result.messages.extend(report.messages)
            if report.applied or not report.issues:
                text = report.text
                break
            issue = "、".join(report.issues)
            retries += 1
            if retries >= self.max_retries:
                result.messages.append(
                    f"NPC创建失败: {issue}，已忽略相关变更，故事由 DM 自行圆场"
                )
                text = report.text
                break
            result.messages.append(f"NPC创建失败: {issue}，DM 正在调整故事…")
            text = self._ask_rewrite(issue, "npc")

        # 3. [状态] 区块：名称规范校验 → 不合格打回重写 → 同步 WorldState
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

        report = self.regulator.sync_status_block(text, report.changed_npcs)
        result.messages.extend(report.messages)

        # 数值复核：以调节器落账为准覆盖 [状态] 块中的 HP/AC，
        # 让玩家看到的“目标”面板永远与“变更”面板一致（允许大模型圆故事，不允许数值裸冲突）
        text = self.regulator.reconcile_status_block(text)

        # 4. 结构校验：缺目标信息 → 修复对话
        if self.needs_repair(text):
            text = self.repair(text)
            result.repaired = True

        result.text = text
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

    # ── 内部：库外物品 / NPC 重写对话 ──

    def _ask_rewrite(self, missing: str, kind: str = "item") -> str:
        if kind == "npc":
            correction_prompt = (
                f"[系统] 注意：无法创建 NPC：{missing}。"
                "请修改你的输出，改用可用的 NPC，或调整叙事让该 NPC 不出现。"
                "保留其他内容不变。请重新输出完整回答。"
            )
        else:
            correction_prompt = (
                f"[系统] 注意：以下物品变更无法执行：{missing}。"
                "请修改你的输出，改用资源库中存在的物品，"
                "或修正 item_add 填表字段，或修改叙事让这些物品不可获得。"
                "保留其他内容不变。请重新输出完整回答。"
            )
        parts = []
        for chunk in self.gm.send_message_stream(correction_prompt):
            parts.append(chunk)
        return "".join(parts).replace("（无需检定）", "")
