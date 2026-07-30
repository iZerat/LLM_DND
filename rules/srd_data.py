from dataclasses import dataclass, field
from typing import Optional

# ── 技能 ──

SKILLS = [
    "特技", "驯兽", "奥秘", "运动", "欺瞒", "历史",
    "洞察", "威吓", "调查", "医药", "自然", "察觉",
    "表演", "游说", "宗教", "巧手", "隐匿", "生存",
]


SKILLS_EN = {
    "acrobatics": "特技", "animal_handling": "驯兽", "arcana": "奥秘",
    "athletics": "运动", "deception": "欺瞒", "history": "历史",
    "insight": "洞察", "intimidation": "威吓", "investigation": "调查",
    "medicine": "医药", "nature": "自然", "perception": "察觉",
    "performance": "表演", "persuasion": "游说", "religion": "宗教",
    "sleight_of_hand": "巧手", "stealth": "隐匿", "survival": "生存",
}

SKILL_BY_EN = {v: k for k, v in SKILLS_EN.items()}
SKILL_ABILITY = {
    "特技": "敏捷", "驯兽": "感知", "奥秘": "智力", "运动": "力量",
    "欺瞒": "魅力", "历史": "智力", "洞察": "感知", "威吓": "魅力",
    "调查": "智力", "医药": "感知", "自然": "智力", "察觉": "感知",
    "表演": "魅力", "游说": "魅力", "宗教": "智力", "巧手": "敏捷",
    "隐匿": "敏捷", "生存": "感知",
}

ABILITIES = ["力量", "敏捷", "体质", "智力", "感知", "魅力"]
ABILITY_EN = {"力量": "strength", "敏捷": "dexterity", "体质": "constitution", "智力": "intelligence", "感知": "wisdom", "魅力": "charisma"}

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

SPECIES_LIST: list[Species] = [
    Species(name="龙裔", name_en="dragonborn", size_options=["中型"], speed=30,
        traits=["黑暗视觉：60尺", "龙族先祖（自选一种龙类决定吐息伤害类型与抗性）", "吐息武器：15尺锥形/30尺线形，DC=8+体质调整+熟练，1d10伤害", "伤害抗性：根据龙族先祖类型", "5级：龙翼飞行（附赠动作，10分钟飞行）"],
        skill_choices=0),
    Species(name="矮人", name_en="dwarf", size_options=["中型"], speed=30,
        traits=["黑暗视觉：120尺", "矮人韧性：毒素伤害抗性，中毒豁免优势", "矮人体魄：HP上限+1，每级再+1", "石之感应：附赠动作获得60尺震颤感知10分钟"],
        skill_choices=0),
    Species(name="精灵", name_en="elf", size_options=["中型"], speed=30,
        traits=["黑暗视觉：60尺", "妖精血统：魅惑豁免优势", "敏锐感官：自选获得洞察/察觉/生存之一熟练", "精制：无需睡眠，4小时长休"],
        skill_choices=1, skill_options=["洞察", "察觉", "生存"],
        has_lineage=True,
        lineages=[
            Lineage(name="黑暗精灵", name_en="dark_elf", traits=["黑暗视觉提升至120尺", "已知舞光术戏法", "3级获得妖火", "5级获得黑暗术"]),
            Lineage(name="高等精灵", name_en="high_elf", traits=["已知魔法伎俩戏法（可每日切换为任意法师戏法）", "3级获得侦测魔法", "5级获得迷踪步"]),
            Lineage(name="木精灵", name_en="wood_elf", traits=["速度提升至35尺", "已知德鲁伊伎俩戏法", "3级获得大步奔行", "5级获得行动无踪"]),
        ]),
    Species(name="半身人", name_en="halfling", size_options=["小型"], speed=30,
        traits=["勇敢：恐惧豁免优势", "半身人灵巧：可通过体型大于你的生物空间", "幸运：D20投出1时可重掷", "天生隐匿：被大型以上生物遮挡时即可躲藏"],
        skill_choices=0),
    Species(name="侏儒", name_en="gnome", size_options=["小型"], speed=30,
        traits=["黑暗视觉：60尺", "侏儒狡黠：智力/感知/魅力豁免优势"],
        has_lineage=True,
        lineages=[
            Lineage(name="森林侏儒", name_en="forest_gnome", traits=["已知魔法伎俩戏法", "动物交谈术：可随意准备，每日熟练次数免费施展"]),
            Lineage(name="岩石侏儒", name_en="rock_gnome", traits=["已知修复术和魔法伎俩", "可制作小型发条装置（AC5，HP1，最多3个，持续8小时）"]),
        ]),
    Species(name="哥利亚", name_en="goliath", size_options=["中型"], speed=35,
        traits=["巨人先祖（自选一项，熟练次数/长休）：云之瞬移（附赠30尺传送）、火之灼烧（命中+1d10火）、冰之寒意（命中+1d6冰+减速10尺）、山之击倒（命中大型以下应击倒）、石之忍耐（反应1d12+体质减伤）、雷之回响（反应60尺内1d8雷鸣）", "5级：巨大化（附赠变大型10分钟，力量优势，速度+10）", "强力体格：挣脱擒抱优势，负重算作大一级"]),
    Species(name="人类", name_en="human", size_options=["中型", "小型"], speed=30,
        traits=["智勇双全：每次长休后获得英雄 inspirations", "技巧娴熟：自选一项技能熟练", "多才多艺：获得一个起源专长"],
        skill_choices=1, skill_options=SKILLS),
    Species(name="兽人", name_en="orc", size_options=["中型"], speed=30,
        traits=["黑暗视觉：120尺", "肾上腺素爆发：附赠动作疾走，获得熟练项临时HP，熟练次数/长休", "不屈不挠：HP归0时若非即死则改为1HP，每长休一次"]),
    Species(name="提夫林", name_en="tiefling", size_options=["中型", "小型"], speed=30,
        traits=["黑暗视觉：60尺", "异界存在：已知奇术戏法"],
        has_lineage=True,
        lineages=[
            Lineage(name="深渊血脉", name_en="abyssal", traits=["毒素伤害抗性", "已知毒云术戏法", "3级获得疾病射线", "5级获得人类定身术"]),
            Lineage(name="冥界血脉", name_en="infernal", traits=["黯蚀伤害抗性", "已知冻寒之触戏法", "3级获得虚假生命", "5级获得衰弱射线"]),
            Lineage(name="炼狱血脉", name_en="hellish", traits=["火焰伤害抗性", "已知火焰箭戏法", "3级获得炼狱叱喝", "5级获得黑暗术"]),
        ]),
]

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

