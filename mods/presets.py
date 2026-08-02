"""mods 预设组合：index/<preset_id>.json 的加载。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from mods.types import INDEX_PACKS, display_name, find_resource_file, find_resource_dirs


@dataclass
class Preset:
    preset_id: str
    name: str
    description: str = ""
    background: str = ""          # 世界背景 stem
    story_pack: str = ""          # 故事包 id（可空）
    opening: str = ""             # 开场模板 stem（可空=随机）
    resource_pack: str = ""       # 资源包 id
    resource_strategy: str = ""   # 资源策略 mode
    world_type: str = "free"      # free=宽松(大模型创建) / structured=严谨(完整世界/程序化)
    components: dict = field(default_factory=dict)  # 原始 components


def load_preset(preset_id: str) -> Optional[Preset]:
    fp = find_resource_file("index", f"{preset_id}.json")
    if fp is None:
        return None
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None
    comp = data.get("components") or {}
    return Preset(
        preset_id=preset_id,
        name=display_name(preset_id, data),
        description=data.get("description", ""),
        background=comp.get("background", ""),
        story_pack=comp.get("story_pack", ""),
        opening=comp.get("opening", ""),
        resource_pack=comp.get("resource_pack", ""),
        resource_strategy=comp.get("resource_strategy", ""),
        world_type=comp.get("world_type", "free"),
        components=comp,
    )


def list_presets() -> list[tuple[str, str]]:
    """(显示名, preset_id)。遍历所有 mod 根下的 index/，主目录优先、同名去重。"""
    INDEX_PACKS.mkdir(parents=True, exist_ok=True)
    out = []
    seen = set()
    for idx_dir in find_resource_dirs("index"):
        for fp in sorted(idx_dir.glob("*.json")):
            if fp.stem in seen:
                continue
            seen.add(fp.stem)
            data = None
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                pass
            name = display_name(fp.stem, data)
            out.append((name, fp.stem))
    return out
