from __future__ import annotations
import re
from typing import Optional
from resource.manager import ResourceManager

_ITEM_BLOCK_RE = re.compile(r"\n?\[物品变更\].*?(?=\n\[|\Z)", re.DOTALL)
_STATUS_CHANGE_BLOCK_RE = re.compile(r"\n?\[状态变更\].*?(?=\n\[|\Z)", re.DOTALL)


class Regulator:
    """数据变更的唯一写入入口（监督者方向B 的落账柜台）。

    只做：解析 → 校验 → 执行 → 回执。
    不发起 LLM 对话、不做重试、不做渲染——这些由监督者负责。

    硬约束：除 history.json 外，LLM 对游戏数据的任何修改都必须经由此类。
    [状态] 等文本区块已彻底废除：LLM 只输出叙事文本，所有数据变更一律经
    工具调用（toolbox → 本类），文本区块不再具备任何落账能力。
    """

    def __init__(self, character, world_state, manager: Optional[ResourceManager] = None):
        self.character = character
        self.world = world_state
        if manager is None:
            manager = ResourceManager(character.inventory, character)
        manager.world = world_state
        self.manager = manager
