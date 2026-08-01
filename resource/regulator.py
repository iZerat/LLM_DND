from __future__ import annotations
import re
from typing import Optional
from resource.manager import ResourceManager
from resource.packs import RESOURCE_MODE_FREE
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
        # 目标解析：target_hp/target_cp 若未显式带 target: 行，则回落到 [状态] 块的“目标:”行，
        # 避免误伤“第一个 active NPC”（如把给突击兵的伤害算到其他敌人头上）。
        target_actions = ("target_hp_add", "target_hp_remove",
                          "target_cp_add", "target_cp_remove")
        if any(r.get("action") in target_actions and not r.get("target") for r in requests):
            self._seed_target_from_status(text)
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

    def _seed_target_from_status(self, text: str) -> None:
        """把 [状态] 块的“目标:”行设为当前目标（不存在则按库先创建）。

        供 submit_status_changes 在 target_hp/target_cp 缺 target: 行时回退解析，
        确保伤害落到玩家正在交战的敌人身上。
        """
        if not self.world:
            return
        matches = list(_STATUS_SYNC_RE.finditer(text))
        if not matches:
            return
        status_text = matches[-1].group(1)
        for line in status_text.split("\n"):
            line = line.strip()
            if not re.match(r"目标\s*:", line):
                continue
            nm = _NPC_LINE_RE.match(line)
            if not nm:
                continue
            name = nm.group(2).strip()
            npc = self.world.get_by_name(name)
            if npc is None:
                npc = self._sync_create_npc(
                    name, name,
                    int(nm.group(3)), int(nm.group(4)), int(nm.group(5)),
                    nm.group(1) or "",
                )
                self.world.add_active(npc)
            self.manager._target_npc = npc
            return

    def reconcile_status_block(self, text: str) -> str:
        """用 WorldState 覆盖 [状态] 块中的玩家/目标 HP 与 AC，保证显示数值与落账一致。

        大模型可以自由叙述故事，但 [状态] 里展示的数值必须以调节器落账为准，
        不允许出现“变更块说扣了血、目标块还是满血”的赤裸裸冲突。
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
            return f"{prefix}{name}, AC:{npc.ac}, HP:{npc.hp}/{npc.max_hp}"

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
        （不改写已有实体，也不扣玩家血），HP 变更统一经 [状态变更] 或战斗结算。
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
        # 玩家 HP 只允许经 [状态变更]（hp: +/-N）或战斗结算落账。

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
                        self.world.touch(existing.id)
                    else:
                        new_npc = self._sync_create_npc(ind_name, base, ac, hp, max_hp, tag)
                        self.world.add_active(new_npc)
                continue

            existing = self.world.get_by_name(name)
            if existing is None:
                existing = self._fuzzy_match_npc(name, changed_npcs)
            if existing:
                # 不改写 HP/AC/max_hp：[状态] 是叙事快照，数值常为模型随意填的，
                # 对已有实体做差值同步会产生幻影伤害（如把 10/10 写成 6/6 即 -4）。
                # HP 变更只允许经 [状态变更]（target_hp: +/-N）或战斗结算落账。
                if existing.name != name:
                    self.world.rename(existing.id, name)
                self.world.touch(existing.id)
            else:
                new_npc = self._sync_create_npc(name, name, ac, hp, max_hp, tag)
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

    def _sync_create_npc(self, name: str, lookup_name: str, ac: int, hp: int,
                         max_hp: int, tag: str) -> NPC:
        """按资源策略创建 [状态] 同步用的 NPC。

        pack（查表创建）: 命中 statblocks/templates 则按库生成真实属性。
                          目录未命中时禁止采用 LLM 填写的数值，一律用库默认，
                          避免「LLM 直写数据」成为世界事实。
        free（填表创建）: 目录为空，允许以 LLM 填写的数值兜底。
        """
        from world.npc_templates import npc_catalog
        from resource.attitude import label_to_int
        hp = min(hp, max_hp)
        attitude = label_to_int(tag)
        if attitude is None:
            attitude = 0
        tmpl = npc_catalog.find_by_name(lookup_name)
        if tmpl:
            npc = npc_catalog.spawn(tmpl["id"], name=name, attitude=attitude)
            if npc:
                return npc
        if self.manager.resource_mode == RESOURCE_MODE_FREE:
            return NPC(
                id=f"npc_{abs(hash(name)) % 1000000:x}",
                name=name, ac=ac, hp=hp, max_hp=max_hp,
                attitude=attitude,
            )
        return NPC(
            id=f"npc_{abs(hash(name)) % 1000000:x}",
            name=name, ac=10, hp=8, max_hp=8,
            attitude=attitude,
        )
