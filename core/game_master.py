import json
import random
import re
from typing import Optional
from pathlib import Path
from openai import OpenAI
from core.config import Config
from core.character import Character

SYSTEM_PROMPT_TEMPLATE = """你是基于 D&D 5e 规则的地城主（GM），你将用中文主持一场精彩的冒险。

当前游戏的世界背景如下：
{setting_content}

## 输出格式

每一轮都必须严格按照以下格式输出（使用方括号标注区块）：

[环境] 严格按以下格式填写，每行一个字段：
地点：微风港
时间：黄昏
温度：15℃（凉爽）
风向：东北风
风速：微风
天气：晴朗
氛围：喧闹
（以上7个字段每轮都必须填写，不允许省略。温度格式：数值℃（体感描述）。时间字段用中文词，不要加括号注释。）

[时间] 严格按以下格式填写，每行一个字段：
年月日：第三年·丰收之月 15日
季节：秋季
时分：18:30
时段：傍晚
（每轮都必须填写，与[环境]中的时间保持一致）

[事件]
描述当前发生了什么。承接上一轮玩家的选择结果。描述要有画面感，但保持精炼。3-5句话。

[状态] 严格按以下格式填表——每行一个字段，不要用 |
玩家: 荷鲁斯 Lv.1 龙裔 邪术师, AC:13, HP:8/8
目标: [敌对]活化盔甲, AC:15, HP:12/12   ← 主要目标（固定一个），无目标则写：目标: 无
其他: [敌对]地精喽啰, AC:12, HP:5/5     ← 其他目标（每个目标单独一行，不要用xN合并）
标签说明：[敌对]敌人 [中立]中立NPC [友方]友方NPC  —— 必须存在
名称规范：目标/其他名称必须是稳定的角色名（如「地精喽啰」「女商人艾拉」）。禁止在名称中加括号或事件描述（如「(已逃窜)」「(倒地)」）——角色当前状态写进[事件]里，绝不写进名称。

[选择]
1. 选项一
2. 选项二
3. 选项三
(给出3个具体的行动选项，让玩家可以选。玩家也可以自己输入其他行动。)

[历史]
- 上一轮的行动记录(只记录事实，不要写判定和结果，结果会在本轮[事件]中描述)

## 字数控制
- 每轮总输出控制在200字以内
- [环境] 3-6行字段
- 环境字段只填数据，不要写句子
- [事件] 3-5句话
- [状态] 1行
- [选择] 3个选项，每个一行
- [历史] 1行
- 描述精炼，不啰嗦

## 核心规则
{core_rules}

## 目标检定与副事件块（可选）
当[事件]中的目标（NPC/敌人）需要做攻击、豁免或属性检定时：
1. 先描述目标要做什么，然后调用 target_check 工具提交检定（多个目标可一次提交多个）；
2. 系统会立即在本地掷出骰子，并把每个检定的骰面、调整值、总值、DC和成败返回给你；
3. 收到判定结果后，在[副事件]区块中用2-3句话描述目标行动的结果（命中/落空、成功/失败的效果，是否暴击/大失败）。
[副事件]只在发起过目标检定时才输出，且必须放在回答的最后；没有目标检定就不要输出[副事件]。

## 对话与行动标记
- 「NPC对话」
- **关键动作或战斗**
- *环境氛围*

## 要求
1. 语言精炼，描述生动，拒绝长篇大论
2. 每一轮都必须给出[环境]、[事件]、[状态]、[选择]四个区块，缺一不可
3. 用中文
4. 保持冒险节奏紧凑
5. [状态]必须包含'玩家:'和'目标:'两行，这是硬性要求

## 检定标记（重要）
当你为玩家提供需要掷骰的行动选项时，在选项末尾用中文括号加上检定信息，格式为：
1. 行动描述（属性 DC 数字）
例如：1. 悄悄溜进船舱（敏捷 DC 12）
2. 威吓守卫（魅力 DC 15）

需检定的选项统一使用「检定」一词，例如（力量检定）、（敏捷 DC 12），不要使用「攻击骰」「豁免骰」等其他说法。
如果某个选项无需检定（纯对话、已知道路等），不要在选项末尾加括号。
格式必须带DC关键字和数字。系统会自动检测并触发交互式投骰界面。

支持的属性：力量、敏捷、体质、智力、感知、魅力"""

