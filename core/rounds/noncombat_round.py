from __future__ import annotations
from core.rounds.base_round import BaseRound, RoundResult, update_choices_map
from core.ui import (
    render_round_header, render_narration_block, render_change_block,
    render_status_row, parse_sections, console,
)
from core.blocks import EnvironmentBlock, EventBlock, ActionBlock, StatusBlock, ChoiceBlock


class NonCombatRound(BaseRound):
    """非战斗回合：单次 DM 调用（长上下文）→ 环境/主事件 → 行动块(上轮骰面)
    → 副事件 → 变更 → 目标 → 选择 → 玩家输入 → 决定块(纯记录)。

    上轮玩家选择的检定骰面顺延到本轮展示（行动块），判定与结果由本轮 DM
    在事件/副事件中说明。决定块只记录选择，不给判定和结果。
    """

    def run(self, player_input: str, on_prompt):
        if self.start_of_turn_death_save() == "dead":
            return RoundResult(action="menu")
        audit, elapsed = self.dm_call(player_input, tag="nc")
        sections = parse_sections(audit.text)
        self.rendered_blocks = []

        render_round_header(self.ctx.round_num, kind="非战斗")

        # [环境] — 从当前场景数据渲染
        m = getattr(self.regulator, "manager", None)
        scene = m.world._ensure_scene() if (m and m.world) else None
        if scene:
            EnvironmentBlock.from_scene(scene).render()
            self.rendered_blocks.append("环境")

        # [事件] — DM 文本
        if "事件" in sections:
            EventBlock.from_text(sections["事件"]).render()
            self.rendered_blocks.append("事件")

        # [行动] — 上轮检定
        carried_check = getattr(self.gm, "last_check_block", None)
        if carried_check:
            ActionBlock.from_check(carried_check).render()
            self.rendered_blocks.append("行动")
            self.gm.last_check_block = None
            if "副事件" in sections:
                render_narration_block(sections["副事件"])
                self.rendered_blocks.append("副事件")
        for cb in (getattr(self.toolbox, "check_results", None) or []):
            ActionBlock.from_check(cb.get("text", "")).render()
            self.rendered_blocks.append("行动")

        # [变更]
        m2 = getattr(self.regulator, "manager", None)
        if audit.messages:
            render_change_block(audit.messages)
            self.rendered_blocks.append("变更")
        if m2 and getattr(m2, "pending_changes", None):
            render_change_block(m2.pending_changes)
            m2.pending_changes.clear()
            if "变更" not in self.rendered_blocks:
                self.rendered_blocks.append("变更")

        # [状态]
        StatusBlock.from_world(self.character, self.world)
        self.rendered_blocks.append("状态")

        # [选择]
        choices = getattr(m2, "choices", None) if m2 else None
        if choices:
            ChoiceBlock.from_choices(choices).render()
            self.rendered_blocks.append("选择")

        errs = self.supervisor.check_round_integrity(
            self.rendered_blocks, "非战斗", self.ctx.round_num)
        for err in errs:
            console.print(f"[indian_red]{err}[/indian_red]")

        pr = on_prompt()
        if pr.action != "continue":
            return RoundResult(action=pr.action, gm=pr.gm)
        transformed, decision_text, check_text = self.resolve_input(
            pr.player_input, from_command=pr.from_command
        )
        self.gm.last_check_block = check_text or None
        self.render_decision(decision_text)
        return RoundResult(player_input=transformed)
