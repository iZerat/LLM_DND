"""mods 资源层：所有可加载资源类型的统一目录映射与显示名规范。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

MODS_DIR = Path(__file__).resolve().parent
MODS_PACKS_DIR = MODS_DIR / "packs"

# ── 四大类目录 ──
WORLD_BACKGROUNDS = MODS_DIR / "world" / "backgrounds"
GENERATION_RULES = MODS_DIR / "world" / "generation_rules"
GENERATION_RESOURCES = MODS_DIR / "world" / "generation_resources"
WORLDS = MODS_DIR / "world" / "worlds"
STORY_PACKS = MODS_DIR / "story" / "story_packs"
OPENING_TEMPLATES = MODS_DIR / "story" / "openings"
RESOURCE_PACKS = MODS_DIR / "resource" / "resource_packs"
STORY_ROLES = MODS_DIR / "resource" / "story_character"
INDEX_PACKS = MODS_DIR / "index"

# 8 种资源类型（+ 索引类），与 design/世界生成.md 对齐
RESOURCE_TYPE_WORLD_BACKGROUND = "world_background"
RESOURCE_TYPE_STORY_PACK = "story_pack"
RESOURCE_TYPE_OPENING = "opening"
RESOURCE_TYPE_RESOURCE_PACK = "resource_pack"
RESOURCE_TYPE_GENERATION_RULES = "generation_rules"
RESOURCE_TYPE_GENERATION_RESOURCES = "generation_resources"
RESOURCE_TYPE_WORLD = "world"
RESOURCE_TYPE_STORY_ROLE = "story_role"
RESOURCE_TYPE_INDEX = "index"


def iter_mod_roots() -> list[Path]:
    """虚拟 mod 根列表：主目录优先，随后是 mods/packs/ 下每个外部独立 mod 包目录。"""
    roots = [MODS_DIR]
    if MODS_PACKS_DIR.is_dir():
        roots.extend(sorted(d for d in MODS_PACKS_DIR.iterdir() if d.is_dir()))
    return roots


def find_resource_dirs(*rel_parts: str) -> list[Path]:
    """在所有 mod 根中查找 rel_parts 相对路径存在的目录，主目录优先。"""
    out = []
    for root in iter_mod_roots():
        d = root.joinpath(*rel_parts)
        if d.is_dir():
            out.append(d)
    return out


def find_resource_file(*rel_parts: str) -> Optional[Path]:
    """在所有 mod 根中查找 rel_parts 相对路径存在的文件，主目录优先；无则返回 None。"""
    for root in iter_mod_roots():
        fp = root.joinpath(*rel_parts)
        if fp.is_file():
            return fp
    return None


def display_name(stem: str, data: Optional[dict] = None) -> str:
    """资源的正式显示名：优先取 json 的 display_name 字段，缺省回退到文件 stem。"""
    if data:
        name = data.get("display_name") or data.get("name")
        if name:
            return name
    return stem


def ensure_dirs():
    for d in (WORLD_BACKGROUNDS, GENERATION_RULES, GENERATION_RESOURCES, WORLDS,
              STORY_PACKS, OPENING_TEMPLATES, RESOURCE_PACKS, STORY_ROLES, INDEX_PACKS):
        d.mkdir(parents=True, exist_ok=True)
