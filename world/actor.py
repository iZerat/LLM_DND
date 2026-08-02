from __future__ import annotations
from dataclasses import dataclass, field, asdict
from uuid import uuid4

from resource.attitude import clamp, coerce_legacy
from world.object import Object
from world.ability import Skill, coerce_skill


@dataclass
class Entity(Object):
    name: str = ""


@dataclass
class Actor(Entity):
    char_class: str = "commoner"
    level: int = 1

    hp: int = 10
    max_hp: int = 10
    base_ac: int = 10
    dead: bool = False

    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    proficiency_bonus: int = 2
    skills: list[Skill] = field(default_factory=list)
    saving_throws: list[str] = field(default_factory=list)

    attitude: int = 0

    def __post_init__(self):
        if not getattr(self, "id", ""):
            self.id = f"actor_{uuid4().hex[:8]}"
        self.level = max(int(self.level or 0), 1)
        self.max_hp = max(int(self.max_hp or 0), 1)
        self.hp = min(max(int(self.hp or 0), 0), self.max_hp)
        self.base_ac = max(int(self.base_ac or 0), 1)
        for ability in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"):
            value = int(getattr(self, ability) or 0)
            setattr(self, ability, min(max(value, 1), 30))
        self.proficiency_bonus = max(int(self.proficiency_bonus or 0), 0)
        self.attitude = coerce_legacy(self.attitude)
        self.skills = [sk for sk in (coerce_skill(s) for s in (self.skills or [])) if sk]

    @property
    def ac(self) -> int:
        return self.base_ac

    @property
    def unconscious(self) -> bool:
        return not self.dead and self.hp <= 0

    @property
    def condition_cn(self) -> str:
        if self.dead:
            return "死亡"
        if self.unconscious:
            return "昏迷"
        return "正常"

    def status_line(self) -> str:
        return f"{self.name}  AC:{self.ac}  HP:{self.hp}/{self.max_hp}"

    def apply_hp(self, delta: int, crit: bool = False) -> tuple[int, int, list[str]]:
        before = self.hp
        self.hp = min(max(self.hp + int(delta or 0), 0), self.max_hp)
        notes: list[str] = []
        if before <= 0 < self.hp:
            notes.append("苏醒")
        elif self.hp == 0 < before:
            notes.append("昏迷")
        return before, self.hp, notes

    def apply_max_hp(self, delta: int) -> tuple[int, int, list[str]]:
        before = self.max_hp
        self.max_hp = max(self.max_hp + int(delta or 0), 1)
        if self.hp > self.max_hp:
            self.hp = self.max_hp
        return before, self.max_hp, []

    def apply_attitude(self, delta: int) -> tuple[int, int]:
        before = self.attitude
        self.attitude = clamp(before + int(delta or 0))
        return before, self.attitude

    @classmethod
    def from_data(cls, d: dict) -> Actor:
        """统一实例化入口：按字段形态分派到 Character / NPC。

        含 race/background/inventory(dict) 视为玩家角色数据（core/character 惰性导入，
        避免 world.actor ↔ core.character 循环依赖）；否则按 NPC.from_dict 迁移构造。
        """
        d = dict(d)
        is_player = ("race" in d or "background" in d) and (
            "char_class" in d or "inventory" in d
        )
        if is_player:
            from core.character import Character
            return Character(**d)
        from world.entity import NPC
        return NPC.from_dict(d)
