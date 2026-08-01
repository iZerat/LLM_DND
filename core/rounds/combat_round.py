from __future__ import annotations
from core.rounds.base_round import BaseRound, RoundResult
from core.rounds.segments.npc_segment import NPCSegment
from core.rounds.segments.player_segment import PlayerSegment
from core.ui import (
    render_round_header, render_env_block, render_event_block,
    render_change_block, parse_sections,
)
from world.entity import NPC


class CombatRound(BaseRound):
    """战斗回合：DM 预调用（长上下文）→ 环境/主事件 → 按先攻小循环逐段。

    每个 actor 依次执行自己的段；段间状态（HP/AC）由 WorldState 落账，
    目标块每段后从 WorldState 重新渲染。回合计数由 GameRound 统一维护。
    """

    def run(self, player_input: str, on_prompt):
        self.gm.last_check_block = None
        audit, elapsed = self.dm_call(
            self._prelude_prompt(player_input),
            tools=None, tag="pre",
        )
        sections = parse_sections(audit.text)
        render_round_header(self.ctx.round_num, kind="战斗")
        if "环境" in sections:
            render_env_block(sections["环境"], self.gm)
        if self.gm and "时间" in sections:
            self.gm.last_time = sections["时间"]
        if "事件" in sections:
            render_event_block(sections["事件"])
        if audit.messages:
            render_change_block(audit.messages)

        initiative = self.ctx.initiative
        if not initiative.order:
            initiative.roll(self.world)
        order = initiative.resolve(self.world)
        choices_text = sections.get("选择", "")

        next_input = player_input
        for name, entity in order:
            if name == self.character.name:
                res = PlayerSegment(self.ctx, choices_text, on_prompt).run()
                if res is not None and res.action != "continue":
                    return res
                if res is not None:
                    next_input = res.player_input
            elif isinstance(entity, NPC) and getattr(entity, "hp", 0) > 0:
                NPCSegment(self.ctx, entity, player_input).run()

        # 战斗结束判定：无存活敌对 → 清空先攻，下轮回非战斗流程
        if not self._hostile_alive():
            initiative.order = []
        return RoundResult(player_input=next_input)

    def _prelude_prompt(self, player_input: str) -> str:
        if not player_input or player_input == "DM，请开始我的冒险吧！":
            return (
                "战斗已经开始！请描述当前战场环境与主事件（总结上一回合发生的事、铺垫本轮），"
                "并先想好在场每个目标的行动倾向。"
                "输出 [环境]、[时间]、[事件]、[选择]、[状态]。"
            )
        return (
            f"（上一轮玩家行动：{player_input}）\n"
            "新一轮战斗开始。请总结上一回合战况、铺垫本回合的开展，"
            "并先想好在场每个目标的行动倾向。"
            "输出 [环境]、[时间]、[事件]、[选择]、[状态]。"
        )

    def _hostile_alive(self) -> bool:
        from resource.attitude import level
        for e in self.world.active.values():
            if isinstance(e, NPC) and level(getattr(e, "attitude", 0)) == "hostile" and getattr(e, "hp", 0) > 0:
                return True
        return False
