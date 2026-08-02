from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from world.object import Object
from world.scene import Scene


@dataclass
class World(Object):
    """世界基类：唯一顶层容器（用户拍板）。

    所有实例归入一个世界实例；世界实例内是场景实例（Scene），
    场景实例内是 Actor/物品等实例（Object）。
    子类可扩展（如 WorldState 迁移为 World 的运行时实现）。
    """

    scenes: dict[str, Scene] = field(default_factory=dict)
    location: str = ""
    time: str = ""

    @classmethod
    def create(cls, name: str = "", **kwargs) -> World:
        return cls(name=name, **kwargs)

    # ── 场景容器操作 ──

    def add_scene(self, scene: Scene) -> None:
        self.scenes[scene.id] = scene

    def remove_scene(self, scene_id: str) -> bool:
        return self.scenes.pop(scene_id, None) is not None

    def get_scene(self, scene_id: str) -> Optional[Scene]:
        return self.scenes.get(scene_id)

    def get_scene_by_name(self, name: str) -> Optional[Scene]:
        for scene in self.scenes.values():
            if scene.name == name:
                return scene
        return None

    def all_scenes(self) -> list[Scene]:
        return list(self.scenes.values())

    # ── 全局查找 ──

    def find(self, obj_id: str) -> Optional[Object]:
        """全局按 id 查找任意实例（遍历场景）。"""
        for scene in self.scenes.values():
            found = scene.get(obj_id)
            if found is not None:
                return found
        return None

    def find_by_name(self, name: str) -> Optional[Object]:
        for scene in self.scenes.values():
            found = scene.get_by_name(name)
            if found is not None:
                return found
        return None

    # ── 序列化 ──

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["scenes"] = {sid: s.to_dict() for sid, s in self.scenes.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> World:
        d = dict(d)
        scenes = d.pop("scenes", {}) or {}
        world = cls(**d)
        for sid, sd in scenes.items():
            scene = Scene.from_dict(sd)
            scene.id = scene.id or sid
            world.scenes[scene.id] = scene
        return world
