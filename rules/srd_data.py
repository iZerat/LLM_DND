from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Optional

from resource.packs import active_pack_dir

# ── 技能 ──

def _srd_dir() -> Path:
    return active_pack_dir() / "srd"


def _load_json(name: str) -> list:
    fp = _srd_dir() / f"{name}.json"
    if not fp.exists():
        raise FileNotFoundError(f"缺少 SRD 资源文件: {fp}")
    return json.loads(fp.read_text(encoding="utf-8"))


_SKILLS_DATA = _load_json("skills")
SKILLS = list(_SKILLS_DATA["skills"])
SKILLS_EN = dict(_SKILLS_DATA["skills_en"])

SKILL_BY_EN = {v: k for k, v in SKILLS_EN.items()}
SKILL_ABILITY = dict(_SKILLS_DATA["skill_ability"])

ABILITIES = ["力量", "敏捷", "体质", "智力", "感知", "魅力"]
ABILITY_EN = {"力量": "strength", "敏捷": "dexterity", "体质": "constitution", "智力": "intelligence", "感知": "wisdom", "魅力": "charisma"}

_ALL_SKILLS = "*"


def _expand_options(opts) -> list[str]:
    if opts == _ALL_SKILLS:
        return list(SKILLS)
    return list(opts or [])

# ── 种族 ──

@dataclass
class Lineage:
    name: str
    traits: list[str] = field(default_factory=list)
    cantrips_known: list[str] = field(default_factory=list)
    spells_known: dict[int, list[str]] = field(default_factory=dict)
    name_en: str = ""

@dataclass
class Species:
    name: str
    size_options: list[str]
    speed: int
    traits: list[str] = field(default_factory=list)
    skill_choices: int = 0
    skill_options: list[str] = field(default_factory=list)
    lineages: list[Lineage] = field(default_factory=list)
    has_lineage: bool = False
    name_en: str = ""

    def trait_lines(self, lineage: Optional[str] = None) -> list[str]:
        lines = list(self.traits)
        if lineage and self.lineages:
            for lin in self.lineages:
                if lin.name == lineage:
                    lines.extend(lin.traits)
        return lines


def _build_species(raw: list) -> list[Species]:
    result = []
    for item in raw:
        d = dict(item)
        d["lineages"] = [Lineage(**lin) for lin in d.get("lineages", [])]
        d["skill_options"] = _expand_options(d.get("skill_options"))
        result.append(Species(**d))
    return result


SPECIES_LIST: list[Species] = _build_species(_load_json("species"))

# ── 背景 ──

@dataclass
class Background:
    name: str
    ability_scores: list[str]
    feat: str
    skill_proficiencies: list[str]
    tool_proficiency: str
    equipment_a: list[str]
    name_en: str = ""
    equipment_b_gp: int = 50


def _build_backgrounds(raw: list) -> list[Background]:
    return [Background(**dict(item)) for item in raw]


BACKGROUND_LIST: list[Background] = _build_backgrounds(_load_json("backgrounds"))

# ── 职业 ──

@dataclass
class ClassDef:
    name: str
    hit_die: int
    primary_ability: list[str]
    saving_throws: list[str]
    skill_choices: int
    skill_options: list[str]
    armor_profs: list[str] = field(default_factory=list)
    weapon_profs: list[str] = field(default_factory=list)
    tool_profs: list[str] = field(default_factory=list)
    name_en: str = ""
    starting_equipment_a: list[str] = field(default_factory=list)
    starting_equipment_b_gp: int = 75


def _build_classes(raw: list) -> list[ClassDef]:
    result = []
    for item in raw:
        d = dict(item)
        d["skill_options"] = _expand_options(d.get("skill_options"))
        result.append(ClassDef(**d))
    return result


CLASS_LIST: list[ClassDef] = _build_classes(_load_json("classes"))

# ── 护甲 ──

@dataclass
class Armor:
    name: str
    category: str
    base_ac: int
    dex_cap: int
    strength_req: int = 0
    stealth_disadvantage: bool = False
    cost: int = 0

