from __future__ import annotations
import re

from core.rounds.segments.base import Segment
from core.ui import (
    render_action_block, render_narration_block, render_change_block,
    render_status_row, parse_sections,
)


def _action_display(name: str, injected: str) -> str:
    """非攻击行动的展示行：剥掉 [标签] 名前缀，如「[敌对] 哥布林：本轮撤退。」→「哥布林 撤退」。"""
    label = re.sub(
        r"^\[[^\]]*\]\s*[^：:]+[：:]\s*", "", (injected or "").strip(),
    ).strip("。").strip()
    label = re.sub(r"^本轮", "", label).strip()
    return f"[yellow]{name} {label}[/yellow]"


class NPCSegment(Segment):
    """目标段：行动块（系统骰，全宽）→ DM 短调用 → 副事件块 → 变更块 → 目标块。

    非攻击行动（撤退/观望等）无骰面：行动块只展示动作本身，保证副事件块始终跟在行动块后。
    """

    def __init__(self, ctx, npc, player_input: str):
        super().__init__(ctx)
        self.npc = npc
        self.player_input = player_input

    def run(self):
        controller = self.ctx.npc_controller
        check_text, injected, change_msg = controller.act(self.npc, self.player_input)
        if check_text:
            render_action_block([{"text": check_text}])
        elif injected:
            render_action_block([{"text": _action_display(self.npc.name, injected)}])
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
