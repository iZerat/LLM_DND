from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
from resource.attitude import coerce_legacy
from resource.models import Currency


@dataclass
class Entity:
    id: str
    name: str
    tags: list[str] = field(default_factory=list)
    memory_weight: int = 50
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Entity:
        return cls(**d)


@dataclass
class NPC(Entity):
    species: str = "human"
    char_class: str = "commoner"
    level: int = 0

    hp: int = 8
    max_hp: int = 8
    ac: int = 10

    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    proficiency_bonus: int = 2
    skills: list[str] = field(default_factory=list)
    saving_throws: list[str] = field(default_factory=list)

    attitude: int = 0
    attitude_reasons: list[dict] = field(default_factory=list)
    currency: Currency = field(default_factory=Currency)
    inventory: list[str] = field(default_factory=list)
    dialogue_state: str = ""

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
        npc = cls(**d)
        npc.currency = Currency(copper=copper)
        return npc
