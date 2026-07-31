"""mods 故事包：story/story_packs/<id>.json 的加载与角色引用解析。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from mods.story_roles import StoryRole, load_role
from mods.types import STORY_PACKS, display_name


@dataclass
class StoryPack:
    pack_id: str
    name: str
    description: str = ""
    roles: list = field(default_factory=list)     # 引用的故事角色 id
    content: str = ""                             # 注入系统提示的剧情内容
    path: Optional[Path] = None


def pack_path(pack_id: str) -> Path:
    return STORY_PACKS / f"{pack_id}.json"


def _manifest(pack_id: str) -> Optional[dict]:
    fp = pack_path(pack_id)
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_story_pack(pack_id: str) -> Optional[StoryPack]:
    data = _manifest(pack_id)
    if data is None:
        return None
    return StoryPack(
        pack_id=pack_id,
        name=display_name(pack_id, data),
        description=data.get("description", ""),
        roles=list(data.get("roles", [])),
        content=data.get("content", ""),
        path=pack_path(pack_id),
    )


def load_story_roles(story_pack: Optional[StoryPack]) -> list[StoryRole]:
    """解析故事包引用的故事角色；未引用的不返回。"""
    if not story_pack:
        return []
    roles = []
    for rid in story_pack.roles:
        r = load_role(rid)
        if r:
            roles.append(r)
    return roles


def list_story_packs() -> list[tuple[str, str]]:
    """(显示名, pack_id)。"""
    if not STORY_PACKS.exists():
        return []
    out = []
    for fp in sorted(STORY_PACKS.glob("*.json")):
        m = _manifest(fp.stem)
        name = display_name(fp.stem, m)
        out.append((name, fp.stem))
    return out
