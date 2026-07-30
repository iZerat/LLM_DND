from dataclasses import dataclass, field, asdict
import yaml
from pathlib import Path
from srd_data import (
    SPECIES_LIST, CLASS_LIST, BACKGROUND_LIST, SKILLS,
    WEAPON_BY_NAME, calc_ac, find_species, find_class, find_background,
)

RACES = [s.name for s in SPECIES_LIST]
CLASSES = [c.name for c in CLASS_LIST]
BACKGROUNDS = [b.name for b in BACKGROUND_LIST]

HIT_DICE = {c.name: c.hit_die for c in CLASS_LIST}

EQUIPMENT_SLOTS = ["武器", "副手", "头部", "身体", "背部", "项链", "戒指1", "戒指2"]


def modifier(score: int) -> int:
    return (score - 10) // 2


def mod_str(score: int) -> str:
    m = modifier(score)
    return f"{m:+d}"


def proficiency_bonus(level: int) -> int:
    return ((level - 1) // 4) + 2


@dataclass
class Combatant:
    name: str = "未知"
    ac: int = 10
    hp: int = 10
    max_hp: int = 10

    def status_line(self) -> str:
        return f"{self.name}  AC:{self.ac}  HP:{self.hp}/{self.max_hp}"


@dataclass
class Character:
    name: str = ""
    race: str = ""
    lineage: str = ""
    char_class: str = ""
    background: str = ""
    level: int = 1
    hp: int = 10
    max_hp: int = 10
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10
    inventory: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    saving_throws: list = field(default_factory=list)
    feats: list = field(default_factory=list)
    description: str = ""
    gender: str = "未知"
    age: str = "成年"
    gp: int = 30
    sp: int = 0
    cp: int = 0

    def __post_init__(self):
        self.normalize_currency()

    def normalize_currency(self):
        if self.cp >= 100:
            self.sp += self.cp // 100
            self.cp = self.cp % 100
        if self.sp >= 100:
            self.gp += self.sp // 100
            self.sp = self.sp % 100
    equipment: dict = field(default_factory=lambda: {
        "武器": "", "副手": "", "头部": "", "身体": "",
        "背部": "", "项链": "", "戒指1": "", "戒指2": "",
    })

    @property
    def dex_mod(self) -> int:
        return modifier(self.dexterity)

    @property
    def ac(self) -> int:
        body_armor = self.equipment.get("身体", "")
        has_shield = bool(self.equipment.get("副手", "") and "盾" in self.equipment["副手"])
        if body_armor:
            return calc_ac(self.dex_mod, body_armor, has_shield)
        return 10 + self.dex_mod + (2 if has_shield else 0)

    @property
    def prof_bonus(self) -> int:
        return proficiency_bonus(self.level)

    def species_trait_lines(self) -> list[str]:
        sp = find_species(self.race)
        if not sp:
            return []
        return sp.trait_lines(self.lineage if self.lineage else None)

    def stats_block(self) -> str:
        return (
            f"力量:{self.strength}{mod_str(self.strength)}  "
            f"敏捷:{self.dexterity}{mod_str(self.dexterity)}  "
            f"体质:{self.constitution}{mod_str(self.constitution)}\n"
            f"智力:{self.intelligence}{mod_str(self.intelligence)}  "
            f"感知:{self.wisdom}{mod_str(self.wisdom)}  "
            f"魅力:{self.charisma}{mod_str(self.charisma)}"
        )

    def player_status(self) -> str:
        return (
            f"{self.name}  Lv.{self.level} {self.race} {self.char_class}\n"
            f"AC:{self.ac}  HP:{self.hp}/{self.max_hp}  熟练:{self.prof_bonus:+d}"
        )

    def currency_str(self) -> str:
        return f"{self.gp}金 {self.sp}银 {self.cp}铜"

    def equip_summary(self) -> str:
        worn = [f"{s}:{v}" for s, v in self.equipment.items() if v]
        return " | ".join(worn) if worn else "无装备"

    def summary(self) -> str:
        lineage_str = f"（{self.lineage}）" if self.lineage else ""
        traits = "；".join(self.species_trait_lines())
        save_str = "、".join(self.saving_throws) if self.saving_throws else "无"
        feat_str = "、".join(self.feats) if self.feats else "无"
        return (
            f"【{self.name}】Lv.{self.level} {self.race}{lineage_str} {self.char_class}\n"
            f"背景: {self.background}  HP: {self.hp}/{self.max_hp}  AC: {self.ac}\n"
            f"力量:{self.strength} 敏捷:{self.dexterity} 体质:{self.constitution}\n"
            f"智力:{self.intelligence} 感知:{self.wisdom} 魅力:{self.charisma}\n"
            f"熟练豁免: {save_str}  专长: {feat_str}\n"
            f"种族特性: {traits}\n"
            f"装备: {self.equip_summary()}\n"
            f"背包: {', '.join(self.inventory) if self.inventory else '空'}\n"
            f"金币: {self.currency_str()}\n"
            f"描述: {self.description}"
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str):
        Path(path).write_text(yaml.dump(self.to_dict(), allow_unicode=True), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "Character":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(**data)
