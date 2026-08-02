from __future__ import annotations
from world.world import World


class WorldState(World):
    """旧世界容器兼容别名（已废弃，保留仅供存档/旧代码引用）。

    World 已接管全部职责：场景化容器 + active/nearby/distant 层池 +
    GC/渲染/序列化。WorldState() 即返回一个 World 实例；
    旧 WorldState JSON（active/nearby/distant 平铺池）经 World.from_dict 自动迁移。
    """
