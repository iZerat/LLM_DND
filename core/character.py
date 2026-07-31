from dataclasses import dataclass, field, asdict
import re
from pathlib import Path
from typing import Optional
from loc import tr
from rules.srd_data import (
    SPECIES_LIST, CLASS_LIST, BACKGROUND_LIST, SKILLS, SKILLS_EN,
    WEAPON_BY_NAME, calc_ac, find_species, find_class, find_background,
)
from resource.models import Inventory, ItemInstance
from resource.item_db import item_db

RACES = [s.name for s in SPECIES_LIST]
CLASSES = [c.name for c in CLASS_LIST]
BACKGROUNDS = [b.name for b in BACKGROUND_LIST]
HIT_DICE = {c.name: c.hit_die for c in CLASS_LIST}


def modifier(score: int) -> int:
    return (score - 10) // 2


def mod_str(score: int) -> str:
    m = modifier(score)
    return f"{m:+d}"


def proficiency_bonus(level: int) -> int:
    return ((level - 1) // 4) + 2


def strip_en_parens(text: str) -> str:
    """去掉纯英文括号内容（如 治疗师（Healer）→治疗师），保留中文括号（如 魔法学徒（法师））。"""
    return re.sub(r"[（(][A-Za-z0-9 _+/-]+[）)]", "", text).strip()


@dataclass
class Combatant:
    name: str = tr("unknown")
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
    skills: list = field(default_factory=list)
    saving_throws: list = field(default_factory=list)
    feats: list = field(default_factory=list)
    description: str = ""
    gender: str = "male"
    age: int = 20
    inventory: Inventory = field(default_factory=Inventory)

    @property
    def dex_mod(self) -> int:
        return modifier(self.dexterity)

    @property
    def ac(self) -> int:
        body_inst = self.inventory.get_equipped("body")
        shield_guid = self.inventory.equipped.get("off_hand")
        has_shield = False
        if shield_guid:
            sd = item_db.get(shield_guid)
            if sd and sd.type.value == "shield":
                has_shield = True
        if body_inst and body_inst.guid:
            body_def = item_db.get(body_inst.guid)
            if body_def and body_def.base_ac:
                return calc_ac(self.dex_mod, body_def.name, has_shield)
        return 10 + self.dex_mod + (2 if has_shield else 0)

    @property
    def prof_bonus(self) -> int:
        return proficiency_bonus(self.level)

    @property
    def race_cn(self) -> str:
        sp = find_species(self.race)
        return sp.name if sp else self.race

    @property
    def class_cn(self) -> str:
        cd = find_class(self.char_class)
        return cd.name if cd else self.char_class

    @property
    def bg_cn(self) -> str:
        bg = find_background(self.background)
        return bg.name if bg else self.background

    @property
    def lineage_cn(self) -> str:
        if not self.lineage:
            return ""
        sp = find_species(self.race)
        if sp and sp.lineages:
            for lin in sp.lineages:
                if lin.name_en == self.lineage or lin.name == self.lineage:
                    return lin.name
        return self.lineage

    def species_trait_lines(self) -> list[str]:
        sp = find_species(self.race)
        if not sp:
            return []
        return sp.trait_lines(self.lineage if self.lineage else None)

    def stats_block(self) -> str:
        return (
            f"{tr('stat:strength')}:{self.strength}{mod_str(self.strength)}  "
            f"{tr('stat:dexterity')}:{self.dexterity}{mod_str(self.dexterity)}  "
            f"{tr('stat:constitution')}:{self.constitution}{mod_str(self.constitution)}\n"
            f"{tr('stat:intelligence')}:{self.intelligence}{mod_str(self.intelligence)}  "
            f"{tr('stat:wisdom')}:{self.wisdom}{mod_str(self.wisdom)}  "
            f"{tr('stat:charisma')}:{self.charisma}{mod_str(self.charisma)}"
        )

    def player_status(self) -> str:
        return (
            f"{self.name}  Lv.{self.level} {self.race_cn} {self.class_cn}\n"
            f"AC:{self.ac}  HP:{self.hp}/{self.max_hp}  "
            f"{tr('general:prof_bonus')}:{self.prof_bonus:+d}"
        )

    def currency_str(self) -> str:
        return str(self.inventory.currency)

    def equip_summary(self) -> str:
        worn = []
        for slot_key in ["weapon", "off_hand", "head", "body", "back", "neck", "ring1", "ring2"]:
            guid = self.inventory.equipped.get(slot_key)
            if guid:
                item_def = item_db.get(guid)
                name = item_def.name if item_def else guid
                slot_cn = tr(f"slot:{slot_key}")
                worn.append(f"{slot_cn}:{name}")
        return " | ".join(worn) if worn else tr("general:none")

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("inventory", None)
        return d

    def summary(self) -> str:
        lineage_str = f"({self.lineage_cn})" if self.lineage else ""
        traits = "；".join(self.species_trait_lines())
        save_str = "、".join(self.saving_throws) if self.saving_throws else tr("general:none")
        feat_str = "、".join(strip_en_parens(f) for f in self.feats) if self.feats else tr("general:none")
        bag_list = []
        for inst in self.inventory.all_instances():
            item_def = item_db.get(inst.guid)
            name = item_def.name if item_def else inst.guid
            bag_list.append(name)
        bag_str = ", ".join(bag_list) if bag_list else tr("general:none")
        gender_cn = tr(f"gender:{self.gender}")
        return (
            f"【{self.name}】Lv.{self.level} {self.race_cn}{lineage_str} {self.class_cn}\n"
            f"{tr('general:bg')}: {self.bg_cn}  {tr('general:hp')}: {self.hp}/{self.max_hp}  "
            f"{tr('general:ac')}: {self.ac}\n"
            f"{tr('general:gender')}: {gender_cn}  {tr('general:age')}: {self.age}\n"
            f"{tr('stat:strength')}:{self.strength} "
            f"{tr('stat:dexterity')}:{self.dexterity} "
            f"{tr('stat:constitution')}:{self.constitution}\n"
            f"{tr('stat:intelligence')}:{self.intelligence} "
            f"{tr('stat:wisdom')}:{self.wisdom} "
            f"{tr('stat:charisma')}:{self.charisma}\n"
            f"{tr('general:save')}: {save_str}  {tr('general:feats')}: {feat_str}\n"
            f"{tr('general:traits')}: {traits}\n"
            f"{tr('general:equip')}: {self.equip_summary()}\n"
            f"{tr('general:bag')}: {bag_str}\n"
            f"{tr('general:money')}: {self.currency_str()}\n"
            f"{tr('general:desc')}: {self.description}"
        )
