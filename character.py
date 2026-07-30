from dataclasses import dataclass, field, asdict
import yaml
from pathlib import Path


RACES = ["人类", "精灵", "矮人", "半身人", "龙裔", "半精灵", "半兽人", "侏儒", "提夫林"]
CLASSES = ["战士", "法师", "游侠", "盗贼", "牧师", "圣骑士", "德鲁伊", "术士", "吟游诗人", "武僧", "野蛮人", "邪术师"]
BACKGROUNDS = ["贵族", "流浪儿", "学者", "士兵", "罪犯", "艺人", "水手", "隐士", "商贩", "工匠"]

HIT_DICE = {
    "战士": 12, "圣骑士": 12, "野蛮人": 12,
    "游侠": 10, "德鲁伊": 10,
    "武僧": 8, "盗贼": 8, "邪术师": 8, "吟游诗人": 8, "术士": 8, "牧师": 8,
    "法师": 6,
}

ARMOR_BY_CLASS = {
    "战士": 18, "圣骑士": 18, "野蛮人": 14,
    "游侠": 15, "德鲁伊": 14,
    "武僧": 14, "盗贼": 14, "邪术师": 13, "吟游诗人": 13, "术士": 12, "牧师": 16,
    "法师": 12,
}

CLASS_DEFAULT_SKILLS = {
    "战士": ["运动", "察觉"],
    "法师": ["调查", "魔法"],
    "游侠": ["察觉", "生存"],
    "盗贼": ["隐匿", "巧手"],
    "牧师": ["洞察", "医药"],
    "圣骑士": ["游说", "宗教"],
    "德鲁伊": ["自然", "驯兽"],
    "术士": ["欺瞒", "游说"],
    "吟游诗人": ["表演", "游说"],
    "武僧": ["特技", "察觉"],
    "野蛮人": ["运动", "生存"],
    "邪术师": ["欺瞒", "调查"],
}

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
    def ac(self) -> int:
        if self.char_class in ARMOR_BY_CLASS:
            return ARMOR_BY_CLASS[self.char_class]
        return 10 + modifier(self.dexterity)

    @property
    def prof_bonus(self) -> int:
        return proficiency_bonus(self.level)

    def stats_block(self) -> str:
        return (
            f"STR:{self.strength}{mod_str(self.strength)}  "
            f"DEX:{self.dexterity}{mod_str(self.dexterity)}  "
            f"CON:{self.constitution}{mod_str(self.constitution)}\n"
            f"INT:{self.intelligence}{mod_str(self.intelligence)}  "
            f"WIS:{self.wisdom}{mod_str(self.wisdom)}  "
            f"CHA:{self.charisma}{mod_str(self.charisma)}"
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
        return (
            f"【{self.name}】Lv.{self.level} {self.race} {self.char_class}\n"
            f"背景: {self.background}  HP: {self.hp}/{self.max_hp}  AC: {self.ac}\n"
            f"力量:{self.strength} 敏捷:{self.dexterity} 体质:{self.constitution}\n"
            f"智力:{self.intelligence} 感知:{self.wisdom} 魅力:{self.charisma}\n"
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
