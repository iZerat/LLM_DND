from __future__ import annotations
import re
from typing import Optional
from resource.manager import ResourceManager
from resource.item_db import item_db
from resource.llm_parser import parse_item_changes, parse_status_changes
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
_ATTITUDE_MAP = {"敌对": "hostile", "中立": "neutral", "友方": "friendly"}


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

    # ── [物品变更]：物品 / 金钱 ──

    def submit_item_changes(self, text: str) -> ChangeReport:
        """解析并落账 [物品变更] 区块，返回剥离该区块后的文本。

        两阶段执行：
          1) 先整体原子校验并执行 item_add 填表创建；
          2) 再用新建物品的名称解析区块内对它们的 +name 引用。
        若出现库外物品或 item_add 校验失败（issues 非空），不改动任何数据，
        由监督者决定：发起重写对话，或忽略该区块。
        """
        requests = parse_item_changes(text)
        if requests is None:
            return ChangeReport(text=text)

        item_adds = [r for r in requests if r.get("action") == "item_add"]
        others = [r for r in requests if r.get("action") != "item_add"]

        # 1) 原子校验 item_add
        item_issues: list[str] = []
        for req in item_adds:
            issue = self.manager.item_add_issue(req)
            if issue:
                item_issues.append(issue)
        if item_issues:
            return ChangeReport(
                text=_ITEM_BLOCK_RE.sub("", text, count=1).strip(),
                applied=False,
                issues=item_issues,
            )

        # 2) 执行 item_add，收集新建名称
        results = [self.manager.item_add(req["fields"]) for req in item_adds]
        created_names = set()
        for req, res in zip(item_adds, results):
            if res.success:
                created_names.add(str((req.get("fields") or {}).get("name", "")).strip())

        # 3) 解析剩余请求；区块内新建物品的名称引用可解析
        remaining: list[dict] = []
        for req in others:
            if req.get("action") == "unknown" and req.get("name") in created_names:
                d = item_db.find_best(req["name"])
                if d:
                    remaining.append({
                        "action": "add",
                        "guid": d.guid,
                        "quantity": req.get("quantity", 1),
                    })
                else:
                    remaining.append(req)
            else:
                remaining.append(req)

        unknown = [r["name"] for r in remaining if r["action"] == "unknown"]
        if unknown:
            return ChangeReport(
                text=_ITEM_BLOCK_RE.sub("", text, count=1).strip(),
                applied=False,
                issues=unknown,
            )
        results += self.manager.process_requests(remaining)
        return ChangeReport(
            text=_ITEM_BLOCK_RE.sub("", text, count=1).strip(),
            applied=True,
            messages=[r.message for r in results if r.visible],
        )

    # ── [状态变更]：HP / 目标 / NPC ──

    def submit_status_changes(self, text: str) -> ChangeReport:
        """解析并落账 [状态变更] 区块，返回剥离该区块后的文本。

        npc_add 请求先整体校验（原子拒绝）：任一条失败则整个区块不落账，
        由监督者发起重写对话或圆场。
        changed_npcs 记录本轮被 [状态变更] 主动改过的 NPC，
        供 sync_status_block 跳过这些 NPC 的重复叠加。
        """
        requests = parse_status_changes(text)
        if requests is None:
            return ChangeReport(text=text)
        npc_issues: list[str] = []
        for req in requests:
            if req.get("action") == "npc_add":
                issue = self.manager.npc_add_issue(req)
                if issue:
                    npc_issues.append(issue)
        if npc_issues:
            return ChangeReport(
                text=_STATUS_CHANGE_BLOCK_RE.sub("", text, count=1).strip(),
                applied=False,
                issues=npc_issues,
            )
        results = self.manager.process_requests(requests)
        changed: set[str] = set()
        for req in requests:
            if req.get("action") == "npc_add":
                f = req.get("fields") or {}
                if f.get("name"):
                    changed.add(str(f["name"]).strip())
        for r in results:
            if r.visible and r.success:
                m = re.match(r"目标 (.+?)(?: HP| [+-])", r.message)
                if m:
                    changed.add(m.group(1))
        return ChangeReport(
            text=_STATUS_CHANGE_BLOCK_RE.sub("", text, count=1).strip(),
            applied=True,
            messages=[r.message for r in results if r.visible and r.success],
            changed_npcs=changed,
        )

    # ── [状态] 区块 → 校验 / 同步 WorldState ──

    def validate_status_block(self, text: str) -> list[str]:
        """校验 [状态] 区块目标名称规范：禁止括号/叙事性描述混入名称。

        返回问题列表；空列表表示通过。由监督者在同步前调用，
        不合格时打回让大模型重写 [状态] 区块。
        """
        issues: list[str] = []
        match = _STATUS_SYNC_RE.search(text)
        if not match:
            return issues
        for line in match.group(1).split("\n"):
            line = line.strip()
            npc_m = _NPC_LINE_RE.match(line)
            if not npc_m:
                continue
            name = npc_m.group(2).strip()
            if _STATUS_NAME_BAD_RE.search(name):
                issues.append(f"目标名称「{name}」含括号，事件描述（如“已逃窜”）应写进[事件]，名称用稳定角色名")
        return issues

    def sync_status_block(self, text: str, changed_npcs: set[str] | None = None) -> ChangeReport:
        """捕获 LLM 在 [状态] 中对 HP/AC/NPC 的叙事性变更并同步 WorldState。

        仅做数据同步，不修改文本（[状态] 区块仍会显示给玩家）。
        """
        report = ChangeReport(text=text)
        if not self.world:
            return report
        match = _STATUS_SYNC_RE.search(text)
        if not match:
            return report
        status_text = match.group(1)
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

        # 玩家 HP
        player_hp_m = re.search(r"HP:\s*(\d+)/(\d+)", status_text)
        if player_hp_m:
            reported_hp = int(player_hp_m.group(1))
            if reported_hp != self.character.hp:
                diff = reported_hp - self.character.hp
                self.character.hp = reported_hp
                report.messages.append(f"玩家HP {'+' if diff > 0 else ''}{diff}点")

        # NPC 行：目标/其他: [tag]名字, AC:N, HP:N/N
        for line in status_text.split("\n"):
            line = line.strip()
            npc_m = _NPC_LINE_RE.match(line)
            if not npc_m:
                continue
            tag = npc_m.group(1) or ""
            name = npc_m.group(2).strip()
            ac = int(npc_m.group(3))
            hp = int(npc_m.group(4))
            max_hp = int(npc_m.group(5))

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
                        if ind_name not in changed_npcs:
                            if existing.hp != hp:
                                diff = hp - existing.hp
                                report.messages.append(
                                    f"目标 {ind_name} HP {'+' if diff > 0 else ''}{diff}点"
                                )
                            existing.hp = hp
                            existing.max_hp = max_hp
                            existing.ac = ac
                        self.world.touch(existing.id)
                    else:
                        new_npc = self._sync_create_npc(ind_name, base, ac, hp, max_hp, tag)
                        self.world.add_active(new_npc)
                continue

            existing = self.world.get_by_name(name)
            if existing:
                if name not in changed_npcs:
                    if existing.hp != hp:
                        diff = hp - existing.hp
                        report.messages.append(
                            f"目标 {name} HP {'+' if diff > 0 else ''}{diff}点"
                        )
                    existing.hp = hp
                    existing.max_hp = max_hp
                    existing.ac = ac
                self.world.touch(existing.id)
            else:
                new_npc = self._sync_create_npc(name, name, ac, hp, max_hp, tag)
                self.world.add_active(new_npc)
                report.messages.append(f"NPC出现: {name} (HP:{new_npc.hp}/{new_npc.max_hp})")

        # GC：衰减权重，驱逐过期实体
        pruned = self.world.tick()
        if pruned:
            report.messages.append(f"已遗忘: {', '.join(pruned)}")
        return report

    def _sync_create_npc(self, name: str, lookup_name: str, ac: int, hp: int,
                         max_hp: int, tag: str) -> NPC:
        """按资源策略创建 [状态] 同步用的 NPC。

        pack（查表创建）: 命中 statblocks/templates 则按库生成真实属性。
        free（填表创建）: 目录为空，退化为默认 NPC 兜底。
        """
        from world.npc_templates import npc_catalog
        attitude = _ATTITUDE_MAP.get(tag, "neutral")
        tmpl = npc_catalog.find_by_name(lookup_name)
        if tmpl:
            npc = npc_catalog.spawn(tmpl["id"], name=name, attitude=attitude)
            if npc:
                return npc
        return NPC(
            id=f"npc_{abs(hash(name)) % 1000000:x}",
            name=name, ac=ac, hp=hp, max_hp=max_hp,
            attitude=attitude,
        )
