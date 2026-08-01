from __future__ import annotations
from rich.prompt import Prompt

from core.commands import parse_command
from core.npc_controller import NPCController
from core.supervisor import Supervisor
from resource.regulator import Regulator
from resource.toolbox import ResourceToolbox
from world.state import WorldState
from world.entity import NPC
from core.ui import console, show_status
from core.rounds.base_round import (
    RoundContext, RoundResult, PromptResult, resolve_player_input,
)
from core.rounds.initiative import Initiative
from core.rounds.noncombat_round import NonCombatRound
from core.rounds.combat_round import CombatRound
from core.game_loop import _GAME_REGISTRY, _show_round_recap


class GameRound:
    """回合大循环：非战斗/战斗分派、回合计数（每轮 +1，所有段共用同一轮号）、玩家输入与命令处理。"""

    def __init__(self, gm):
        self._init_context(gm)

    def _init_context(self, gm):
        self.gm = gm
        self.character = gm.character
        self.world_state = getattr(gm, "world_state", None) or WorldState()
        gm.world_state = self.world_state
        self.regulator = Regulator(self.character, self.world_state)
        self.regulator.manager.resource_mode = getattr(gm, "resource_mode", "pack")
        self.supervisor = Supervisor(gm, self.regulator)
        self.toolbox = ResourceToolbox(self.regulator)
        self.npc_controller = NPCController(gm, self.regulator)
        self.initiative = getattr(gm, "initiative", None) or Initiative(self.character)
        gm.initiative = self.initiative
        self.clockwork = self._init_clockwork(gm)
        gm.last_changed_npcs = set()
        hist = getattr(gm, "compressed_history", []) or []
        self.round_num = hist[-1]["round"] if hist else 0

    @staticmethod
    def _init_clockwork(gm):
        """发条（本地模拟推进）：会话级单例，注册态度漂移任务。"""
        cw = getattr(gm, "clockwork", None)
        if cw is None:
            from world.clockwork.clockwork import Clockwork
            from world.clockwork.jobs import AttitudeDriftJob
            cw = Clockwork()
            cw.register(AttitudeDriftJob())
            gm.clockwork = cw
        return cw

    def run(self):
        console.print(
            f"\n[steel_blue]{self.character.name}[/steel_blue] 的冒险开始了！"
            f"输入 [grey62]/help[/grey62] 查看命令\n"
        )
        prev_input = self._loaded_prestep()
        if prev_input == "quit":
            return
        if prev_input == "menu":
            return "menu"
        if prev_input is None:
            prev_input = "DM，请开始我的冒险吧！"

        while True:
            self.round_num += 1
            self.gm.last_changed_npcs = set()
            ctx = RoundContext(
                self.gm, self.regulator, self.supervisor, self.toolbox,
                self.npc_controller, self.initiative, self.round_num,
            )
            if self._in_combat():
                result = CombatRound(ctx).run(prev_input, on_prompt=self._prompt)
            else:
                result = NonCombatRound(ctx).run(prev_input, on_prompt=self._prompt)
            if result.action == "quit":
                return
            if result.action == "menu":
                return "menu"
            if result.action == "load":
                self._init_context(result.gm)
                show_status(self.character)
                prev_input = self._loaded_prestep()
                if prev_input == "quit":
                    return
                if prev_input == "menu":
                    return "menu"
                if prev_input is None:
                    prev_input = "DM，请开始我的冒险吧！"
                continue
            prev_input = result.player_input
            self._run_clockwork_tick()

    def _run_clockwork_tick(self):
        """每轮结束：发条推进（态度向 0 漂移），展示可见变更。

        写协调：跳过本轮被调节器/玩家改过的 NPC（gm.last_changed_npcs），
        避免发条立刻抵消刚发生的实时变更。
        """
        locked = set(getattr(self.gm, "last_changed_npcs", None) or ())
        events = self.clockwork.tick(
            self.world_state, at=f"round {self.round_num}", locked=locked
        )
        if events:
            from core.ui import render_change_block
            render_change_block([f"[grey50]发条[/grey50] {ev.message}" for ev in events])

    def _loaded_prestep(self):
        """读档恢复：回放上轮 → 重建选项映射 → 收集玩家输入（作为本轮 DM 的回应输入）。

        返回玩家输入；quit/menu 时返回控制标记；无历史时返回 None。"""
        while True:
            if not (self.gm.compressed_history and self.gm.last_assistant):
                return None
            _show_round_recap(self.gm)
            self._restore_choices()
            pr = self._prompt()
            if pr.action == "load":
                self._init_context(pr.gm)
                show_status(self.character)
                continue
            if pr.action == "quit":
                return "quit"
            if pr.action == "menu":
                return "menu"
            transformed, decision_text, check_text = resolve_player_input(
                self.gm, self.character, pr.player_input, from_command=pr.from_command,
                world=self.world_state, manager=self.regulator.manager,
            )
            self.gm.last_check_block = check_text or None
            if not pr.from_command:
                from core.ui import render_decision_block
                render_decision_block(decision_text)
            return transformed

    # ── 战斗判定 ──

    def _in_combat(self) -> bool:
        from resource.attitude import level
        for e in self.world_state.active.values():
            if isinstance(e, NPC) and level(getattr(e, "attitude", 0)) == "hostile" and getattr(e, "hp", 0) > 0:
                return True
        return False

    # ── 玩家输入 ──

    def _prompt(self) -> PromptResult:
        while True:
            try:
                raw = Prompt.ask(f"[grey82]{self.character.name}[/grey82]")
            except (EOFError, KeyboardInterrupt):
                console.print("\n冒险结束！")
                return PromptResult(action="quit")
            if not raw.strip():
                continue
            if parse_command(raw) is not None:
                result = _GAME_REGISTRY.resolve(raw, "game")
                if result is None:
                    console.print("[grey50]无效命令，输入 /help 查看可用命令[/grey50]")
                    continue
                cmd, args = result
                action = cmd.handler(self.gm, args)
                if action.action == "quit":
                    console.print("冒险结束！")
                    return PromptResult(action="quit")
                if action.action == "menu":
                    return PromptResult(action="menu")
                if action.action == "load":
                    return PromptResult(action="load", gm=action.gm)
                if action.action == "narrative":
                    return PromptResult(action="continue", player_input=action.player_input, from_command=True)
                continue
            return PromptResult(player_input=raw)

    def _restore_choices(self):
        """读档后从 last_assistant 文本重建选项映射。"""
        if not self.gm.last_assistant:
            return
        from core.ui import parse_sections
        from core.rounds.base_round import update_choices_map
        sections = parse_sections(self.gm.last_assistant)
        if "选择" in sections:
            update_choices_map(self.gm, sections["选择"])
