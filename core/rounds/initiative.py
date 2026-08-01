from __future__ import annotations
import random
from dataclasses import dataclass

from core.character import modifier
from world.entity import NPC


@dataclass
class InitiativeEntry:
    name: str
    value: int

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value}


class Initiative:
    """先攻：d20 + 敏捷调整值，从高到低（同名共享一次掷骰）。

    开战（首个 active hostile NPC）时冻结 order，随存档保存；
    战斗结束后清空，下次开战重新掷。
    """

    def __init__(self, character):
        self.character = character
        self.order: list[InitiativeEntry] = []

    def roll(self, world) -> list[InitiativeEntry]:
        """对玩家与每个在场存活 NPC 掷先攻并排序（从高到低）。返回新 order。"""
        entries: list[tuple[str, int]] = [
            (self.character.name, random.randint(1, 20) + modifier(self.character.dexterity))
        ]
        roll_cache: dict[str, int] = {}
        for e in world.active.values():
            if not isinstance(e, NPC) or getattr(e, "hp", 0) <= 0:
                continue
            if e.name not in roll_cache:
                roll_cache[e.name] = random.randint(1, 20)
            entries.append((e.name, roll_cache[e.name] + modifier(e.dexterity)))
        entries.sort(key=lambda x: x[1], reverse=True)
        self.order = [InitiativeEntry(name=n, value=v) for n, v in entries]
        return self.order

    def resolve(self, world) -> list[tuple[str, object]]:
        """把 order 映射为 (name, entity) 列表；玩家名映射为 Character，其余按名字在世界查找。"""
        resolved: list[tuple[str, object]] = []
        for e in self.order:
            if e.name == self.character.name:
                resolved.append((e.name, self.character))
                continue
            ent = world.get_by_name(e.name)
            if ent is None:
                continue
            resolved.append((e.name, ent))
        return resolved

    def is_player_first(self) -> bool:
        return bool(self.order) and self.order[0].name == self.character.name

    def to_dict(self) -> list[dict]:
        return [e.to_dict() for e in self.order]

    @classmethod
    def from_dict(cls, data: list[dict] | None, character) -> Initiative:
        init = cls(character)
        for e in data or []:
            init.order.append(InitiativeEntry(name=e["name"], value=e.get("value", 0)))
        return init
