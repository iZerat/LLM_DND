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

    def apply_hp(self, delta: int, crit: bool = False, non_lethal: bool = False) -> tuple[int, int, list[str]]:
        """0 HP 语义对齐 RAW（rules/playing-the-game.md）：
        - 非致命打击 non_lethal（L1205）：目标降至 1 HP + 昏迷，不杀死
        - 角色类 NPC（is_character）：0 HP → 昏迷 + 死亡豁免（L1229；GM 破例 L1217）
        - 怪物类 NPC（默认）：0 HP → 即死（L1217）
        - 巨量伤害（余量 ≥ 生命上限）→ 即死（L1221）
        """
        before = self.hp
        if self.dead:
            return before, self.hp, [f"{self.name} 已死亡，无法变更 HP"]
        notes: list[str] = []
        if delta > 0:
            new = min(self.hp + int(delta or 0), self.max_hp)
            self.hp = new
            if before <= 0 < new or self.knocked_out:
                self.knocked_out = False
                self.stable = False
                self.death_fails = 0
                self.death_successes = 0
                notes.append("苏醒")
            return before, self.hp, notes
        if delta < 0:
            amount = -int(delta or 0)
            if non_lethal and amount > 0 and before > 0:
                self.hp = max(self.hp - amount, 1)
                self.knocked_out = True
                self.stable = False
                self.death_fails = 0
                self.death_successes = 0
                notes.append("非致命击昏（保留 1 点生命，昏迷）")
                return before, self.hp, notes
            self.hp = max(self.hp - amount, 0)
            if self.hp == 0 and amount > 0:
                if before == 0:
                    if self.is_character:
                        fails = 2 if crit else 1
                        self.death_fails += fails
                        notes.append(f"死亡豁免失败 {fails} 次（{self.death_fails}/3）")
                        if self.death_fails >= 3:
                            self.dead = True
                            notes.append("死亡")
                    else:
                        notes.append("（已倒地，无法再改变状态）")
                else:
                    remaining = amount - before
                    if remaining >= self.max_hp:
                        self.dead = True
                        notes.append("即死（巨量伤害 ≥ 生命上限）")
                    elif self.is_character:
                        notes.append("昏迷（重要角色，进入死亡豁免）")
                    else:
                        self.dead = True
                        notes.append("即死")
        return before, self.hp, notes

    def apply_max_hp(self, delta: int) -> tuple[int, int, list[str]]:
        before = self.max_hp
        if self.dead:
            return before, self.max_hp, [f"{self.name} 已死亡，无法变更最大HP"]
        self.max_hp = max(self.max_hp + int(delta or 0), 1)
        if self.hp > self.max_hp:
            self.hp = self.max_hp
        return before, self.max_hp, []
