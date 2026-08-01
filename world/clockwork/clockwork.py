from __future__ import annotations
"""本地模拟推进（发条）：注册一批任务，每轮小步推进，离屏批量结算。

设计见 `design/four-systems-architecture.md` §5。
与调节器的边界：写同一字段前检查 locked，避开调节器/玩家刚写过的对象；
本模块自身不落账、不渲染，只产出 ChangeEvent 交上层展示。
"""
from world.clockwork.events import ChangeEvent
from world.clockwork.jobs import ClockworkJob
from resource.writestamp import WriteStamp


class Clockwork:
    """发条：持有任务注册表，统一推进世界内可演化数据。"""

    def __init__(self):
        self.jobs: list[ClockworkJob] = []

    def register(self, job: ClockworkJob) -> ClockworkJob:
        self.jobs.append(job)
        return job

    def tick(self, world, elapsed: int = 1, at: object = "",
             locked: set[str] | None = None) -> list[ChangeEvent]:
        """每轮小步推进。

        world: WorldState
        elapsed: 本轮推进的时间片（每轮 1；离屏结算传更大值）
        at: 记录用标签（轮号/游戏时间），写入 reason.at
        locked: 本 tick 内被其他写入方（调节器/玩家）刚改过的对象名，跳过
        """
        events: list[ChangeEvent] = []
        combat = self._combat_active(world)
        stamp = WriteStamp(writer="clockwork", version=1, at=at)
        for npc in self._npcs(world):
            if locked and npc.name in locked:
                continue
            for job in self.jobs:
                if job.field and locked and npc.name in locked:
                    continue
                events.extend(job.apply(npc, elapsed, stamp, combat=combat))
        return events

    def catch_up(self, world, elapsed: int, at: object = "",
                 locked: set[str] | None = None) -> list[ChangeEvent]:
        """离屏结算：对象离开玩家视线期间的批量推进（对齐设计 §5.2）。"""
        return self.tick(world, elapsed=elapsed, at=at, locked=locked)

    # ── 内部 ──

    @staticmethod
    def _npcs(world):
        """只漂 nearby/distant（D1）：世界池 active=在场，归大模型/调节器管辖，
        发条不得触碰，避免与实时叙事/战斗结算打架。"""
        from world.entity import NPC
        if world is None:
            return []
        return [
            e for pool in (world.nearby, world.distant)
            for e in pool.values()
            if isinstance(e, NPC)
        ]

    @staticmethod
    def _combat_active(world) -> bool:
        """场上有存活敌对 NPC 即视为战斗中（与 GameRound._in_combat 同源判定）。"""
        from world.entity import NPC
        from resource.attitude import level
        if world is None:
            return False
        for e in world.active.values():
            if (isinstance(e, NPC) and getattr(e, "hp", 0) > 0
                    and level(getattr(e, "attitude", 0)) == "hostile"):
                return True
        return False
