"""回合块类体系。所有终端输出的块都是 RoundBlock 的子类，统一 render 接口。

数据隔离原则：
- [环境] → Scene.environment 摘抄 地点/温度（时间短摘抄自 World.time）
- [事件]/[副事件] → DM 文本（唯一的自由区）
- [行动] → checker 本地掷骰结果
- [变更] → 结构化变更记录（Actor 属性 变更 (旧值 >>> 新值)），由 ChangeBlock/MoneyChangeBlock 渲染
- [状态] → world.active + character（本地渲染，LLM 不再输出此区块）
- [选择] → manager.choices（create_choice 工具）
- [决定] → 玩家输入
"""

from __future__ import annotations

import re

from rich.panel import Panel
from rich.markdown import Markdown
from rich import box

from core.ui import console
from resource.models import format_cp_change

# ── 基类 ──


class RoundBlock:
    title: str = ""
    border_color: str = "grey58"

    def __init__(self, content: str = ""):
        self.content = content

    def render(self):
        if self.content.strip():
            console.print(Panel(
                self.content.strip(),
                title=f"[{self.border_color}]{self.title}[/{self.border_color}]",
                border_style=self.border_color,
                box=box.SQUARE,
            ))


# ── 环境块 — 从 Scene.environment + World.time 摘抄 地点/时间/温度 ──

class EnvironmentBlock(RoundBlock):
    title = "环境"
    border_color = "steel_blue"

    @classmethod
    def from_scene(cls, scene, world=None) -> EnvironmentBlock:
        env = getattr(scene, "environment", None) or {}
        fields = []
        loc = env.get("地点", "") or getattr(scene, "location", "") or ""
        if loc:
            fields.append(f"地点：{loc}")
        period = ""
        if world is not None:
            period = getattr(world, "time_short", lambda: "")()
        if not period:
            period = env.get("时间", "")
        if period:
            fields.append(f"时间：{period}")
        temp = env.get("温度", "")
        if temp:
            fields.append(f"温度：{temp}")
        return cls(content="    ".join(fields))


# ── 事件块 — DM 输出的 [事件] 文本 ──

class EventBlock(RoundBlock):
    title = "事件"
    border_color = "#cc6b3e"

    def render(self):
        if self.content.strip():
            console.print(Panel(
                Markdown(self.content.strip()),
                title=f"[{self.border_color}]{self.title}[/{self.border_color}]",
                border_style=self.border_color,
                box=box.SQUARE,
            ))

    @classmethod
    def from_text(cls, text: str) -> EventBlock:
        return cls(content=text)


class SubEventBlock(RoundBlock):
    title = "事件"
    border_color = "#d4946b"

    @classmethod
    def from_text(cls, text: str) -> SubEventBlock:
        return cls(content=text)


# ── 行动块 — 检定/攻击结果 ──

class ActionBlock(RoundBlock):
    title = "行动"
    border_color = "#E06C75"

    @classmethod
    def from_check(cls, check_text: str) -> ActionBlock:
        return cls(content=check_text)


class ChangeBlock(RoundBlock):
    """变更块基类：只渲染结构化变更记录「Actor 属性 变更 (旧值 >>> 新值)」。

    监督者诊断（状态格式需修正 / 系统提醒）等随意文本不属于变更，
    不会出现在这里——非结构化行一律过滤丢弃。
    """
    title = "变更"
    border_color = "#d4a0a0"

    # 结构化变更行：必须含 (旧值 >>> 新值) 形态；允许后跟状态注解
    # （如 HP 归零时的「，倒地昏迷」），仅以此形态判定是否属于变更记录
    _STRUCTURED_RE = re.compile(r"\([^()]*?>>>[^()]*\)")

    @classmethod
    def from_messages(cls, messages: list[str]):
        if not messages:
            return None
        lines = []
        for m in messages:
            s = cls._line_text(m)
            if not s or not cls._STRUCTURED_RE.search(s):
                continue
            lines.append(s)
        return cls(content="\n".join(lines)) if lines else None

    @staticmethod
    def _line_text(m) -> str:
        if isinstance(m, str):
            return m.strip()
        get = getattr(m, "line", None)
        return (get() if callable(get) else str(m)).strip()


class MoneyChangeBlock(ChangeBlock):
    """金钱变更块：金钱变更的专用子类（金银铜换算 + 金色标注）。

    金钱是唯一需要单位换算的变更类型（1金=10000铜、1银=100铜），
    因此单独成子类，由 from_cp 统一换算后打印；未来其他特殊变更
    类型可仿照此类各自成子类。
    """
    title = "变更"
    border_color = "#e3c26b"

    @classmethod
    def is_money_line(cls, s: str) -> bool:
        return bool(re.match(r"^\S+\s+金钱\s+[+-]", cls._line_text(s)))

    @classmethod
    def from_cp(cls, actor: str, delta_cp: int, before_cp: int, after_cp: int):
        return cls(content=format_cp_change(actor, delta_cp, before_cp, after_cp))

    @classmethod
    def format_line(cls, s: str) -> str:
        return f"[#e3c26b]{cls._line_text(s)}[/#e3c26b]"


class StatusBlock(RoundBlock):
    """目标块：玩家+NP Columns 横排渲染，可一行多个/多行。"""
    title = "状态"
    border_color = "grey58"

    @classmethod
    def from_world(cls, character, world_state, targets=None):
        """委托 render_status_row 的 Columns 渲染，同时返回实例供 block 列表追踪。"""
        from core.ui import render_status_row as _rsr
        _rsr(character, world_state, targets=targets)
        return cls(content="")  # content 为空，render 不做额外输出


class ChoiceBlock(RoundBlock):
    title = "选择"
    border_color = "dark_sea_green"

    @classmethod
    def from_choices(cls, choices: list[dict]):
        if not choices:
            return None
        lines = []
        ab_cn_map = {"strength":"力量","dexterity":"敏捷","constitution":"体质",
                     "intelligence":"智力","wisdom":"感知","charisma":"魅力"}
        for c in choices:
            idx, label, ct = c["index"], c["label"], c.get("choice_type","narrative")
            tag = ""
            if ct == "attack":
                ab = ab_cn_map.get(c.get("ability",""),"")
                tgt = c.get("target","")
                tag = (ab or "") + "攻击" + (f" 对{tgt}" if tgt else "")
            elif ct == "ability_check":
                ab = ab_cn_map.get(c.get("ability",""),"")
                dc = c.get("dc", 0)
                tag = f"{ab}检定" + (f" DC {dc}" if dc else "")
            tag_str = f" [#5DCCCC]（{tag}）[/#5DCCCC]" if tag else ""
            lines.append(f"[white]{idx}.[/white] [#F9F1A5]{label}{tag_str}[/#F9F1A5]")
        return cls(content="\n".join(lines))


class DecisionBlock(RoundBlock):
    title = "决定"
    border_color = "#9b87c4"

    @classmethod
    def from_text(cls, text: str):
        return cls(content=text)


class DeathSaveBlock(RoundBlock):
    title = "死亡豁免"
    border_color = "indian_red"

    @classmethod
    def from_text(cls, text: str):
        return cls(content=text)
