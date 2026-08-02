from __future__ import annotations
from core.rounds.segments.base import Segment
from core.ui import (
    render_action_block, render_narration_block, render_change_block,
    render_status_row, parse_sections,
)


class NPCSegment(Segment):
    """目标段：行动块（系统骰，全宽）→ DM 短调用 → 副事件块 → 变更块 → 目标块。"""

    def __init__(self, ctx, npc, player_input: str):
        super().__init__(ctx)
        self.npc = npc
        self.player_input = player_input

    def run(self):
        controller = self.ctx.npc_controller
        check_text, injected, change_msg = controller.act(self.npc, self.player_input)
        if check_text:
            render_action_block([{"text": check_text}])
        if not injected:
            render_status_row(self.character, self.world)
            return
        audit, _ = self.dm_call(
            f"{injected}\n\n请把以上已经系统结算的行动编织进 [副事件] 区块，"
            f"用 2-3 句话描述 {self.npc.name} 的这轮行动。伤害/结果已落账，不要重复扣血。"
            f"\n\n[当前战场]\n{self.world_context()}",
            tools=[], mode="light", tag="seg",
        )
        sections = parse_sections(audit.text)
        if "副事件" in sections:
            render_narration_block(sections["副事件"])
        if change_msg:
            render_change_block([change_msg])
        render_status_row(self.character, self.world)
