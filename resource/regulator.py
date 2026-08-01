from __future__ import annotations
import re
from typing import Optional
from resource.manager import ResourceManager
from world.entity import NPC

_ITEM_BLOCK_RE = re.compile(r"\n?\[物品变更\].*?(?=\n\[|\Z)", re.DOTALL)
_STATUS_CHANGE_BLOCK_RE = re.compile(r"\n?\[状态变更\].*?(?=\n\[|\Z)", re.DOTALL)
_STATUS_SYNC_RE = re.compile(
    r"\[状态\]\s*(.*?)(?=\n\[(?:环境|场景|场景细节|事件|副事件|状态|选择|历史|时间)|\Z)",
    re.DOTALL,
)
_NPC_LINE_RE = re.compile(
    r"(?:目标|其他)\s*:\s*(?:\[(.+?)\])?\s*(.+?),\s*AC:\s*(\d+),\s*HP:\s*(\d+)/(\d+)"
)
# 名称内禁止出现括号：叙事性描述（如「(已逃窜)」）不得混入目标名称
_STATUS_NAME_BAD_RE = re.compile(r"[（）()]")


class ChangeReport:
    """一次变更提交的回执：剥离后的文本 + 用户可见变更消息 + 待处理问题。"""

    def __init__(self, text: str = "", applied: bool = False,
                 messages: list[str] | None = None,
                 issues: list[str] | None = None,
                 changed_npcs: set[str] | None = None):
        self.text = text
        self.applied = applied
        self.messages = messages or []
        self.issues = issues or []
        self.changed_npcs = changed_npcs or set()


