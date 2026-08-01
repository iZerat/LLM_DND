from __future__ import annotations
from core.rounds.base_round import BaseRound


class Segment(BaseRound):
    """战斗回合小循环中的一段（玩家段 / 目标段），共用 BaseRound 的 DM 调用与渲染。"""
