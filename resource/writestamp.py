from __future__ import annotations
"""写协调戳：调节器/发条/玩家对同一字段的连续写入必须检查 stamp，防止互相静默覆盖。

设计见 `design/four-systems-architecture.md` §4.2。
"""
from dataclasses import dataclass


@dataclass
class WriteStamp:
    """同字段最后一次写入的元信息。

    writer: "regulator" | "clockwork" | "player" | "generator"
    version: 单调递增，越大越新
    at: 记录用标签（轮号/游戏时间）
    """
    writer: str = "clockwork"
    version: int = 1
    at: object = ""


def newer(a: WriteStamp | None, b: WriteStamp | None) -> WriteStamp | None:
    """取两者中较新的 stamp（version 大者新）；任一为 None 时取另一个。"""
    if a is None:
        return b
    if b is None:
        return a
    return a if a.version >= b.version else b