BACKGROUND_LIST: list[Background] = [
    Background(name="贵族", name_en="noble", ability_scores=["智力", "感知", "魅力"], feat="熟练（Skilled）",
        skill_proficiencies=["历史", "游说"], tool_proficiency="棋盘套装",
        equipment_a=["精致服装", "印戒", "身份文书", "钱包（20金）", "香水", "旅行者服装"]),
    Background(name="流浪儿", name_en="urchin", ability_scores=["敏捷", "体质", "智力"], feat="幸运（Lucky）",
        skill_proficiencies=["巧手", "隐匿"], tool_proficiency="盗贼工具",
        equipment_a=["2把匕首", "盗贼工具", "地图", "旅行者服装", "钱包（10金）", "灯笼"]),
    Background(name="学者", name_en="sage", ability_scores=["体质", "智力", "感知"], feat="魔法学徒（法师）",
        skill_proficiencies=["奥秘", "历史"], tool_proficiency="书法工具",
        equipment_a=["木棍", "书法工具", "历史书", "8张羊皮纸", "长袍", "8金币"]),
    Background(name="士兵", name_en="soldier", ability_scores=["力量", "敏捷", "体质"], feat="凶蛮打击（Savage Attacker）",
        skill_proficiencies=["运动", "威吓"], tool_proficiency="棋盘套装",
        equipment_a=["长矛", "短弓", "20支箭", "棋盘套装", "医疗包", "箭袋", "旅行者服装", "14金币"]),
    Background(name="罪犯", name_en="criminal", ability_scores=["敏捷", "体质", "智力"], feat="警觉（Alert）",
        skill_proficiencies=["巧手", "隐匿"], tool_proficiency="盗贼工具",
        equipment_a=["2把匕首", "盗贼工具", "撬棍", "2个钱包", "旅行者服装", "16金币"]),
    Background(name="艺人", name_en="entertainer", ability_scores=["敏捷", "魅力", "感知"], feat="音乐家（Musician）",
        skill_proficiencies=["表演", "欺瞒"], tool_proficiency="一种乐器",
        equipment_a=["乐器", "戏服", "镜子", "香水", "旅行者服装", "15金币"]),
    Background(name="水手", name_en="sailor", ability_scores=["力量", "体质", "感知"], feat="健壮（Tough）",
        skill_proficiencies=["运动", "察觉"], tool_proficiency="导航工具",
        equipment_a=["短矛", "50尺绳子", "攀爬钩", "水袋", "旅行者服装", "12金币"]),
    Background(name="隐士", name_en="hermit", ability_scores=["体质", "感知", "魅力"], feat="治疗师（Healer）",
        skill_proficiencies=["医药", "宗教"], tool_proficiency="草药工具",
        equipment_a=["医疗包", "草药工具", "毛毯", "5根蜡烛", "圣水", "旅行者服装", "5金币"]),
    Background(name="商贩", name_en="merchant", ability_scores=["智力", "魅力", "感知"], feat="工匠（Crafter）",
        skill_proficiencies=["洞察", "游说"], tool_proficiency="一种工匠工具",
        equipment_a=["工匠工具", "天秤", "10尺布料", "墨水笔", "账本", "旅行者服装", "25金币"]),
    Background(name="工匠", name_en="artisan", ability_scores=["力量", "敏捷", "智力"], feat="工匠（Crafter）",
        skill_proficiencies=["调查", "察觉"], tool_proficiency="一种工匠工具",
        equipment_a=["工匠工具", "锤子", "10根铁钉", "毛毯", "旅行者服装", "20金币"]),
]

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

