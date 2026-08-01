from __future__ import annotations
from typing import Optional
from world.entity import Entity, NPC


class WorldState:
    WEIGHT_ACTIVE = 100
    WEIGHT_NEARBY_INIT = 60
    WEIGHT_DISTANT_INIT = 30

    DECAY_ACTIVE = 0
    DECAY_NEARBY = 5
    DECAY_DISTANT = 15

    GC_THRESHOLD = 0

    def __init__(self):
        self.active: dict[str, Entity] = {}
        self.nearby: dict[str, Entity] = {}
        self.distant: dict[str, Entity] = {}
        self.location: str = ""
        self.time: str = ""

    # ── entity management ──

    def add_active(self, entity: Entity) -> None:
        entity.memory_weight = self.WEIGHT_ACTIVE
        self._remove_anywhere(entity.id)
        self.active[entity.id] = entity

    def add_nearby(self, entity: Entity) -> None:
        entity.memory_weight = self.WEIGHT_NEARBY_INIT
        self._remove_anywhere(entity.id)
        self.nearby[entity.id] = entity

    def add_distant(self, entity: Entity) -> None:
        entity.memory_weight = self.WEIGHT_DISTANT_INIT
        self._remove_anywhere(entity.id)
        self.distant[entity.id] = entity

    def get(self, entity_id: str) -> Optional[Entity]:
        for pool in (self.active, self.nearby, self.distant):
            if entity_id in pool:
                return pool[entity_id]
        return None

    def get_by_name(self, name: str) -> Optional[Entity]:
        for pool in (self.active, self.nearby, self.distant):
            for e in pool.values():
                if e.name == name:
                    return e
        return None

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

    def _remove_anywhere(self, entity_id: str) -> None:
        self.active.pop(entity_id, None)
        self.nearby.pop(entity_id, None)
        self.distant.pop(entity_id, None)

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
                pruned.append(eid)
        return pruned

    # ── status rendering for LLM prompt ──

    def _status_mark(self, e: Entity) -> str:
        """NPC 倒地/死亡标记（LLM 上下文用）。"""
        if getattr(e, "dead", False):
            return "（已死亡）"
        if getattr(e, "hp", 0) <= 0:
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

    def to_dict(self) -> dict:
        return {
            "active": [e.to_dict() for e in self.active.values()],
            "nearby": [e.to_dict() for e in self.nearby.values()],
            "distant": [e.to_dict() for e in self.distant.values()],
            "location": self.location,
            "time": self.time,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WorldState:
        from world.entity import NPC
        ws = cls()
        ws.location = d.get("location", "")
        ws.time = d.get("time", "")
        for ed in d.get("active", []):
            e = NPC.from_dict(ed) if "char_class" in ed else Entity.from_dict(ed)
            ws.active[e.id] = e
        for ed in d.get("nearby", []):
            e = NPC.from_dict(ed) if "char_class" in ed else Entity.from_dict(ed)
            ws.nearby[e.id] = e
        for ed in d.get("distant", []):
            e = NPC.from_dict(ed) if "char_class" in ed else Entity.from_dict(ed)
            ws.distant[e.id] = e
        return ws

    def _tag(self, e: Entity) -> str:
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