class Regulator:
    """数据变更的唯一写入入口（监督者方向B 的落账柜台）。

    只做：解析 → 校验 → 执行 → 回执。
    不发起 LLM 对话、不做重试、不做渲染——这些由监督者负责。

    硬约束：除 history.json 外，LLM 对游戏数据的任何修改都必须经由此类。
    """

    def __init__(self, character, world_state, manager: Optional[ResourceManager] = None):
        self.character = character
        self.world = world_state
        if manager is None:
            manager = ResourceManager(character.inventory, character)
        manager.world = world_state
        self.manager = manager

    # ── [状态] 区块 → 校验 / 同步 WorldState ──

    def reconcile_status_block(self, text: str) -> str:
        """用 WorldState 覆盖 [状态] 块中的玩家/目标 HP 与 AC，保证显示数值与落账一致。

        大模型可以自由叙述故事，但 [状态] 里展示的数值必须以调节器落账为准，
        不允许出现“工具扣了血、目标块还是满血”的赤裸裸冲突。
        """
        if not self.world:
            return text
        matches = list(_STATUS_SYNC_RE.finditer(text))
        if not matches:
            return text
        status_text = matches[-1].group(1)
        new_status = status_text

        ch = self.character
        if ch:
            player_m = re.search(r"玩家\s*:.*", new_status)
            if player_m:
                player_line = player_m.group(0)
                fixed = re.sub(
                    r",?\s*AC:\s*\d+\s*,\s*HP:\s*\d+/\d+",
                    f", AC:{ch.ac}, HP:{ch.hp}/{ch.max_hp}",
                    player_line, count=1,
                )
                new_status = new_status.replace(player_line, fixed)

        def fix_npc_line(line: str) -> str:
            m = _NPC_LINE_RE.match(line)
            if not m:
                return line
            name = m.group(2).strip()
            npc = self.world.get_by_name(name)
            if npc is None:
                npc = self._fuzzy_match_npc(name, set())
            if not npc:
                return line
            prefix = line[:m.start(2)]
            # 名称回显世界实体的规范名（npc.name），拒绝 LLM 的别名/省略称呼覆盖世界事实
            return f"{prefix}{npc.name}, AC:{npc.ac}, HP:{npc.hp}/{npc.max_hp}"

        new_status = "\n".join(fix_npc_line(l) if _NPC_LINE_RE.match(l.strip()) else l
                               for l in new_status.split("\n"))

        start, end = matches[-1].span()
        return text[:start] + "[状态]" + new_status + text[end:]

    def validate_status_block(self, text: str) -> list[str]:
        """校验 [状态] 区块目标名称规范：禁止括号/叙事性描述混入名称。

        返回问题列表；空列表表示通过。由监督者在同步前调用，
        不合格时打回让大模型重写 [状态] 区块。
        """
        issues: list[str] = []
        matches = list(_STATUS_SYNC_RE.finditer(text))
        if not matches:
            return issues
        for line in matches[-1].group(1).split("\n"):
            line = line.strip()
            if re.match(r"玩家\s*:", line) and re.search(r"目标\s*:", line):
                issues.append("玩家行混入了「目标:」，目标信息应单独成行")
                continue
            npc_m = _NPC_LINE_RE.match(line)
            if not npc_m:
                continue
            name = npc_m.group(2).strip()
            if _STATUS_NAME_BAD_RE.search(name):
                issues.append(f"目标名称「{name}」含括号，事件描述（如“已逃窜”）应写进[事件]，名称用稳定角色名")
        return issues

    def sync_status_block(self, text: str, changed_npcs: set[str] | None = None) -> ChangeReport:
        """同步 [状态] 块：登记新出现的 NPC（按库创建）、清理垃圾实体、刷新权重。

        [状态] 是叙事快照：其 HP/AC 数值常由模型随意填写，因此不做数值落账
        （不改写已有实体，也不扣玩家血），HP 变更统一经 change_status 工具或战斗结算。
        """
        report = ChangeReport(text=text)
        if not self.world:
            return report
        matches = list(_STATUS_SYNC_RE.finditer(text))
        if not matches:
            return report
        status_text = matches[-1].group(1)
        changed_npcs = changed_npcs or set()

        # 清理因 xN 格式 / 名称内叙事描述 产生的垃圾实体
        for pool_name in ("active", "nearby", "distant"):
            pool = getattr(self.world, pool_name, {})
            garbage_ids = [
                eid for eid, e in pool.items()
                if re.search(r"\s*x\d+\s*$", e.name) or _STATUS_NAME_BAD_RE.search(e.name)
            ]
            for eid in garbage_ids:
                self.world.remove(eid)

        # 玩家 HP：不改写。 [状态] 是叙事快照，数值常为模型随意填的
        # （如把满血写成 6/6），当作伤害同步会造成幻影扣血。
        # 玩家 HP 只允许经 change_status 工具或战斗结算落账。

        # NPC 行：目标/其他: [tag]名字, AC:N, HP:N/N
        for line in status_text.split("\n"):
            line = line.strip()
            npc_m = _NPC_LINE_RE.match(line)
            if not npc_m:
                continue
            tag = npc_m.group(1) or ""
            name = npc_m.group(2).strip()
            # AC/HP 是 LLM 叙事快照，只用于格式校验，登记时一律拒绝（T4）

            # 展开 xN 为独立实例
            x_m = re.search(r"\s*x(\d+)(?:\s|$)", name)
            if x_m:
                base = name[:x_m.start()].strip()
                count = int(x_m.group(1))
                garbage = self.world.get_by_name(name)
                if garbage:
                    self.world.remove(garbage.id)
                for i in range(count):
                    ind_name = f"{base}{i + 1}"
                    existing = self.world.get_by_name(ind_name)
                    if existing:
                        self.world.touch(existing.id)
                    else:
                        new_npc = self._sync_create_npc(ind_name, base, tag)
                        self.world.add_active(new_npc)
                continue

            existing = self.world.get_by_name(name)
            if existing is None:
                existing = self._fuzzy_match_npc(name, changed_npcs)
            if existing:
                # 不改写 HP/AC/max_hp 也绝不改名：[状态] 是叙事快照，数值与名称都不得写回世界。
                # 世界实体的名字是稳定角色名，LLM 的别名/省略称呼不覆盖它（柯恩→学者柯恩 bug）。
                self.world.touch(existing.id)
            else:
                new_npc = self._sync_create_npc(name, name, tag)
                self.world.add_active(new_npc)

        # GC：衰减权重，驱逐过期实体
        pruned = self.world.tick()
        if pruned:
            report.messages.append(f"已遗忘: {', '.join(pruned)}")
        return report

    def _fuzzy_match_npc(self, name: str, changed_npcs: set[str]) -> NPC | None:
        """DM 改名/省略称呼时识别同一实体：在场存活 NPC 中唯一名称含新名的候选即视为本人。

        仅当候选唯一时才合并，避免把不同 NPC 误并。
        """
        if not name:
            return None
        candidates = [
            e for e in self.world.active.values()
            if isinstance(e, NPC)
            and getattr(e, "hp", 0) > 0
            and (name in e.name or e.name in name)
            and e.name not in changed_npcs
        ]
        return candidates[0] if len(candidates) == 1 else None

    def _sync_create_npc(self, name: str, lookup_name: str, tag: str) -> NPC:
        """按资源策略登记 [状态] 中新出现的未登记 NPC（只登记名字，数值一律拒绝）。

        pack（查表创建）: 命中 statblocks/templates 则按库生成真实属性。
        free（填表创建）: 目录为空时以库默认属性兜底。
        两种模式都绝不用 LLM 在 [状态] 里填写的 AC/HP——[状态] 是叙事快照，
        数值不得成为世界事实（D4/T4）。自定义 NPC 只能经 create_npc 工具（表单校验）。
        """
        from world.npc_templates import npc_catalog
        from resource.attitude import label_to_int
        attitude = label_to_int(tag)
        if attitude is None:
            attitude = 0
        tmpl = npc_catalog.find_by_name(lookup_name)
        if tmpl:
            npc = npc_catalog.spawn(tmpl["id"], name=name, attitude=attitude)
            if npc:
                return npc
        return NPC(
            id=f"npc_{abs(hash(name)) % 1000000:x}",
            name=name, base_ac=10, hp=8, max_hp=8,
            attitude=attitude,
        )