CLASS_LIST: list[ClassDef] = [
    ClassDef(name="野蛮人", name_en="barbarian", hit_die=12, primary_ability=["力量"],
        saving_throws=["力量", "体质"], skill_choices=2,
        skill_options=["驯兽", "运动", "威吓", "自然", "察觉", "生存"],
        armor_profs=["轻甲", "中甲", "盾牌"], weapon_profs=["简易武器", "军用武器"],
        starting_equipment_a=["巨斧", "4把手斧", "探险家套装", "15金币"], starting_equipment_b_gp=75),
    ClassDef(name="吟游诗人", name_en="bard", hit_die=8, primary_ability=["魅力"],
        saving_throws=["敏捷", "魅力"], skill_choices=3,
        skill_options=SKILLS,  # 任何技能
        armor_profs=["轻甲"], weapon_profs=["简易武器"],
        tool_profs=["三种乐器"],
        starting_equipment_a=["皮甲", "2把匕首", "乐器", "艺人套装", "19金币"], starting_equipment_b_gp=90),
    ClassDef(name="牧师", name_en="cleric", hit_die=8, primary_ability=["感知"],
        saving_throws=["感知", "魅力"], skill_choices=2,
        skill_options=["历史", "洞察", "医药", "游说", "宗教"],
        armor_profs=["轻甲", "中甲", "盾牌"], weapon_profs=["简易武器"],
        starting_equipment_a=["链甲衫", "盾牌", "硬头锤", "圣徽", "牧师套装", "7金币"], starting_equipment_b_gp=110),
    ClassDef(name="德鲁伊", name_en="druid", hit_die=8, primary_ability=["感知"],
        saving_throws=["智力", "感知"], skill_choices=2,
        skill_options=["驯兽", "奥秘", "洞察", "医药", "自然", "察觉", "宗教", "生存"],
        armor_profs=["轻甲", "盾牌"], weapon_profs=["简易武器"],
        tool_profs=["草药工具"],
        starting_equipment_a=["皮甲", "盾牌", "镰刀", "德鲁伊法器（橡木法杖）", "探险家套装", "草药工具", "9金币"], starting_equipment_b_gp=50),
    ClassDef(name="战士", name_en="fighter", hit_die=10, primary_ability=["力量", "敏捷"],
        saving_throws=["力量", "体质"], skill_choices=2,
        skill_options=["特技", "驯兽", "运动", "历史", "洞察", "威吓", "游说", "察觉", "生存"],
        armor_profs=["轻甲", "中甲", "重甲", "盾牌"], weapon_profs=["简易武器", "军用武器"],
        starting_equipment_a=["链甲", "巨剑", "链枷", "8支标枪", "地下城套装", "4金币"], starting_equipment_b_gp=155),
    ClassDef(name="武僧", name_en="monk", hit_die=8, primary_ability=["敏捷", "感知"],
        saving_throws=["力量", "敏捷"], skill_choices=2,
        skill_options=["特技", "运动", "历史", "洞察", "宗教", "隐匿"],
        armor_profs=[], weapon_profs=["简易武器", "轻型军用武器"],
        tool_profs=["一种工匠工具或乐器"],
        starting_equipment_a=["长矛", "5把匕首", "工匠工具或乐器", "探险家套装", "11金币"], starting_equipment_b_gp=50),
    ClassDef(name="圣骑士", name_en="paladin", hit_die=10, primary_ability=["力量", "魅力"],
        saving_throws=["感知", "魅力"], skill_choices=2,
        skill_options=["运动", "洞察", "威吓", "医药", "游说", "宗教"],
        armor_profs=["轻甲", "中甲", "重甲", "盾牌"], weapon_profs=["简易武器", "军用武器"],
        starting_equipment_a=["链甲", "盾牌", "长剑", "6支标枪", "圣徽", "牧师套装", "9金币"], starting_equipment_b_gp=150),
    ClassDef(name="游侠", name_en="ranger", hit_die=10, primary_ability=["敏捷", "感知"],
        saving_throws=["力量", "敏捷"], skill_choices=3,
        skill_options=["驯兽", "运动", "洞察", "调查", "自然", "察觉", "隐匿", "生存"],
        armor_profs=["轻甲", "中甲", "盾牌"], weapon_profs=["简易武器", "军用武器"],
        starting_equipment_a=["镶钉皮甲", "弯刀", "短剑", "长弓", "20支箭", "箭袋", "德鲁伊法器", "探险家套装", "7金币"], starting_equipment_b_gp=150),
    ClassDef(name="盗贼", name_en="rogue", hit_die=8, primary_ability=["敏捷"],
        saving_throws=["敏捷", "智力"], skill_choices=4,
        skill_options=["特技", "运动", "欺瞒", "洞察", "威吓", "调查", "察觉", "游说", "巧手", "隐匿"],
        armor_profs=["轻甲"], weapon_profs=["简易武器", "娴熟或轻型军用武器"],
        tool_profs=["盗贼工具"],
        starting_equipment_a=["皮甲", "2把匕首", "短剑", "短弓", "20支箭", "箭袋", "盗贼工具", "窃贼套装", "8金币"], starting_equipment_b_gp=100),
    ClassDef(name="术士", name_en="sorcerer", hit_die=6, primary_ability=["魅力"],
        saving_throws=["体质", "魅力"], skill_choices=2,
        skill_options=["奥秘", "欺瞒", "洞察", "威吓", "游说", "宗教"],
        armor_profs=[], weapon_profs=["简易武器"],
        starting_equipment_a=["长矛", "2把匕首", "奥术法器（水晶）", "地下城套装", "28金币"], starting_equipment_b_gp=50),
    ClassDef(name="邪术师", name_en="warlock", hit_die=8, primary_ability=["魅力"],
        saving_throws=["感知", "魅力"], skill_choices=2,
        skill_options=["奥秘", "欺瞒", "历史", "威吓", "调查", "自然", "宗教"],
        armor_profs=["轻甲"], weapon_profs=["简易武器"],
        starting_equipment_a=["皮甲", "镰刀", "2把匕首", "奥术法器（魔珠）", "神秘学书", "学者套装", "15金币"], starting_equipment_b_gp=100),
    ClassDef(name="法师", name_en="wizard", hit_die=6, primary_ability=["智力"],
        saving_throws=["智力", "感知"], skill_choices=2,
        skill_options=["奥秘", "历史", "洞察", "调查", "医药", "自然", "宗教"],
        armor_profs=[], weapon_profs=["简易武器"],
        starting_equipment_a=["2把匕首", "奥术法器（木棍）", "长袍", "法术书", "学者套装", "5金币"], starting_equipment_b_gp=55),
]

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

def find_species(name: str) -> Optional[Species]:
    for s in SPECIES_LIST:
        if s.name == name or s.name_en == name:
            return s
    return None

def find_class(name: str) -> Optional[ClassDef]:
    for c in CLASS_LIST:
        if c.name == name or c.name_en == name:
            return c
    return None

def find_background(name: str) -> Optional[Background]:
    for b in BACKGROUND_LIST:
        if b.name == name or b.name_en == name:
            return b
    return None

def find_armor(name: str) -> Optional[Armor]:
    for a in ARMOR_LIST:
        if a.name == name:
            return a
    return None

def calc_ac(dex_mod: int, armor_name: str = "布甲", has_shield: bool = False) -> int:
    arm = find_armor(armor_name) or ARMOR_LIST[0]
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
