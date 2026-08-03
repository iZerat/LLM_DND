from __future__ import annotations
"""发条任务：对每个符合条件的对象做本地模拟推进。

统一签名 apply(obj, elapsed, stamp, combat=False) -> list[ChangeEvent]。
- elapsed：推进的轮数/时间片
- stamp：写入协调戳（WriteStamp）
- combat：本 tick 是否处于战斗（战斗中暂停与战斗状态冲突的模拟）
"""
from resource.attitude import decay, level_cn
from resource.models import format_signed
from world.clockwork.events import ChangeEvent


class ClockworkJob:
    """发条任务基类：field 声明本任务写入的字段，供写协调（locked）跳过。"""

    field: str = ""

    def apply(self, obj, elapsed: int, stamp, combat: bool = False) -> list[ChangeEvent]:
        return []


class AttitudeDriftJob(ClockworkJob):
    """态度漂移任务：NPC 态度每轮向 0 小额漂移（绝对值大的快消）。

    规则（设计 §8 已定）：
    - 每轮结束态度向 0 漂移，步长见 `resource.attitude.decay`；
    - **战斗锁定**：场上有存活敌对 NPC 时整个漂移暂停（combat=True），
      防止战斗中途态度跌破阈值脱战；
    - **写协调**：本 tick 被调节器/玩家改过的 NPC（Clockwork.tick 的 locked）
      不会传到本任务，由调用方跳过。
    """

    field = "attitude"

    def apply(self, obj, elapsed: int, stamp, combat: bool = False) -> list[ChangeEvent]:
        if combat:
            return []
        cur = getattr(obj, "attitude", 0)
        if not isinstance(cur, int) or cur == 0:
            return []
        new = cur
        for _ in range(max(1, elapsed)):
            new = decay(new)
            if new == 0:
                break
        if new == cur:
            return []
        applied = new - cur
        obj.attitude = new
        reasons = getattr(obj, "attitude_reasons", None)
        if isinstance(reasons, list):
            reasons.append({
                "event": "decay",
                "delta": applied,
                "at": getattr(stamp, "at", "") if stamp else "",
                "source": "clockwork",
            })
        return [ChangeEvent(
            target=obj.name,
            message=f"{obj.name} 态度 缓和 {format_signed(applied)} "
                    f"({format_signed(cur)} >>> {format_signed(new)})",
            field=self.field,
            source="clockwork",
        )]