ARMOR_LIST: list[Armor] = [
    Armor(name="布甲", category="无甲", base_ac=10, dex_cap=99, cost=0),
    Armor(name="棉甲", category="轻甲", base_ac=11, dex_cap=99, stealth_disadvantage=True, cost=5),
    Armor(name="皮甲", category="轻甲", base_ac=11, dex_cap=99, cost=10),
    Armor(name="镶钉皮甲", category="轻甲", base_ac=12, dex_cap=99, cost=45),
    Armor(name="兽皮甲", category="中甲", base_ac=12, dex_cap=2, cost=10),
    Armor(name="链甲衫", category="中甲", base_ac=13, dex_cap=2, cost=50),
    Armor(name="鳞甲", category="中甲", base_ac=14, dex_cap=2, stealth_disadvantage=True, cost=50),
    Armor(name="胸甲", category="中甲", base_ac=14, dex_cap=2, cost=400),
    Armor(name="半身板甲", category="中甲", base_ac=15, dex_cap=2, stealth_disadvantage=True, cost=750),
    Armor(name="环甲", category="重甲", base_ac=14, dex_cap=0, stealth_disadvantage=True, cost=30),
    Armor(name="链甲", category="重甲", base_ac=16, dex_cap=0, strength_req=13, stealth_disadvantage=True, cost=75),
    Armor(name="板条甲", category="重甲", base_ac=17, dex_cap=0, strength_req=15, stealth_disadvantage=True, cost=200),
    Armor(name="全身板甲", category="重甲", base_ac=18, dex_cap=0, strength_req=15, stealth_disadvantage=True, cost=1500),
    Armor(name="盾牌", category="盾牌", base_ac=2, dex_cap=99, cost=10),
]

# ── 武器 ──

@dataclass
class Weapon:
    name: str
    category: str
    damage_dice: str
    damage_type: str
    properties: list[str] = field(default_factory=list)
    cost: int = 0

WEAPON_LIST: list[Weapon] = [
    # 简易近战
    Weapon(name="木棍", category="简易近战", damage_dice="1d6", damage_type="钝击", properties=[" versatile(1d8)"]),
    Weapon(name="匕首", category="简易近战", damage_dice="1d4", damage_type="穿刺", properties=["娴熟", "轻型", "投掷(20/60)"]),
    Weapon(name="短矛", category="简易近战", damage_dice="1d6", damage_type="穿刺", properties=["投掷(20/60)", "versatile(1d8)"]),
    Weapon(name="手斧", category="简易近战", damage_dice="1d6", damage_type="挥砍", properties=["轻型", "投掷(20/60)"]),
    Weapon(name="标枪", category="简易近战", damage_dice="1d6", damage_type="穿刺", properties=["投掷(30/120)"]),
    Weapon(name="硬头锤", category="简易近战", damage_dice="1d6", damage_type="钝击", properties=[]),
    Weapon(name="镰刀", category="简易近战", damage_dice="1d4", damage_type="挥砍", properties=["轻型"]),
    Weapon(name="巨棒", category="简易近战", damage_dice="1d8", damage_type="钝击", properties=["双手"]),
    # 简易远程
    Weapon(name="轻弩", category="简易远程", damage_dice="1d8", damage_type="穿刺", properties=["弹药(80/320)", "装填", "双手"]),
    Weapon(name="短弓", category="简易远程", damage_dice="1d6", damage_type="穿刺", properties=["弹药(80/320)", "双手"]),
    Weapon(name="投石索", category="简易远程", damage_dice="1d4", damage_type="钝击", properties=["弹药(30/120)"]),
    # 军用近战
    Weapon(name="长剑", category="军用近战", damage_dice="1d8", damage_type="挥砍", properties=["versatile(1d10)"]),
    Weapon(name="巨剑", category="军用近战", damage_dice="2d6", damage_type="挥砍", properties=["重型", "双手"]),
    Weapon(name="巨斧", category="军用近战", damage_dice="1d12", damage_type="挥砍", properties=["重型", "双手"]),
    Weapon(name="战斧", category="军用近战", damage_dice="1d8", damage_type="挥砍", properties=["versatile(1d10)"]),
    Weapon(name="链枷", category="军用近战", damage_dice="1d8", damage_type="钝击", properties=[]),
    Weapon(name="长弓", category="军用远程", damage_dice="1d8", damage_type="穿刺", properties=["弹药(150/600)", "重型", "双手"]),
    Weapon(name="短剑", category="军用近战", damage_dice="1d6", damage_type="穿刺", properties=["娴熟", "轻型"]),
    Weapon(name="弯刀", category="军用近战", damage_dice="1d6", damage_type="挥砍", properties=["娴熟", "轻型"]),
    Weapon(name="细剑", category="军用近战", damage_dice="1d8", damage_type="穿刺", properties=["娴熟"]),
    Weapon(name="刺叉", category="军用近战", damage_dice="1d10", damage_type="挥砍", properties=["重型", "触及", "双手"]),
    Weapon(name="长枪", category="军用近战", damage_dice="1d10", damage_type="穿刺", properties=["重型", "触及", "双手"]),
    Weapon(name="战锤", category="军用近战", damage_dice="1d8", damage_type="钝击", properties=["versatile(1d10)"]),
    Weapon(name="巨锤", category="军用近战", damage_dice="2d6", damage_type="钝击", properties=["重型", "双手"]),
    Weapon(name="三叉戟", category="军用近战", damage_dice="1d8", damage_type="穿刺", properties=["投掷(20/60)", "versatile(1d10)"]),
    Weapon(name="手弩", category="军用远程", damage_dice="1d6", damage_type="穿刺", properties=["弹药(30/120)", "轻型", "装填"]),
    Weapon(name="重弩", category="军用远程", damage_dice="1d10", damage_type="穿刺", properties=["弹药(100/400)", "重型", "装填", "双手"]),
]

