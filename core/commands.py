"""命令系统：OOP 统一管理所有命令的识别输入与分发。

核心设计：
- 一个命令（Command）= 一个对象，携带多个识别输入（aliases）。
- 前缀：`/`（英文斜杠）或 `、`（中文输入法的斜杠键）都视为命令前缀。
- 解析：剥前缀 → 匹配别名（英文全名 / 缩写 / 中文词）→ 返回 (Command, args)。
- 未匹配别名 → 无效命令；非命令前缀开头的输入（自由行动）一律不拦截。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

PREFIXES = ("/", "、")

SCOPE_MENU = "menu"
SCOPE_GAME = "game"


@dataclass
class Command:
    key: str                 # 规范命令名，如 "back"
    category: str            # 帮助分组
    summary: str             # 一句话说明
    aliases: tuple = field(default_factory=tuple)   # 识别输入（不含前缀）
    scopes: tuple = field(default_factory=tuple)    # 生效阶段 (menu/game)
    handler: Optional[Callable] = None              # 处理回调，由调用方注入

    def matches(self, name: str) -> bool:
        return name.lower() in self.aliases


class CommandRegistry:
    def __init__(self):
        self._commands: dict[str, Command] = {}
        self._alias_index: dict[str, Command] = {}

    def register(self, cmd: Command) -> None:
        self._commands[cmd.key] = cmd
        for alias in cmd.aliases:
            self._alias_index.setdefault(alias.lower(), cmd)

    def resolve(self, raw: str, scope: str) -> Optional[tuple[Command, str]]:
        """解析输入 → (Command, args)。非命令输入 / 无匹配 → None。"""
        parsed = parse_command(raw)
        if parsed is None:
            return None
        name, args = parsed
        if not name:
            cmd = self._alias_index.get("help")
        else:
            cmd = self._alias_index.get(name.lower())
        if cmd is None or scope not in cmd.scopes:
            return None
        return cmd, args

    def commands_for(self, scope: str) -> list[Command]:
        return [c for c in self._commands.values() if scope in c.scopes]

    def get(self, key: str) -> Optional[Command]:
        return self._commands.get(key)


def parse_command(raw: str) -> Optional[tuple[str, str]]:
    """剥离命令前缀，返回 (命令名, 参数)。非命令输入 → None。

    - 单独 `/` 或 `、` → ("", "")
    - `/save 名字` → ("save", "名字")
    - `、返回村庄` → ("返回村庄", "")  ← 别名匹配失败时为无效命令
    """
    s = raw.strip()
    if not s or s[0] not in PREFIXES:
        return None
    body = s[1:].strip()
    if not body:
        return "", ""
    parts = body.split(maxsplit=1)
    name = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    return name, args


def build_registry() -> CommandRegistry:
    """构建完整命令注册表（handler 留空，由 main/game_loop 各自注入）。"""
    reg = CommandRegistry()
    reg.register(Command(
        key="help", category="其他", summary="帮助",
        aliases=("help", "?", "帮助"),
        scopes=(SCOPE_MENU, SCOPE_GAME),
    ))
    reg.register(Command(
        key="back", category="导航", summary="返回上一级菜单",
        aliases=("back", "b", "返回"),
        scopes=(SCOPE_MENU,),
    ))
    reg.register(Command(
        key="menu", category="导航", summary="返回主菜单",
        aliases=("menu", "m", "主菜单", "菜单"),
        scopes=(SCOPE_MENU, SCOPE_GAME),
    ))
    reg.register(Command(
        key="quit", category="其他", summary="退出游戏",
        aliases=("quit", "退出"),
        scopes=(SCOPE_MENU, SCOPE_GAME),
    ))
    reg.register(Command(
        key="quickstart", category="游戏", summary="快速开始（随机角色直接进入游戏）",
        aliases=("quickstart", "q", "快速开始"),
        scopes=(SCOPE_MENU,),
    ))
    reg.register(Command(
        key="roll", category="骰子", summary="投骰",
        aliases=("roll", "投骰", "掷骰"),
        scopes=(SCOPE_GAME,),
    ))
    reg.register(Command(
        key="status", category="角色", summary="角色状态",
        aliases=("status", "状态"),
        scopes=(SCOPE_GAME,),
    ))
    reg.register(Command(
        key="info", category="角色", summary="详细角色信息",
        aliases=("info", "信息"),
        scopes=(SCOPE_GAME,),
    ))
    reg.register(Command(
        key="scene", category="环境", summary="详细环境信息",
        aliases=("scene", "env", "场景", "环境"),
        scopes=(SCOPE_GAME,),
    ))
    reg.register(Command(
        key="equip", category="角色", summary="查看装备栏",
        aliases=("equip", "装备"),
        scopes=(SCOPE_GAME,),
    ))
    reg.register(Command(
        key="bag", category="角色", summary="查看背包与金钱",
        aliases=("bag", "背包"),
        scopes=(SCOPE_GAME,),
    ))
    reg.register(Command(
        key="skill", category="角色", summary="查看技能",
        aliases=("skill", "技能"),
        scopes=(SCOPE_GAME,),
    ))
    reg.register(Command(
        key="time", category="角色", summary="查看当前时间",
        aliases=("time", "时间"),
        scopes=(SCOPE_GAME,),
    ))
    reg.register(Command(
        key="save", category="存档", summary="保存",
        aliases=("save", "保存"),
        scopes=(SCOPE_GAME,),
    ))
    reg.register(Command(
        key="load", category="存档", summary="读档",
        aliases=("load", "读档"),
        scopes=(SCOPE_GAME,),
    ))
    return reg