CORE_RULES = """- 属性调整值 = (属性值-10)//2
- 熟练加值: 1级+2
- 检定: d20 + 属性调整值 + (熟练加值 if 熟练) vs DC
- 攻击: d20 + 力量调整值(近战) or 敏捷调整值(远程) + 熟练加值 vs AC
- 优势: 2d20取高; 劣势: 2d20取低
- DC: 5极简 10简单 15中等 20困难 25极难
- 伤害: 武器骰子 + 属性调整值
- 豁免: d20 + 属性调整值 (+熟练加值 if 有该豁免熟练)
- 大成功/大失败: 骰面天然20=大成功（自动成功/暴击），天然1=大失败（自动失败/失手）
- 种族特性、专长和技能在角色信息中列出"""



ABILITY_CN_TO_EN = {
    "力量": "strength",
    "敏捷": "dexterity",
    "体质": "constitution",
    "智力": "intelligence",
    "感知": "wisdom",
    "魅力": "charisma",
}


def parse_check_from_text(text: str) -> tuple | None:
    """Detect (属性 检定/DC 数字) in text. Returns (ability_cn, ability_en, dc) or None.
    If a check is mentioned without a DC, defaults to DC 10."""
    if re.search(r'[（(]\s*无需', text):
        return None
    # Search for any known ability name in the text, then look for DC
    m = re.search(r'DC\s*(\d+)', text)
    if m:
        dc = int(m.group(1))
        for cn, en in ABILITY_CN_TO_EN.items():
            if cn in text:
                return (cn, en, dc)
    # No DC: look for (ability_name + 检定/判定/豁免) -> default DC 10
    for cn, en in ABILITY_CN_TO_EN.items():
        if re.search(rf'[（(].*{cn}.*?(?:检定|判定|豁免)', text):
            return (cn, en, 10)
    return None


from core.opening_templates import load_opening_template
from resource.packs import RESOURCE_MODE_PACK


RULES_DIR = Path(__file__).parent / "rules"


def _load_rules() -> str:
    return CORE_RULES


