from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from world.object import Object
from world.scene import Scene


@dataclass
class World(Object):
    """世界基类：唯一顶层容器（用户拍板）+ WorldState 的运行时实现。

    设计：所有实例归入一个世界实例；世界实例内是场景实例（Scene），
    场景实例内是 Actor/物品等实例（Object）。「场景 = 位置粒度」——
    Actor 进入场景即进入当前层池（active/nearby/distant 保持旧语义，
    供 LLM 上下文与 GC 使用），场景给实体提供位置归属。

    WorldState 旧 API（active/nearby/distant 层池 + location/time +
    add/promote/tick/render）全部保留，runtime 层无需改动即可迁移；
    存档以 scenes 结构序列化，旧 WorldState JSON 经 from_dict 自动迁移。
    """

    scenes: dict[str, Scene] = field(default_factory=dict)
    location: str = ""
    time: str = ""
    # 创建配方：记录世界是用什么组合造出来的（世界背景 + 故事包 + 开场模板 + 资源包/填表）
    world_composition: dict = field(default_factory=dict)

    WEIGHT_ACTIVE = 100
    WEIGHT_NEARBY_INIT = 60
    WEIGHT_DISTANT_INIT = 30

    DECAY_ACTIVE = 0
    DECAY_NEARBY = 5
    DECAY_DISTANT = 15

    GC_THRESHOLD = 0

    def __post_init__(self):
        super().__post_init__()
        self.active: dict[str, Object] = {}
        self.nearby: dict[str, Object] = {}
        self.distant: dict[str, Object] = {}
        self.current_scene_id: str = ""

    # ── 场景管理 ──

    def _ensure_scene(self) -> Scene:
        if self.current_scene_id and self.current_scene_id in self.scenes:
            return self.scenes[self.current_scene_id]
        name = self.location or self.name or "主场景"
        scene = Scene.create(name=name, location=self.location)
        self.current_scene_id = scene.id
        self.scenes[scene.id] = scene
        return scene

    def _attach_to_scene(self, obj: Object) -> None:
        self._ensure_scene().add_object(obj)

    def add_scene(self, scene: Scene) -> None:
        self.scenes[scene.id] = scene
        self.current_scene_id = self.current_scene_id or scene.id

    def remove_scene(self, scene_id: str) -> bool:
        if self.current_scene_id == scene_id:
            self.current_scene_id = ""
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

    # ── 实体层池管理（WorldState 兼容）──

    def add_active(self, entity: Object) -> None:
        entity.memory_weight = self.WEIGHT_ACTIVE
        self._remove_anywhere(entity.id)
        self.active[entity.id] = entity
        self._attach_to_scene(entity)

    def add_nearby(self, entity: Object) -> None:
        entity.memory_weight = self.WEIGHT_NEARBY_INIT
        self._remove_anywhere(entity.id)
        self.nearby[entity.id] = entity
        self._attach_to_scene(entity)

    def add_distant(self, entity: Object) -> None:
        entity.memory_weight = self.WEIGHT_DISTANT_INIT
        self._remove_anywhere(entity.id)
        self.distant[entity.id] = entity
        self._attach_to_scene(entity)

    def get(self, entity_id: str) -> Optional[Object]:
        for pool in (self.active, self.nearby, self.distant):
            if entity_id in pool:
                return pool[entity_id]
        return self.find(entity_id)

    def get_by_name(self, name: str) -> Optional[Object]:
        for pool in (self.active, self.nearby, self.distant):
            for e in pool.values():
                if e.name == name:
                    return e
        return self.find_by_name(name)

    def remove(self, entity_id: str) -> None:
        self._remove_anywhere(entity_id)

    def touch(self, entity_id: str) -> None:
        """Refresh weight — call when player interacts with this entity."""
        e = self.get(entity_id)
        if e is None:
            return
        if entity_id in self.active:
            e.memory_weight = self.WEIGHT_ACTIVE
        elif entity_id in self.nearby:
            self.add_active(e)
        elif entity_id in self.distant:
            self.add_active(e)

    def promote(self, entity_id: str, target_layer: str) -> None:
        e = self.get(entity_id)
        if e is None:
            return
        self._remove_anywhere(entity_id)
        if target_layer == "active":
            self.active[entity_id] = e
            e.memory_weight = self.WEIGHT_ACTIVE
        elif target_layer == "nearby":
            self.nearby[entity_id] = e
            e.memory_weight = self.WEIGHT_NEARBY_INIT
        elif target_layer == "distant":
            self.distant[entity_id] = e
            e.memory_weight = self.WEIGHT_DISTANT_INIT
        self._attach_to_scene(e)

    def _remove_anywhere(self, entity_id: str) -> None:
        self.active.pop(entity_id, None)
        self.nearby.pop(entity_id, None)
        self.distant.pop(entity_id, None)
        for scene in self.scenes.values():
            scene.remove_object(entity_id)

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

    # ── GC: decay all weights, evict expired ──

    def tick(self) -> list[str]:
        """Decay all weights and remove expired entities. Returns pruned ids."""
        pruned: list[str] = []
        for pool, decay in [
            (self.active, self.DECAY_ACTIVE),
            (self.nearby, self.DECAY_NEARBY),
            (self.distant, self.DECAY_DISTANT),
        ]:
            dead: list[str] = []
            for eid, e in pool.items():
                e.memory_weight -= decay
                if e.memory_weight <= self.GC_THRESHOLD:
                    dead.append(eid)
            for eid in dead:
                del pool[eid]
                self._remove_from_scenes(eid)
                pruned.append(eid)
        return pruned

    def _remove_from_scenes(self, entity_id: str) -> None:
        for scene in self.scenes.values():
            scene.remove_object(entity_id)

    # ── status rendering for LLM prompt ──

    def _status_mark(self, e: Object) -> str:
        """NPC 击昏/倒地/死亡标记（LLM 上下文用）。"""
        if getattr(e, "dead", False):
            return "（已死亡）"
        if getattr(e, "knocked_out", False):
            return "（击昏昏迷）"
        if getattr(e, "unconscious", False):
            return "（倒地昏迷）"
        return ""

    def render_status_block(self, player_line: str) -> str:
        lines = [f"玩家: {player_line}"]
        if self.active:
            for e in self.active.values():
                tag = self._tag(e)
                lines.append(f"目标: [{tag}]{e.name}, AC:{e.ac}, HP:{e.hp}/{e.max_hp}{self._status_mark(e)}")
        if not self.active:
            lines.append("目标: 无")
        for e in self.nearby.values():
            tag = self._tag(e)
            lines.append(f"附近: [{tag}]{e.name}, AC:{e.ac}, HP:{e.hp}/{e.max_hp}{self._status_mark(e)}")
        for e in self.distant.values():
            tag = self._tag(e)
            lines.append(f"外围: [{tag}]{e.name}, AC:{e.ac}, HP:{e.hp}/{e.max_hp}{self._status_mark(e)}")
        return "\n".join(lines)

    def _tag(self, e: Object) -> str:
        if hasattr(e, 'attitude'):
            from resource.attitude import level_cn
            return level_cn(getattr(e, 'attitude', 0))
        return "中立"

    def render_context_for_llm(self, pc_name: str, pc_ac: int, pc_hp: int, pc_max_hp: int,
                               pc_dead: bool = False) -> str:
        """Render [当前世界状态] block for injection into LLM user message."""
        lines = ["[当前世界状态]"]
        pc_mark = "（已死亡）" if pc_dead else ("（倒地昏迷）" if pc_hp <= 0 else "")
        lines.append(f"玩家: {pc_name}, AC:{pc_ac}, HP:{pc_hp}/{pc_max_hp}{pc_mark}")
        if self.active:
            for e in self.active.values():
                tag = self._tag(e)
                lines.append(f"主目标: [{tag}]{e.name}, AC:{e.ac}, HP:{e.hp}/{e.max_hp}{self._status_mark(e)}")
        else:
            lines.append("主目标: 无")
        for e in self.nearby.values():
            tag = self._tag(e)
            lines.append(f"附近: [{tag}]{e.name}, AC:{e.ac}, HP:{e.hp}/{e.max_hp}{self._status_mark(e)}")
        for e in self.distant.values():
            tag = self._tag(e)
            lines.append(f"外围: [{tag}]{e.name}, AC:{e.ac}, HP:{e.hp}/{e.max_hp}{self._status_mark(e)}")
        return "\n".join(lines)

    # ── 序列化（新格式 scenes 结构 + layers 层池映射；旧 WorldState JSON 自动迁移）──

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["scenes"] = {sid: s.to_dict() for sid, s in self.scenes.items()}
        d["layers"] = {
            "active": list(self.active.keys()),
            "nearby": list(self.nearby.keys()),
            "distant": list(self.distant.keys()),
        }
        if self.world_composition:
            d["composition"] = dict(self.world_composition)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> World:
        d = dict(d)
        if not any(k in d for k in ("scenes", "active", "nearby", "distant")):
            return cls(**d)
        legacy = not d.get("scenes")
        scenes = d.pop("scenes", {}) or {}
        layers = d.pop("layers", None) or {}
        composition = d.pop("composition", None) or {}
        d.pop("world_composition", None)  # 避免与显式传参冲突
        active = d.pop("active", []) or []
        nearby = d.pop("nearby", []) or []
        distant = d.pop("distant", []) or []
        world = cls(world_composition=composition, **d)
        for sid, sd in scenes.items():
            scene = Scene.from_dict(sd)
            scene.id = scene.id or sid
            world.scenes[scene.id] = scene
        world.current_scene_id = next(iter(world.scenes), "")
        if legacy:
            # 旧 WorldState 存档迁移：平铺层池 → 全部归入当前场景
            for ed in active:
                world.add_active(Scene._restore_object(ed))
            for ed in nearby:
                world.add_nearby(Scene._restore_object(ed))
            for ed in distant:
                world.add_distant(Scene._restore_object(ed))
        else:
            # 新格式：按 layers 映射把场景内对象放回层池；未在映射中的对象留在场景
            pool_map = {"active": world.active, "nearby": world.nearby, "distant": world.distant}
            for layer_name, eids in layers.items():
                pool = pool_map.get(layer_name)
                if pool is None:
                    continue
                for eid in eids:
                    obj = world.find(eid)
                    if obj is not None:
                        pool[eid] = obj
        return world


@dataclass
class FreeWorld(World):
    """宽松世界：由大模型生成，世界背景和叙事由 LLM 主导发挥，世界实例较少结构化约束。"""


@dataclass
class StructuredWorld(World):
    """严谨世界：由预设组合、故事包或程序化生成，数据完整、规则约束强。"""


def world_from_dict(d: dict):
    """World 反序列化工厂：根据 composition.type 分派到对应子类。"""
    comp = d.get("composition") or {}
    if comp.get("type") == "free":
        return FreeWorld.from_dict(d)
    if comp.get("type") == "structured":
        return StructuredWorld.from_dict(d)
    return World.from_dict(d)
