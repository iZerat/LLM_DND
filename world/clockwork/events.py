from __future__ import annotations
"""发条系统的可见变更事件。"""
from dataclasses import dataclass


@dataclass
class ChangeEvent:
    """一次本地模拟推进产生的可见变更（进入变更回执列表，让玩家感知世界在动）。"""
    target: str
    message: str
    field: str = ""
    source: str = "clockwork"
