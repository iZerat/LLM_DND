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
    OPENING_TEMPLATES,
    WORLD_BACKGROUNDS,
    WORLDS,
    display_name,
)

__all__ = [
    "Preset", "list_presets", "load_preset",
    "StoryPack", "list_story_packs", "load_story_pack", "load_story_roles",
    "StoryRole", "list_all_roles", "load_role",
]


# ── 世界背景 ──
def list_world_backgrounds() -> list[tuple[str, str]]:
    if not WORLD_BACKGROUNDS.exists():
        WORLD_BACKGROUNDS.mkdir(parents=True, exist_ok=True)
    return _list_json(WORLD_BACKGROUNDS)


def load_world_background(stem: str) -> str:
    return _load_json_content(WORLD_BACKGROUNDS, stem)


# ── 开场模板 ──
def list_opening_templates() -> list[tuple[str, str]]:
    if not OPENING_TEMPLATES.exists():
        OPENING_TEMPLATES.mkdir(parents=True, exist_ok=True)
    return _list_json(OPENING_TEMPLATES)


def load_opening_template(stem: str) -> str:
    return _load_json_content(OPENING_TEMPLATES, stem)


# ── 生成类（开发中） ──
def list_generation_rules() -> list[tuple[str, str]]:
    return _list_json(GENERATION_RULES)


def list_generation_resources() -> list[tuple[str, str]]:
    return _list_json(GENERATION_RESOURCES)


def list_worlds() -> list[tuple[str, str]]:
    return _list_json(WORLDS)


def _list_json(directory) -> list[tuple[str, str]]:
    """扫描目录下 *.json，(正式显示名 display_name, 文件 stem)。"""
    import json as _json
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
    out = []
    for fp in sorted(directory.glob("*.json")):
        try:
            data = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            data = None
        out.append((display_name(fp.stem, data), fp.stem))
    return out


def _load_json_content(directory, stem: str) -> str:
    """读取 json 的 content 字段（无则返回空串）。"""
    import json as _json
    fp = directory / f"{stem}.json"
    if not fp.exists():
        return ""
    try:
        data = _json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return ""
    return str((data or {}).get("content", "")).strip()


# ── 资源包 ──
def list_resource_packs() -> list[str]:
    """已安装资源包 id（resource_packs/ 下的子目录）。"""
    from mods.types import RESOURCE_PACKS
    if not RESOURCE_PACKS.exists():
        return []
    return sorted(
        d.name for d in RESOURCE_PACKS.iterdir()
        if d.is_dir()
    )


def load_story_role_or_none(role_id: str) -> Optional[StoryRole]:
    return load_role(role_id)
