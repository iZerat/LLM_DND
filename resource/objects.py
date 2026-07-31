from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

TYPE_TEXT = "text"
TYPE_INT = "int"
TYPE_BOOL = "bool"
TYPE_LIST = "list"


@dataclass
class FieldSpec:
    key: str
    label: str
    type: str = TYPE_TEXT
    required: bool = True
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    default: Any = None
    options: list[str] = field(default_factory=list)
    help: str = ""


@dataclass
class ResourceSchema:
    fields: list[FieldSpec]

    def field(self, key: str) -> Optional[FieldSpec]:
        for f in self.fields:
            if f.key == key:
                return f
        return None

    def render_form(self) -> str:
        tmpl_keys = ", ".join(f"{f.key}={f.label}" for f in self.fields)
        constraints = []
        for f in self.fields:
            parts = []
            if f.type == TYPE_INT:
                if f.min_value is not None and f.max_value is not None:
                    parts.append(f"整数，范围 {f.min_value}~{f.max_value}")
                elif f.min_value is not None:
                    parts.append(f"整数，>= {f.min_value}")
                elif f.max_value is not None:
                    parts.append(f"整数，<= {f.max_value}")
                else:
                    parts.append("整数")
            elif f.type == TYPE_LIST:
                parts.append("逗号分隔列表")
            elif f.type == TYPE_BOOL:
                parts.append("是/否")
            if f.options:
                parts.append("可选值: " + "/".join(f.options))
            parts.append("必填" if f.required else "可选")
            constraints.append(f"  {f.key}: {'，'.join(parts)}")
        return tmpl_keys + "\n字段约束：\n" + "\n".join(constraints)

    def validate(self, values: dict) -> list[str]:
        errors: list[str] = []
        for f in self.fields:
            v = values.get(f.key)
            if v is None or v == "":
                if f.required:
                    errors.append(f"{f.key} 缺失（{f.label}为必填）")
                continue
            if f.type == TYPE_INT:
                if isinstance(v, bool) or not isinstance(v, int):
                    try:
                        v = int(str(v).strip())
                    except (TypeError, ValueError):
                        errors.append(f"{f.key} 应为整数")
                        continue
                if f.min_value is not None and v < f.min_value:
                    errors.append(f"{f.key} 不能小于 {f.min_value}")
                if f.max_value is not None and v > f.max_value:
                    errors.append(f"{f.key} 不能大于 {f.max_value}")
            elif f.type == TYPE_LIST:
                if isinstance(v, (int, bool)):
                    errors.append(f"{f.key} 应为列表")
            elif f.type == TYPE_BOOL:
                if not isinstance(v, str):
                    errors.append(f"{f.key} 应为是/否")
        return errors

    def clamp(self, values: dict) -> dict:
        out = dict(values)
        for f in self.fields:
            v = out.get(f.key)
            if v is None or v == "":
                continue
            if f.type == TYPE_INT:
                try:
                    v = int(str(v).strip())
                except (TypeError, ValueError):
                    continue
                if f.min_value is not None:
                    v = max(v, f.min_value)
                if f.max_value is not None:
                    v = min(v, f.max_value)
                out[f.key] = v
        return out


@dataclass
class ResourceObject:
    name: str
    name_en: str = ""
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    description: str = ""

    def lookup_keys(self) -> list[str]:
        keys = [self.name]
        if self.name_en:
            keys.append(self.name_en)
        keys.extend(self.aliases)
        return [k for k in keys if k]


ATTITUDE_CN_TO_EN = {"中立": "neutral", "友好": "friendly", "友方": "friendly", "敌对": "hostile", "敌意": "hostile"}


