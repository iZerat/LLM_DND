from __future__ import annotations
from core.rounds.base_round import BaseRound, RoundResult, update_choices_map
from core.rounds.segments.npc_segment import NPCSegment
from core.rounds.segments.player_segment import PlayerSegment
from core.ui import (
    render_round_header, render_change_block, render_status_row, parse_sections, console,
)
from core.blocks import EnvironmentBlock, EventBlock, SubEventBlock, ActionBlock, ChoiceBlock
from world.entity import NPC


class CombatRound(BaseRound):
    """战斗回合：DM 预调用（长上下文）→ 环境/主事件 → 按先攻小循环逐段。

    每个 actor 依次执行自己的段（NPC段：DM 短调用 → 行动块 → 副事件 → 变更 → 状态块；
    玩家段：选择块 → 输入 → 决定块 → DM 短调用 → 行动块 → 副事件 → 变更 → 状态块）。
    """

    def run(self, player_input: str, on_prompt):
        audit, elapsed = self.dm_call(
            self._prelude_prompt(player_input),
            tools=None, mode="full", tag="pre", require_event=True,
            require_choices=True,
        )
        sections = parse_sections(audit.text)
        self.rendered_blocks = []
        render_round_header(self.ctx.round_num, kind="战斗")

        # [环境]
        m = getattr(self.regulator, "manager", None)
        scene = m.world._ensure_scene() if (m and m.world) else None
        if scene:
            EnvironmentBlock.from_scene(scene, world=m.world).render()
            self.rendered_blocks.append("环境")

        # [事件]
        if "事件" in sections:
            EventBlock.from_text(sections["事件"]).render()
            self.rendered_blocks.append("事件")

        # [行动] carried + pending changes
        carried_check = getattr(self.gm, "last_check_block", None)
        if carried_check:
            ActionBlock.from_check(carried_check).render()
            self.rendered_blocks.append("行动")
            self.gm.last_check_block = None
            if getattr(self.gm, "last_check_changes", None):
                render_change_block(self.gm.last_check_changes)
                self.rendered_blocks.append("变更")
                self.gm.last_check_changes = None
        if "副事件" in sections:
            SubEventBlock.from_text(sections["副事件"]).render()
            self.rendered_blocks.append("副事件")
        if audit.messages:
            render_change_block(audit.messages)
            self.rendered_blocks.append("变更")

        initiative = self.ctx.initiative
        if not initiative.order:
            initiative.roll(self.world)
        order = initiative.resolve(self.world)

        # [状态] 目标块：prelude 渲染了行动/变更块后必须以目标块收尾（小循环一段一处理，
        # carried 行动段不能被下一个行动段紧接）；无行动/变更但玩家先手时也补打，
        # 保证玩家输入前能看到战场状态。
        if "行动" in self.rendered_blocks or "变更" in self.rendered_blocks:
            render_status_row(self.character, self.world)
            self.rendered_blocks.append("状态")
        elif order and order[0][0] == self.character.name:
            render_status_row(self.character, self.world)
            self.rendered_blocks.append("状态")

        # [选择] 由 PlayerSegment 渲染，prelude 不重复
        choices_text = sections.get("选择", "")

        errs = self.supervisor.check_round_integrity(
            self.rendered_blocks, "战斗", self.ctx.round_num, node="prelude")
        for err in errs:
            console.print(f"[indian_red]{err}[/indian_red]")

        next_input = player_input
        for name, entity in order:
            if name == self.character.name:
                res = PlayerSegment(self.ctx, choices_text, on_prompt,
                                    supervisor=self.supervisor,
                                    round_num=self.ctx.round_num).run()
                if res is not None and res.action != "continue":
                    return res
                if res is not None:
                    next_input = res.player_input
            elif isinstance(entity, NPC) and not getattr(entity, "dead", False):
                if getattr(entity, "unconscious", False):
                    if getattr(entity, "is_character", False):
                        self._npc_death_save(entity)
                    continue
                NPCSegment(self.ctx, entity, player_input).run()

        if not self._hostile_alive():
            initiative.order = []
        return RoundResult(player_input=next_input)

    def _npc_death_save(self, npc):
        """重要 NPC（is_character）回合起手 0 HP → 系统自动死亡豁免（同玩家，RAW L1229）。"""
        from core.ui import render_death_save_block
        res = self.regulator.manager.roll_death_save(npc)
        if res and res.success:
            render_death_save_block(res.message)
            self.rendered_blocks.append("死亡豁免")
        return getattr(npc, "dead", False)

    def _prelude_prompt(self, player_input: str) -> str:
        prefix = "战斗已经开始！请总结上一回合战况、铺垫本轮战场局势。只输出 [事件] 区块。"
        if player_input and player_input != "DM，请开始我的冒险吧！":
            prefix = (
                f"（上一轮玩家行动：{player_input}）\n"
                "新一轮战斗开始。请总结上一回合战况、铺垫本轮战场局势。"
                "输出 [事件] 区块；上一轮有玩家检定结果时另加 [副事件] 区块描述其过程与结果。"
                "叙事中不要出现「已落账」「系统结算」「HP 减少」等记账式/系统用语——"
                "数值变化由系统单独渲染的[变更]块展示，你只需用画面感语言描述。"
            )
        if self.character.hp <= 0:
            prefix += "（注意：玩家当前处于昏迷/倒地状态）"
        return prefix

    def _hostile_alive(self) -> bool:
        from resource.attitude import level
        for e in self.world.active.values():
            if (isinstance(e, NPC) and level(getattr(e, "attitude", 0)) == "hostile"
                    and not getattr(e, "dead", False)
                    and not getattr(e, "unconscious", False)):
                return True
        return False