WEAPON_BY_NAME = {w.name: w for w in WEAPON_LIST}

# ── 查找函数 ──

def _build_index(items) -> dict:
    idx = {}
    for it in items:
        idx[it.name] = it
        if getattr(it, "name_en", ""):
            idx[it.name_en] = it
    return idx

_SPECIES_INDEX = _build_index(SPECIES_LIST)
_CLASS_INDEX = _build_index(CLASS_LIST)
_BACKGROUND_INDEX = _build_index(BACKGROUND_LIST)
_ARMOR_INDEX = {a.name: a for a in ARMOR_LIST}

def find_species(name: str) -> Optional[Species]:
    return _SPECIES_INDEX.get(name)

def find_class(name: str) -> Optional[ClassDef]:
    return _CLASS_INDEX.get(name)

def find_background(name: str) -> Optional[Background]:
    return _BACKGROUND_INDEX.get(name)

def find_armor(name: str) -> Optional[Armor]:
    return _ARMOR_INDEX.get(name)

def calc_ac(dex_mod: int, armor: object = "布甲", has_shield: bool = False) -> int:
    """按护甲计算 AC。armor 可为 ARMOR_LIST 中的名称，或带 base_ac/armor_category/dex_cap 的物品定义。"""
    name = getattr(armor, "name", None) or (armor if isinstance(armor, str) else "")
    arm = find_armor(name) if name else None
    if arm is None and getattr(armor, "base_ac", None):
        # 资源包物品（如战锤动力甲）：直接用物品字段
        base_ac = int(getattr(armor, "base_ac"))
        category = getattr(armor, "armor_category", "") or ""
        dex_cap = int(getattr(armor, "dex_cap", 99) or 99)
        if category in ("重甲", "heavy"):
            ac = base_ac
        elif category in ("中甲", "medium"):
            ac = base_ac + min(dex_mod, dex_cap)
        elif category in ("轻甲", "light"):
            ac = base_ac + dex_mod
        else:
            ac = 10 + dex_mod
        if has_shield:
            ac += 2
        return ac
    if arm is None:
        arm = ARMOR_LIST[0]
    if arm.category == "重甲":
        ac = arm.base_ac
    elif arm.category == "中甲":
        ac = arm.base_ac + min(dex_mod, arm.dex_cap)
    elif arm.category == "轻甲":
        ac = arm.base_ac + dex_mod
    else:
        ac = 10 + dex_mod
    if has_shield:
        ac += 2
    return ac


def reload():
    """按当前资源包重新加载 SRD（原地替换，保持已有引用）。"""
    global SKILLS, SKILLS_EN, SKILL_BY_EN, SKILL_ABILITY
    global SPECIES_LIST, BACKGROUND_LIST, CLASS_LIST
    global _SPECIES_INDEX, _CLASS_INDEX, _BACKGROUND_INDEX
    data = _load_json("skills")
    SKILLS[:] = list(data["skills"])
    SKILLS_EN.clear()
    SKILLS_EN.update(data["skills_en"])
    SKILL_BY_EN.clear()
    SKILL_BY_EN.update({v: k for k, v in SKILLS_EN.items()})
    SKILL_ABILITY.clear()
    SKILL_ABILITY.update(data["skill_ability"])
    SPECIES_LIST[:] = _build_species(_load_json("species"))
    BACKGROUND_LIST[:] = _build_backgrounds(_load_json("backgrounds"))
    CLASS_LIST[:] = _build_classes(_load_json("classes"))
    _SPECIES_INDEX.clear()
    _SPECIES_INDEX.update(_build_index(SPECIES_LIST))
    _CLASS_INDEX.clear()
    _CLASS_INDEX.update(_build_index(CLASS_LIST))
    _BACKGROUND_INDEX.clear()
    _BACKGROUND_INDEX.update(_build_index(BACKGROUND_LIST))
