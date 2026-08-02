from __future__ import annotations
from dataclasses import dataclass, field, asdict
from uuid import uuid4


@dataclass
class Object:
    """一切世界对象的根基类（用户拍板：Object / World / Scene 基类）。

    对应 design-tenets 主旨一「对象分级管理」：
    - source 区分对象来源（program 程序化生成 / llm 临时创建 / player 玩家），
      是「来路不明对象」审计的字段级落点；
    - persistent 标记是否持久化（LLM 临时次要对象可回收）；
    - memory_weight 供 WorldState/【发条】按权重生命周期回收。
    """

    id: str = ""
    name: str = ""
    tags: list[str] = field(default_factory=list)
    memory_weight: int = 50
    description: str = ""
    source: str = "program"
    persistent: bool = True

    def __post_init__(self):
        if not self.id:
            self.id = f"obj_{uuid4().hex[:8]}"

    @classmethod
    def create(cls, name: str = "", **kwargs) -> Object:
        """统一实例化入口：Object.create(name=..., **字段) → 自动生成 id。"""
        return cls(name=name, **kwargs)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Object:
        return cls(**d)

    def lookup_keys(self) -> list[str]:
        keys = [self.name]
        keys.extend(self.tags)
        return [k for k in keys if k]
