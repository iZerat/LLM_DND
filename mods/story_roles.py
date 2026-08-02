"""mods 故事角色模型与加载。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from mods.types import STORY_ROLES, display_name, find_resource_dirs, find_resource_file

_STAT_DEFAULTS = {"力量": 10, "敏捷": 10, "体质": 10, "智力": 10, "感知": 10, "魅力": 10}


@dataclass
class StoryRole:
    """故事角色：仅能通过故事包的 roles 引用被加载，不进入任何菜单。"""
    role_id: str
    name: str
    description: str = ""
    species: str = ""          # 种族（中文）
    lineage: str = ""          # 亚种/派系（中文）
    char_class: str = ""       # 职业（中文）
    background: str = ""       # 背景（中文）
    stats: dict = field(default_factory=dict)          # 属性
    hp: int = 10
    max_hp: int = 10
    skills: list = field(default_factory=list)          # 技能（英文 key）
    equipment: list = field(default_factory=list)       # 物品名列表
    opening: str = ""          # 该角色专属开场模板 stem；为空则用预设/手动选择的开场


def role_path(role_id: str) -> Path:
    """在所有 mod 根中查找故事角色文件；未找到则回退到主目录路径。"""
    return find_resource_file("resource", "story_character", f"{role_id}.json") or STORY_ROLES / f"{role_id}.json"


def load_role(role_id: str) -> Optional[StoryRole]:
    fp = role_path(role_id)
    if not fp.exists():
        return None
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None
    stats = dict(_STAT_DEFAULTS)
    stats.update({k: v for k, v in (data.get("stats") or {}).items()})
    hp = data.get("hp", _STAT_DEFAULTS["体质"] + 10)
    return StoryRole(
        role_id=role_id,
        name=display_name(role_id, data),
        description=data.get("description", ""),
        species=data.get("species", ""),
        lineage=data.get("lineage", ""),
        char_class=data.get("char_class", ""),
        background=data.get("background", ""),
        stats=stats,
        hp=hp, max_hp=data.get("max_hp", hp),
        skills=list(data.get("skills", [])),
        equipment=list(data.get("equipment", [])),
        opening=data.get("opening", ""),
    )


def list_all_roles() -> list[tuple[str, str]]:
    """全部故事角色 (显示名, role_id)。遍历所有 mod 根，主目录优先、同名去重。仅用于调试。"""
    STORY_ROLES.mkdir(parents=True, exist_ok=True)
    out = []
    seen = set()
    for role_dir in find_resource_dirs("resource", "story_character"):
        for fp in sorted(role_dir.glob("*.json")):
            if fp.stem in seen:
                continue
            seen.add(fp.stem)
            r = load_role(fp.stem)
            if r:
                out.append((r.name, r.role_id))
    return out
