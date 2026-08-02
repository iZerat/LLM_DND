"""回合块类体系。所有终端输出的块都是 RoundBlock 的子类，统一 render 接口。

数据隔离原则：
- [环境] → Scene.environment
- [事件]/[副事件] → DM 文本（唯一的自由区）
- [行动] → checker 本地掷骰结果
- [变更] → manager.pending_changes + audit.messages
- [状态] → world.active + character
- [选择] → manager.choices（create_choice 工具）
- [决定] → 玩家输入
"""

from __future__ import annotations

from rich.panel import Panel
from rich import box

from core.ui import console

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


# ── 环境块 — 从 Scene.environment 渲染 ──

class EnvironmentBlock(RoundBlock):
    title = "环境"
    border_color = "steel_blue"

    @classmethod
    def from_scene(cls, scene) -> EnvironmentBlock:
        env = getattr(scene, "environment", None) or {}
        fields = []
        place = env.get("地点", "") or getattr(scene, "location", "")
        time_val = env.get("时间", "")
        temp = env.get("温度", "")
        if place:
            fields.append(f"地点：{place}")
        if time_val:
            fields.append(f"时间：{time_val}")
        if temp:
            fields.append(f"温度：{temp}")
        for k, v in env.items():
            if k not in ("地点", "时间", "温度") and v:
                fields.append(f"{k}：{v}")
        return cls(content="    ".join(fields))


# ── 事件块 — DM 输出的 [事件] 文本 ──

class EventBlock(RoundBlock):
    title = "事件"
    border_color = "#cc6b3e"

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
    title = "变更"
    border_color = "#d4a0a0"

    @classmethod
    def from_messages(cls, messages: list[str]):
        if not messages:
            return None
        return cls(content="\n".join(messages))


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
                tag = (ab or "") + "攻击" + (f"对{tgt}" if tgt else "")
            elif ct == "ability_check":
                ab = ab_cn_map.get(c.get("ability",""),"")
                dc = c.get("dc", 0)
                tag = f"{ab}检定" + (f" DC {dc}" if dc else "")
            if tag:
                label += f"（{tag}）"
            lines.append(f"{idx}. {label}")
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