class GameMaster:
    def __init__(self, character: Character, template: str = "", setting_content: str = "", setting_stem: str = "", resource_mode: str = "pack",
                 story_pack_id: str = "", story_pack_content: str = "", world_source: str = "llm", resource_pack: str = ""):
        self.character = character
        self.client: Optional[OpenAI] = None
        self.history: list = []
        self._init_client()
        self.last_choices: list = []
        self.last_choices_map: dict = {}
        self.last_scene: str = ""
        self.last_scene_detail: str = ""
        self.last_time: str = ""
        self.last_assistant: str = ""
        self.template = template
        self.setting_content = setting_content
        self.setting_stem = setting_stem
        self.resource_mode = resource_mode
        self.resource_pack = resource_pack
        self.story_pack_id = story_pack_id
        self.story_pack_content = story_pack_content
        self.world_source = world_source
        # 角色创建时的完整快照（角色模板），随存档保存，不随游戏进程变化
        from core.templates import template_data
        self.character_template: dict = template_data(character)
        self.compressed_history: list = []
        self._round_num: int = 0
        self._truncated: bool = False
        self.last_usage: dict | None = None

    def _init_client(self):
        if Config.is_ready():
            self.client = OpenAI(
                base_url=Config.API_BASE_URL,
                api_key=Config.API_KEY,
            )

    def _resource_strategy_note(self) -> str:
        """按资源策略生成创建提示：pack 查表 / free 填表（schema 驱动表单）。"""
        tool_note = (
            "\n\n## 数据变更方式\n"
            "对游戏数据的所有变更（物品、金钱、HP、NPC）一律通过调用工具完成，"
            "不要在叙事中手写 [物品变更]/[状态变更] 区块。"
            "[状态] 区块仍须输出用于状态展示。"
            "若工具调用不可用（后端不支持），再回退为在叙事末尾附加 [物品变更]/[状态变更] 文本区块。"
        )
        if self.resource_mode == RESOURCE_MODE_PACK:
            return (
                tool_note
                + "\n\n## 资源策略：查表创建\n"
                "本世界使用资源包：NPC 与物品均从资源库查询生成，不要凭空捏造。"
                "npc_add 请用紧凑格式：npc_add: 名称, AC:10, HP:8/8, [态度]。"
                "物品请使用资源库中存在的名称。若你提到的 NPC/物品不在资源库，"
                "系统会提示你改用库中存在的条目或调整叙事。"
            )
        from resource.objects import NPCTemplate
        from resource.models import ItemDef
        npc_form = NPCTemplate.schema().render_form()
        item_form = ItemDef.schema().render_form()
        return (
            tool_note
            + "\n\n## 资源策略：填表创建\n"
            "本世界不使用资源包：NPC 与物品由你填表创建，无需查库。\n"
            "填表创建必须贴合上面的世界背景设定（世界观、风格、属性平衡），"
            "属性要符合 D&D 规则常识，超出范围会被拒绝并触发修正。\n"
            "创建 NPC：npc_add: <字段>，字段可填：\n"
            f"{npc_form}\n"
            "示例：npc_add: name=山贼首领, char_class=盗贼, level=5, hp=32, ac=15, "
            "dexterity=17, skills=隐匿/欺瞒, attitude=敌对\n"
            "创建物品：item_add: <字段>，字段可填：\n"
            f"{item_form}\n"
            "示例：item_add: name=灰烬长刀, type=武器, damage_dice=1d8, "
            "damage_type=火焰, value_cp=500\n"
            "item_add 只定义物品；要放进背包，需在同一[物品变更]区块中再写 + 名称 x数量。"
        )

    def _build_system_prompt(self) -> str:
        char_summary = self.character.summary()
        format_rule = "\n\n[记住] [状态]必须包含'玩家:'和'目标:'两行。有敌人/NPC就写目标行并加[敌对][中立][友方]标签。多个目标每个单独一行用'其他:'（不要用xN合并）。无目标写'目标: 无'。目标/其他名称必须是稳定角色名，禁止加括号或事件描述（如「(已逃窜)」），名称一律用中文（如「哥布林」「地精喽啰」），禁止英文原名（如 Goblin、Orc）。角色信息中【装备】是穿在身上的（有槽位），【背包】是携带品，【金钱】是货币总量（单位为cp），三者不要混淆。\n角色对话用「」包裹，特殊名词（地名、物品名、法术名、组织名等）用【】包裹。\n\n## 资源变更格式\n在输出末尾附加以下区块（不要插入叙事中间）：\n\n### [物品变更] — 仅限物品和金钱\n[物品变更]\n+ 物品名称（装备槽位）   ← 加物品，可指定装备槽位\n+ 物品名称 x数量        ← 加多个\n- 物品名称              ← 移除物品\ncp: +N                  ← 加铜币（N为铜币数，1金=10000铜）\ncp: -N                  ← 扣铜币\n注意：金钱统一使用cp（铜币）为单位，不要用金币、银币。1金=10000铜，1银=100铜。\n\n### [状态变更] — HP / 目标 / NPC\n[状态变更]\nhp: +N                  ← 玩家加生命值\nhp: -N                  ← 玩家扣生命值\nmax_hp: +N              ← 增加最大生命值\nmax_hp: -N              ← 减少最大生命值\ntarget: NPC名称         ← 设置目标（后续指令作用于该目标）\ntarget_hp: +N           ← 目标加生命值\ntarget_hp: -N           ← 目标扣生命值\ntarget_cp: +N           ← 目标加铜币\ntarget_cp: -N           ← 目标扣铜币\nnpc_add: 名称, AC:10, HP:8/8, [中立] ← 创建新NPC并设为目标\n请使用标准的D&D物品名称。如果物品不在游戏库中，系统会提示你修改。"
        template_note = ""
        if self.template and not self.history:
            t = load_opening_template(self.template)
            if t:
                template_note = f"\n\n## 开场模板\n{t}\n严格按此模板生成第一轮输出。"

        story_note = ""
        if self.story_pack_content:
            story_note = f"\n\n## 故事包\n{self.story_pack_content}\n故事剧情必须遵循此故事包设定，人物、地名、组织以此为准。"

        setting = self.setting_content if self.setting_content else "一个标准的 D&D 奇幻世界。"
        core_rules_text = _load_rules()

        prompt = SYSTEM_PROMPT_TEMPLATE.format(setting_content=setting, core_rules=core_rules_text)
        prompt += f"\n\n## 当前角色信息\n{char_summary}" + format_rule + template_note + story_note
        prompt += self._resource_strategy_note()

        if self.compressed_history:
            history_lines = []
            for h in self.compressed_history:
                history_lines.append(f"第{h['round']}轮：{h['summary']}")
            prompt += f"\n\n## 冒险历程\n" + "\n".join(history_lines)

        return prompt

    def _build_messages(self, player_input: str) -> list:
        system_content = self._build_system_prompt()
        messages = [{"role": "system", "content": system_content}]
        messages.append({"role": "user", "content": player_input + "\n\n[记住] [状态]必包含'玩家:'和'目标:'两行。有敌人/NPC就写目标行并加[敌对][中立][友方]标签。多个目标每个单独一行用'其他:'（不要用xN合并）。无目标写'目标: 无'。目标名称禁止加括号或事件描述（如「(已逃窜)」），状态写进[事件]，名称一律用中文（如「哥布林」「地精喽啰」），禁止英文原名（如 Goblin、Orc）。角色对话用「」包裹，特殊名词用【】包裹。数据变更（物品/金钱/HP/NPC）优先调用工具；工具不可用时才在末尾附加[物品变更]/[状态变更]区块。金钱统一用cp，HP用hp。"})
        return messages

    def _handle_dice_roll(self, player_input: str) -> Optional[str]:
        match = re.match(r"^/roll\s*(.*)", player_input.strip())
        if not match:
            return None
        expr = match.group(1).strip() or "d20"

        def roll_dice(m):
            count = int(m.group(1)) if m.group(1) else 1
            sides = int(m.group(2))
            modifier = int(m.group(3)) if m.group(3) else 0
            if count < 1:
                count = 1
            results = [random.randint(1, sides) for _ in range(count)]
            total = sum(results) + modifier
            return str(total)

        expr_parsed = re.sub(r"(\d+)?d(\d+)(?:\s*\+\s*(\d+))?", roll_dice, expr)
        try:
            result = eval(expr_parsed)
        except:
            return f"无效骰子: {expr}"

        return f"[投骰] {expr} = **{result}**"

    def send_message_stream(self, player_input: str, tools=None, tool_executor=None, status_cb=None):
        messages = self._build_messages(player_input)
        self.last_tool_results = []
        self._used_tools = False

        if not self.client:
            yield "错误: API 未配置"
            return

        use_tools = bool(tools and tool_executor)
        try:
            collected = ""
            tool_rounds = 0
            while True:
                kwargs = dict(
                    model=Config.MODEL_NAME,
                    messages=messages,
                    stream=True,
                    temperature=0.8,
                    max_tokens=8192,
                )
                if use_tools:
                    kwargs["tools"] = tools
                self.last_usage = None
                try:
                    response = self.client.chat.completions.create(
                        **kwargs, stream_options={"include_usage": True},
                    )
                except Exception:
                    if use_tools:
                        # 后端不支持工具 → 自动回退文本协议
                        use_tools = False
                        continue
                    response = self.client.chat.completions.create(**kwargs)

                tool_calls_acc: dict[int, dict] = {}
                self._truncated = False
                for chunk in response:
                    if getattr(chunk, "usage", None):
                        self.last_usage = {
                            "prompt_tokens": chunk.usage.prompt_tokens,
                            "completion_tokens": chunk.usage.completion_tokens,
                            "total_tokens": chunk.usage.total_tokens,
                        }
                        continue
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason == "length":
                        self._truncated = True
                    delta = choice.delta
                    if delta.content:
                        content = delta.content
                        collected += content
                        yield content
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            acc = tool_calls_acc.setdefault(
                                tc.index, {"id": tc.id or "", "name": "", "args": ""}
                            )
                            if tc.id:
                                acc["id"] = tc.id
                            if tc.function and tc.function.name:
                                acc["name"] = tc.function.name
                            if tc.function and tc.function.arguments:
                                acc["args"] += tc.function.arguments

                if not tool_calls_acc or tool_rounds >= 8:
                    break
                tool_rounds += 1
                self._used_tools = True

                has_target_check = any(c["name"] == "target_check" for c in tool_calls_acc.values())
                if has_target_check and status_cb:
                    status_cb("目标检定中...")

                # 把工具调用与结果注入会话，继续取最终叙事
                messages.append({
                    "role": "assistant",
                    "content": collected or None,
                    "tool_calls": [
                        {"id": c["id"], "type": "function",
                         "function": {"name": c["name"], "arguments": c["args"]}}
                        for c in tool_calls_acc.values()
                    ],
                })
                for c in tool_calls_acc.values():
                    args = {}
                    try:
                        args = json.loads(c["args"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    reply = tool_executor(c["name"], args)
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content": reply})

                if has_target_check and status_cb:
                    status_cb("DM 叙述检定结果...")

            self._round_num += 1
            self.last_assistant = collected
            self._compress_history(player_input, collected)

            self.history.append({"role": "user",
                                "content": player_input if not player_input.startswith("/roll") else f"[指令] {player_input}"})
            self.history.append({"role": "assistant", "content": collected})

        except Exception as e:
            yield f"API 请求失败: {e}"

    def _compress_history(self, player_input: str, dm_response: str):
        try:
            prompt = (
                f"将以下 D&D 游戏轮次压缩为 1-2 句中文摘要，只保留关键事件和叙事进展：\n\n"
                f"玩家: {player_input}\n\n"
                f"DM: {dm_response}"
            )
            r = self.client.chat.completions.create(
                model=Config.MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                temperature=0.3,
                max_tokens=128,
            )
            summary = r.choices[0].message.content.strip()
            self.compressed_history.append({"round": self._round_num, "summary": summary})
        except Exception:
            self.compressed_history.append({"round": self._round_num, "summary": "(摘要生成失败)"})

    def usage_summary(self) -> str:
        if not self.last_usage:
            return ""
        p = self.last_usage.get("prompt_tokens", 0)
        c = self.last_usage.get("completion_tokens", 0)
        t = self.last_usage.get("total_tokens", p + c)
        return f"（upload: {p} tokens / download: {c} tokens / total: {t} tokens）"

    def to_dict(self) -> dict:
        return {
            "character": self.character.to_dict(),
            "history": self.history,
            "last_scene": self.last_scene,
            "last_scene_detail": self.last_scene_detail,
            "last_time": self.last_time,
            "last_assistant": self.last_assistant,
            "compressed_history": self.compressed_history,
            "setting_stem": self.setting_stem,
            "resource_mode": self.resource_mode,
        }

    def get_history(self) -> list:
        return self.history

    def set_history(self, history: list):
        self.history = history
