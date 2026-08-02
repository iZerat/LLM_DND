from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from world.object import Object


@dataclass
class Skill(Object):
    """技能基类（参照 rules/SRD 5.2.1 + skills.json）。

    D&D 5e 技能 = 名称 + 关联属性 + 是否熟练。
    熟练与否是角色侧状态：Actor.skills 里出现的 Skill 即视为熟练；
    Skill 对象本身是定义（name/name_en/ability）。
    """

    name_en: str = ""
    ability: str = ""

    @classmethod
    def from_rules(cls, name_en: str) -> Optional[Skill]:
        """按英文 key 从 rules/srd_data 反查中文名与关联属性。

        例：from_rules("acrobatics") → Skill(特技, acrobatics, dexterity)。
        """
        from rules.srd_data import SKILLS_EN, SKILL_ABILITY, ABILITY_EN
        cn = SKILLS_EN.get(name_en)
        if not cn:
            return None
        ability_cn = SKILL_ABILITY.get(cn, "")
        return cls(
            name=cn,
            name_en=name_en,
            ability=ABILITY_EN.get(ability_cn, ""),
        )

    @classmethod
    def from_cn(cls, cn: str) -> Optional[Skill]:
        """按中文名构建（从 skills.json 反查）。"""
        from rules.srd_data import SKILL_ABILITY, ABILITY_EN
        ability_cn = SKILL_ABILITY.get(cn, "")
        return cls(name=cn, ability=ABILITY_EN.get(ability_cn, ""))


def skills_from_srd() -> list[Skill]:
    """构建标准 18 项技能（数据源 skills.json）。"""
    from rules.srd_data import SKILLS
    return [s for s in (Skill.from_cn(cn) for cn in SKILLS) if s]


def coerce_skill(value) -> Optional[Skill]:
    """把存档/模板中的技能条目规范化为 Skill 对象。

    兼容三种形态：Skill 对象 / dict（to_dict 结果）/ 字符串。
    字符串优先按英文 key（SKILLS_EN）反查，再按中文名反查，兜底构造纯名称 Skill。
    """
    if value is None:
        return None
    if isinstance(value, Skill):
        return value
    if isinstance(value, dict):
        return Skill.from_dict(value)
    s = str(value).strip()
    if not s:
        return None
    sk = Skill.from_rules(s)
    if sk is None:
        sk = Skill.from_cn(s)
    if sk is None:
        sk = Skill(name=s)
    return sk


def coerce_feat(value) -> Optional[Feat]:
    """把存档/模板中的专长条目规范化为 Feat 对象。

    兼容三种形态：Feat 对象 / dict / 字符串（专长名，如背景授予的专长）。
    """
    if value is None:
        return None
    if isinstance(value, Feat):
        return value
    if isinstance(value, dict):
        return Feat.from_dict(value)
    s = str(value).strip()
    if not s:
        return None
    return Feat(name=s)


@dataclass
class Feat(Object):
    """专长基类（参照 rules：背景 Background.feat 授予专长名）。

    prerequisites 前置条件；effects 为程序可解释的受控效果
    （如 "ability:strength" 能力提升、"skill:acrobatics" 获得熟练），
    供后续系统接线，不给 LLM 自由解释。
    """

    name_en: str = ""
    prerequisites: str = ""
    effects: list[str] = field(default_factory=list)


@dataclass
class Spell(Object):
    """法术基类（参照 SRD 5.2.1 法术字段；SRD 无法术表，数据层待建）。

    解析/结算字段：
    - level/school/casting_time/range/components/duration/concentration：5e 法术定义；
    - damage_dice/damage_type：伤害结算（经调节器，与攻击同链路）；
    - saving_throw：豁免属性 key（非空表示需豁免）；
    - attack_roll：True 表示需攻击检定；
    - effect：人类可读效果说明。
    """

    level: int = 0
    school: str = ""
    name_en: str = ""
    casting_time: str = ""
    range: str = ""
    components: list[str] = field(default_factory=list)
    duration: str = ""
    concentration: bool = False
    damage_dice: str = ""
    damage_type: str = ""
    saving_throw: str = ""
    attack_roll: bool = False
    effect: str = ""


# ── D&D 5e 标准行动类型 ──
_CHOICE_TYPES = {
    "attack": "攻击",
    "ability_check": "属性检定",
    "narrative": "叙事",
}


@dataclass
class Choice(Object):
    choice_type: str = "narrative"
    label: str = ""
    ability: str = ""
    dc: int = 0
    target: str = ""
    skill: str = ""


def coerce_choice(obj) -> Optional[Choice]:
    if obj is None:
        return None
    if isinstance(obj, Choice):
        return obj
    if isinstance(obj, dict):
        ct = str(obj.get("choice_type", "narrative")).strip().lower()
        if ct not in _CHOICE_TYPES:
            ct = "narrative"
        try:
            return Choice(
                id=obj.get("id", ""),
                name=obj.get("name", ""),
                tags=list(obj.get("tags") or []),
                description=obj.get("description", ""),
                source=obj.get("source", ""),
                persistent=bool(obj.get("persistent", True)),
                memory_weight=int(obj.get("memory_weight", 50)),
                choice_type=ct,
                label=obj.get("label", obj.get("name", "")),
                ability=obj.get("ability", ""),
                dc=int(obj.get("dc", 0)),
                target=obj.get("target", ""),
                skill=obj.get("skill", ""),
            )
        except Exception:
            return None
    return None
