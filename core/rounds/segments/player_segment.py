from __future__ import annotations
from core.rounds.base_round import RoundResult, update_choices_map
from core.rounds.segments.base import Segment
from core.ui import (
    render_choice_block, render_action_block, render_narration_block,
    render_change_block, render_status_row, parse_sections,
)


class PlayerSegment(Segment):
    """玩家段：选择块 → 玩家输入 → 决定块 → 行动块 → DM 短调用 → 副事件块 → 变更块 → 状态块。

    选项编号输入：本地机械结算（交互骰），DM 仅编织叙事（不重复结算）。
    自由文本/命令输入：交由 DM 全权处理（含工具落账）。
    """

    def __init__(self, ctx, choices_text: str, on_prompt):
        super().__init__(ctx)
        self.choices_text = choices_text
        self.on_prompt = on_prompt

    def run(self):
        outcome = self.start_of_turn_death_save()
        if outcome == "dead":
            return RoundResult(action="menu")

        if self.choices_text:
            update_choices_map(self.gm, self.choices_text)
            render_choice_block(self.choices_text)

        pr = self.on_prompt()
        if pr.action != "continue":
            return RoundResult(action=pr.action, gm=pr.gm)

        transformed, decision_text, check_text = self.resolve_input(
            pr.player_input, from_command=pr.from_command
        )
        self.render_decision(decision_text)
        if check_text:
            render_action_block([{"text": check_text}])

        is_local = not pr.from_command and pr.player_input.strip().isdigit()
        if is_local:
            audit, _ = self.dm_call(
                f"玩家本轮行动：{transformed}。检定已由系统结算，"
                f"请把结果编织进 [副事件] 区块描述，不要重复结算。"
                f"\n\n[当前战场]\n{self.world_context()}",
                tools=[], mode="light", tag="seg",
            )
        else:
            audit, _ = self.dm_call(transformed, tag="seg")

        sections = parse_sections(audit.text)
        if getattr(self.toolbox, "check_results", None):
            render_action_block(self.toolbox.check_results)
        if "副事件" in sections:
            render_narration_block(sections["副事件"])
        if audit.messages:
            render_change_block(audit.messages)
        render_status_row(self.character, self.world)
        return RoundResult(player_input=transformed)
