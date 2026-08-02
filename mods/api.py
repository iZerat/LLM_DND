"""mods 统一资源 API：8 类资源 + 预设索引的统一入口。

各类型职责：
  world_background / opening    纯文本模板
  story_pack + story_role       剧情包（故事包 → 故事角色引用链）
  resource_pack                 物品/NPC 资源包（配合资源策略）
  index                         预设组合（一键装配）
  generation_rules/generation_resources/world 生成相关（开发中）
"""
from __future__ import annotations

from typing import Optional

from mods.presets import Preset, list_presets, load_preset
from mods.story_packs import StoryPack, list_story_packs, load_story_pack, load_story_roles
from mods.story_roles import StoryRole, list_all_roles, load_role
from mods.types import (
    GENERATION_RESOURCES,
    GENERATION_RULES,
    INDEX_PACKS,
    OPENING_TEMPLATES,
    RESOURCE_PACKS,
    WORLD_BACKGROUNDS,
    WORLDS,
    display_name,
    find_resource_dirs,
    find_resource_file,
)

__all__ = [
    "Preset", "list_presets", "load_preset",
    "StoryPack", "list_story_packs", "load_story_pack", "load_story_roles",
    "StoryRole", "list_all_roles", "load_role",
]


# ── 世界背景 ──
def list_world_backgrounds() -> list[tuple[str, str]]:
    WORLD_BACKGROUNDS.mkdir(parents=True, exist_ok=True)
    return _list_json(find_resource_dirs("world", "backgrounds"))


def load_world_background(stem: str) -> str:
    return _load_json_content(find_resource_dirs("world", "backgrounds"), stem)


# ── 开场模板 ──
def list_opening_templates() -> list[tuple[str, str]]:
    OPENING_TEMPLATES.mkdir(parents=True, exist_ok=True)
    return _list_json(find_resource_dirs("story", "openings"))


def load_opening_template(stem: str) -> str:
    return _load_json_content(find_resource_dirs("story", "openings"), stem)


# ── 生成类（开发中） ──
def list_generation_rules() -> list[tuple[str, str]]:
    return _list_json(GENERATION_RULES)


def list_generation_resources() -> list[tuple[str, str]]:
    return _list_json(GENERATION_RESOURCES)


def list_worlds() -> list[tuple[str, str]]:
    return _list_json(WORLDS)


def _list_json(directories) -> list[tuple[str, str]]:
    """扫描每个目录下 *.json，(正式显示名 display_name, 文件 stem)；主目录优先、同名去重。"""
    import json as _json
    out = []
    seen = set()
    for directory in directories:
        if not directory.exists():
            continue
        for fp in sorted(directory.glob("*.json")):
            if fp.stem in seen:
                continue
            seen.add(fp.stem)
            try:
                data = _json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                data = None
            out.append((display_name(fp.stem, data), fp.stem))
    return out


def _load_json_content(directories, stem: str) -> str:
    """按目录顺序查找并读取 json 的 content 字段（无则返回空串）。"""
    import json as _json
    for directory in directories:
        fp = directory / f"{stem}.json"
        if not fp.exists():
            continue
        try:
            data = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            return ""
        return str((data or {}).get("content", "")).strip()
    return ""


# ── 资源包 ──
def list_resource_packs() -> list[str]:
    """已安装资源包 id（各 mod 根下 resource/resource_packs/ 的子目录，主目录优先、同名去重）。"""
    RESOURCE_PACKS.mkdir(parents=True, exist_ok=True)
    out = []
    seen = set()
    for packs_root in find_resource_dirs("resource", "resource_packs"):
        for d in sorted(packs_root.iterdir()):
            if d.is_dir() and d.name not in seen:
                seen.add(d.name)
                out.append(d.name)
    return sorted(out)


def load_story_role_or_none(role_id: str) -> Optional[StoryRole]:
    return load_role(role_id)