@dataclass
class NPCTemplate(ResourceObject):
    species: str = "human"
    char_class: str = "commoner"
    level: int = 1
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
    attitude: str = "neutral"
    items: list[str] = field(default_factory=list)

    @classmethod
    def schema(cls) -> ResourceSchema:
        return ResourceSchema(fields=[
            FieldSpec("name", "名称", required=True),
            FieldSpec("name_en", "英文名", required=False),
            FieldSpec("species", "种族", required=False, default="human"),
            FieldSpec("char_class", "职业", required=False, default="commoner"),
            FieldSpec("level", "等级", type=TYPE_INT, min_value=0, max_value=20, required=False, default=1),
            FieldSpec("hp", "生命值", type=TYPE_INT, min_value=1, required=False, default=8),
            FieldSpec("max_hp", "最大生命值", type=TYPE_INT, min_value=1, required=False, default=0),
            FieldSpec("ac", "护甲等级", type=TYPE_INT, min_value=0, required=False, default=10),
            FieldSpec("strength", "力量", type=TYPE_INT, min_value=3, max_value=30, required=False, default=10),
            FieldSpec("dexterity", "敏捷", type=TYPE_INT, min_value=3, max_value=30, required=False, default=10),
            FieldSpec("constitution", "体质", type=TYPE_INT, min_value=3, max_value=30, required=False, default=10),
            FieldSpec("intelligence", "智力", type=TYPE_INT, min_value=3, max_value=30, required=False, default=10),
            FieldSpec("wisdom", "感知", type=TYPE_INT, min_value=3, max_value=30, required=False, default=10),
            FieldSpec("charisma", "魅力", type=TYPE_INT, min_value=3, max_value=30, required=False, default=10),
            FieldSpec("proficiency_bonus", "熟练加值", type=TYPE_INT, min_value=0, max_value=10, required=False, default=2),
            FieldSpec("skills", "技能", type=TYPE_LIST, required=False),
            FieldSpec("saving_throws", "豁免", type=TYPE_LIST, required=False),
            FieldSpec("attitude", "态度", options=["中立", "友好", "敌对"], required=False, default="中立"),
            FieldSpec("items", "携带物品", type=TYPE_LIST, required=False),
            FieldSpec("tags", "标签", type=TYPE_LIST, required=False),
            FieldSpec("description", "描述", required=False),
        ])

    @classmethod
    def from_form(cls, values: dict) -> tuple[Optional[NPCTemplate], list[str]]:
        schema = cls.schema()
        errors = schema.validate(values)
        if errors:
            return None, errors
        vals = schema.clamp(values)

        def split_list(v) -> list[str]:
            if not v:
                return []
            if isinstance(v, list):
                raw = v
            else:
                raw = [x.strip() for x in re.split(r"[,/、]", str(v)) if x.strip()]
            out = []
            for x in raw:
                x = str(x).strip().strip("[]")
                if x and x not in out:
                    out.append(x)
            return out

        def to_int(v, default):
            try:
                return int(str(v).strip())
            except (TypeError, ValueError):
                return default

        hp = to_int(vals.get("hp"), 8)
        max_hp = to_int(vals.get("max_hp"), 0) or hp
        attitude_cn = vals.get("attitude") or "中立"
        attitude = ATTITUDE_CN_TO_EN.get(str(attitude_cn).strip(), str(attitude_cn).strip() or "neutral")

        tmpl = cls(
            name=str(vals.get("name", "")).strip(),
            name_en=str(vals.get("name_en", "")).strip(),
            species=str(vals.get("species") or "human").strip(),
            char_class=str(vals.get("char_class") or "commoner").strip(),
            level=to_int(vals.get("level"), 1),
            hp=hp,
            max_hp=max_hp,
            ac=to_int(vals.get("ac"), 10),
            strength=to_int(vals.get("strength"), 10),
            dexterity=to_int(vals.get("dexterity"), 10),
            constitution=to_int(vals.get("constitution"), 10),
            intelligence=to_int(vals.get("intelligence"), 10),
            wisdom=to_int(vals.get("wisdom"), 10),
            charisma=to_int(vals.get("charisma"), 10),
            proficiency_bonus=to_int(vals.get("proficiency_bonus"), 2),
            skills=split_list(vals.get("skills")),
            saving_throws=split_list(vals.get("saving_throws")),
            attitude=attitude,
            items=split_list(vals.get("items")),
            tags=split_list(vals.get("tags")),
        )
        return tmpl, []

    def to_template_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_template_dict(cls, d: dict) -> NPCTemplate:
        known = {f.name for f in cls.schema().fields}
        known.add("name_en")
        known.add("aliases")
        known.add("description")
        clean = {k: v for k, v in d.items() if k in known}
        return cls(**clean)
