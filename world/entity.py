from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
from resource.attitude import coerce_legacy
from resource.models import Currency
from world.actor import Actor, Entity


@dataclass
class NPC(Actor):
    species: str = "human"

    attitude_reasons: list[dict] = field(default_factory=list)
    currency: Currency = field(default_factory=Currency)
    inventory: list[str] = field(default_factory=list)
    dialogue_state: str = ""

    @classmethod
    def create(cls, name: str = "", **kwargs) -> NPC:
        return cls(name=name, **kwargs)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["currency"] = {"copper": self.currency.copper}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> NPC:
        d = dict(d)
        copper = d.pop("currency", {}).get("copper", 0)
        if "attitude" in d:
            d["attitude"] = coerce_legacy(d["attitude"])
        d.setdefault("attitude_reasons", [])
        if "ac" in d and "base_ac" not in d:
            d["base_ac"] = d.pop("ac")
        npc = cls(**d)
        npc.currency = Currency(copper=copper)
        return npc

    def apply_hp(self, delta: int, crit: bool = False) -> tuple[int, int, list[str]]:
        before = self.hp
        if self.dead:
            return before, self.hp, [f"{self.name} 已死亡，无法变更 HP"]
        notes: list[str] = []
        if delta > 0:
            new = min(self.hp + int(delta or 0), self.max_hp)
            self.hp = new
            if before <= 0 < new:
                notes.append("苏醒")
        elif delta < 0:
            new = max(self.hp + int(delta or 0), 0)
            self.hp = new
            if new == 0:
                if before == 0:
                    notes.append("（仍倒地）")
                elif -delta - before >= self.max_hp:
                    self.dead = True
                    notes.append("即死（巨量伤害 ≥ 生命上限）")
                else:
                    notes.append("倒地昏迷")
        return before, self.hp, notes

    def apply_max_hp(self, delta: int) -> tuple[int, int, list[str]]:
        before = self.max_hp
        if self.dead:
            return before, self.max_hp, [f"{self.name} 已死亡，无法变更最大HP"]
        self.max_hp = max(self.max_hp + int(delta or 0), 1)
        if self.hp > self.max_hp:
            self.hp = self.max_hp
        return before, self.max_hp, []
