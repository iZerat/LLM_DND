"""角色随机生成（roll）独立模块。

快速创建 / 详细创建（掷骰属性） / 角色模板 共用。
所有随机决策集中于此，便于预览、重掷与单测。
"""
from __future__ import annotations
import random

from core.character import Character, RACES, CLASSES, BACKGROUNDS, HIT_DICE
from rules.srd_data import SKILL_BY_EN, find_species, find_class, find_background

ATTRS_CN = ["力量", "敏捷", "体质", "智力", "感知", "魅力"]

_FANTASY_NAMES = ["艾琳", "索恩", "灰风", "夜影", "石心", "霜牙", "火鬃", "刃歌", "晨星", "雾行"]


# ── 单项随机 ──

def random_name() -> str:
    return random.choice(_FANTASY_NAMES)


def roll_species() -> tuple[str, str, str]:
    """随机种族 → (种族中文, 种族英文, 流派英文)。"""
    species_cn = random.choice(RACES)
    sp = find_species(species_cn)
    race_en = sp.name_en if sp else species_cn
    lineage = ""
    if sp and sp.lineages:
        lin = random.choice(sp.lineages)
        lineage = lin.name_en or lin.name
    return species_cn, race_en, lineage


def roll_class() -> tuple[str, str]:
    """随机职业 → (职业中文, 职业英文)。"""
    class_cn = random.choice(CLASSES)
    cd = find_class(class_cn)
    return class_cn, (cd.name_en if cd else class_cn)


def roll_background() -> tuple[str, str, str]:
    """随机背景 → (背景中文, 背景英文, 专长)。"""
    bg_cn = random.choice(BACKGROUNDS)
    bg = find_background(bg_cn)
    bg_en = bg.name_en if bg else bg_cn
    feat = bg.feat if bg else ""
    return bg_cn, bg_en, feat


def _roll_4d6() -> int:
    """4d6 取最高 3（D&D 标准掷属性方式）。"""
    return sum(sorted(random.randint(1, 6) for _ in range(4))[1:])


def roll_stats(method: str = "4d6") -> dict:
    """掷属性 → {属性中文: 数值}。

    - "4d6": 六组 4d6 去最低（真正的掷骰）
    - "standard": 标准阵列 [15,14,13,12,10,8] 随机打乱（旧行为）
    """
    if method == "standard":
        vals = [15, 14, 13, 12, 10, 8]
        random.shuffle(vals)
    else:
        vals = [_roll_4d6() for _ in range(6)]
    return dict(zip(ATTRS_CN, vals))


def roll_stats_with_log(method: str = "4d6") -> tuple[dict, str]:
    """掷属性并返回一行摘要日志（预览时展示给玩家）。"""
    if method == "standard":
        vals = [15, 14, 13, 12, 10, 8]
        random.shuffle(vals)
        log = "标准阵列打乱: " + "、".join(map(str, vals))
    else:
        vals = [_roll_4d6() for _ in range(6)]
        log = "掷骰 4d6 取最高3: " + "、".join(map(str, vals))
    return dict(zip(ATTRS_CN, vals)), log


# ── 派生项（职业/背景决定） ──

def class_skills(cd) -> list[str]:
    """职业前 N 项技能（英文 key）。"""
    skills_cn = list(cd.skill_options[:cd.skill_choices]) if cd else []
    return [SKILL_BY_EN.get(s, s) for s in skills_cn]


def class_saving_throws(cd) -> list[str]:
    """职业豁免（英文 key）。"""
    return [SKILL_BY_EN.get(s, s) for s in (cd.saving_throws if cd else [])]


def build_character(name: str, stats: dict, species_cn: str = "", class_cn: str = "",
                    bg_cn: str = "") -> Character:
    """用已选定的种族/职业/背景 + 属性组装角色（不含起始装备，由 main 统一初始化）。"""
    species_cn = species_cn or random.choice(RACES)
    sp = find_species(species_cn)
    race_en = sp.name_en if sp else species_cn
    lineage = ""
    if sp and sp.lineages:
        lin = random.choice(sp.lineages)
        lineage = lin.name_en or lin.name

    class_cn = class_cn or random.choice(CLASSES)
    cd = find_class(class_cn)
    class_en = cd.name_en if cd else class_cn

    bg_cn = bg_cn or random.choice(BACKGROUNDS)
    bg = find_background(bg_cn)
    bg_en = bg.name_en if bg else bg_cn
    feat = bg.feat if bg else ""

    hd = HIT_DICE.get(class_cn, 10)
    con_mod = (stats["体质"] - 10) // 2
    hp = hd + con_mod

    char = Character(
        name=name or random_name(),
        race=race_en, lineage=lineage, char_class=class_en,
        background=bg_en, description=f"一位{species_cn}{class_cn}，背景是{bg_cn}。",
        level=1, hp=hp, max_hp=hp,
        strength=stats["力量"], dexterity=stats["敏捷"],
        constitution=stats["体质"], intelligence=stats["智力"],
        wisdom=stats["感知"], charisma=stats["魅力"],
        skills=class_skills(cd), saving_throws=class_saving_throws(cd),
        feats=[feat] if feat else [],
        gender=random.choice(["male", "female"]),
        age=random.randint(18, 45),
    )
    return char


def roll_character(name: str | None = None, stats_method: str = "4d6") -> tuple[Character, str]:
    """全随机角色。返回 (Character, 掷骰摘要)。"""
    species_cn, _, _ = roll_species()
    class_cn, _ = roll_class()
    bg_cn, _, _ = roll_background()
    stats, log = roll_stats_with_log(stats_method)
    return build_character(name or random_name(), stats, species_cn, class_cn, bg_cn), log
