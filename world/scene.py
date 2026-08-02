from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from world.object import Object


@dataclass
class Scene(Object):
    """场景基类：世界实例内的一格（城镇 / 地牢 / 营地 / 酒馆…）。

    用户设想：世界实例内有场景实例，场景实例内有 Actor/物品等实例。
    objects 按 id 索引，同时提供名称查询与 add/remove。
    子类可扩展（如战场 CombatScene 加先攻队列），并覆盖 from_dict 恢复子对象类型。
    """

    location: str = ""
    objects: dict[str, Object] = field(default_factory=dict)

    def __post_init__(self):
        super().__post_init__()
        if not self.location:
            self.location = self.name

    # ── 实例化 ──

    @classmethod
    def create(cls, name: str = "", **kwargs) -> Scene:
        return cls(name=name, **kwargs)

    # ── 容器操作 ──

    def add_object(self, obj: Object) -> None:
        self.objects[obj.id] = obj

    def remove_object(self, obj_id: str) -> bool:
        return self.objects.pop(obj_id, None) is not None

    def get(self, obj_id: str) -> Optional[Object]:
        return self.objects.get(obj_id)

    def get_by_name(self, name: str) -> Optional[Object]:
        for obj in self.objects.values():
            if obj.name == name:
                return obj
        return None

    def all_objects(self) -> list[Object]:
        return list(self.objects.values())

    # ── 序列化 ──

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["objects"] = {oid: o.to_dict() for oid, o in self.objects.items()}
        return d

    @classmethod
    def _restore_object(cls, od: dict) -> Object:
        """按字段形态恢复对象：Actor 侧字段走 Actor.from_data 分派 Character/NPC，
        其余回退为普通 Object。"""
        from world.actor import Actor
        is_actor = any(k in od for k in (
            "char_class", "species", "hp", "base_ac", "strength", "race", "background",
        ))
        if is_actor:
            return Actor.from_data(od)
        return Object.from_dict(od)

    @classmethod
    def from_dict(cls, d: dict) -> Scene:
        d = dict(d)
        objs = d.pop("objects", {}) or {}
        scene = cls(**d)
        for oid, od in objs.items():
            restored = cls._restore_object(od)
            restored.id = restored.id or oid
            scene.objects[restored.id] = restored
        return scene
