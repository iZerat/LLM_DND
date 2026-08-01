from __future__ import annotations
from core.rounds.base_round import BaseRound, RoundResult, update_choices_map
from core.ui import (
    render_round_header, render_env_block, render_event_block, render_action_block,
    render_narration_block, render_change_block, render_status_row,
    render_choice_block, parse_sections,
)


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

        render_round_header(self.ctx.round_num, kind="非战斗")
        if "环境" in sections:
            render_env_block(sections["环境"], self.gm)
        if self.gm and "时间" in sections:
            self.gm.last_time = sections["时间"]
        if "事件" in sections:
            render_event_block(sections["事件"])

        carried_check = getattr(self.gm, "last_check_block", None)
        check_blocks = []
        if carried_check:
            check_blocks.append({"text": carried_check})
            self.gm.last_check_block = None
        check_blocks.extend(getattr(self.toolbox, "check_results", None) or [])
        if check_blocks:
            render_action_block(check_blocks)
            if "副事件" in sections:
                render_narration_block(sections["副事件"])
        if audit.messages:
            render_change_block(audit.messages)
        render_status_row(self.character, self.world)
        if "选择" in sections:
            update_choices_map(self.gm, sections["选择"])
            render_choice_block(sections["选择"])

        pr = on_prompt()
        if pr.action != "continue":
            return RoundResult(action=pr.action, gm=pr.gm)
        transformed, decision_text, check_text = self.resolve_input(
            pr.player_input, from_command=pr.from_command
        )
        self.gm.last_check_block = check_text or None
        self.render_decision(decision_text)
        return RoundResult(player_input=transformed)
