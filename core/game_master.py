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
描述当前发生了什么。承接上一轮玩家的选择结果，说明其行动造成的影响；若玩家上一轮行动是系统结算的检定（输入中带 [检定]/[攻击]），其结果已给出，直接作为事实承接。描述要有画面感，但保持精炼。3-5句话。

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

## 目标检定与[副事件]（可选）
当[事件]中的目标（NPC/敌人）或玩家需要做攻击、豁免或属性检定，且未被系统机械结算时：
1. 先描述要做的事，然后调用 d20_roll 工具提交检定（actor=发起者，kind=ability_check/saving_throw/attack_roll；attack_roll 对目标 AC，其余对 DC）；
2. 系统会立即在本地掷出骰子，并把骰面、调整值、总值、DC/AC 和成败返回给你；玩家攻击的伤害与目标态度基线也由系统落账；
3. 收到判定结果后，在[副事件]区块中用2-3句话描述目标行动的结果（命中/落空、成功/失败的效果，是否暴击/大失败）。
另外，若本轮系统已结算在场 NPC 的行动（以 [系统·NPC行动·已结算] 注入，伤害已直接落账），
也应把每个 NPC 的行动分别写入[副事件]，每行以 敌对/友方/中立 标签开头。
若玩家上一轮的行动是系统结算的检定（玩家输入中带 [检定] 或 [攻击] 标注，骰面与成败已给出），
在[副事件]中用2-3句话补充描述该行动的结果（承接[事件]的叙述，不要重复判定或改数值）。
[副事件]只在上述目标检定或玩家检定发生时输出，且必须放在回答的最后；没有检定就不要输出[副事件]。

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
- 生命归零: 0 HP 即昏迷；巨量伤害（余量≥生命上限）即死；玩家死亡豁免由系统每回合起手自动掷，NPC 0 HP 倒地留场可治疗苏醒
- 种族特性、专长和技能在角色信息中列出"""

NARRATION_SYSTEM_PROMPT = """你是基于 D&D 5e 规则的地城主（GM），正在战斗回合的逐段进行中，只负责把一个目标/玩家已由系统机械结算好的行动编织进叙事。

## 输出格式
只输出一个区块，2-3 句话：

[副事件]
（描述该行动的过程与结果，要有画面感。行动结果已被系统结算/落账，不要重复判定或扣血，也不要改写给定的数值。）

## 要求
1. 只输出 [副事件]，不要输出 [环境]、[事件]、[状态]、[选择]、[历史] 等区块
2. 用中文，精炼、有画面感
3. 不要添加任何标记语法之外的说明"""



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
                 story_pack_id: str = "", story_pack_content: str = "", world_source: str = "llm", resource_pack: str = "",
                 world=None):
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
        if world is not None:
            self.world_state = world
        # 当前游戏会话绑定的存档槽位（空串=尚未存档）；载入存档时由 load_game 绑定
        self.save_slot: str = ""
        # 角色创建时的完整快照（角色模板），随存档保存，不随游戏进程变化
        from core.templates import template_data
        self.character_template: dict = template_data(character)
        self.compressed_history: list = []
        self._round_num: int = 0
        self._truncated: bool = False
        self.last_usage: dict | None = None

    @property
    def world(self):
        """当前世界实例（World 接管 WorldState 职责后的一等字段）。

        runtime 在 game_round/game_loop 中构造 World 并赋给 gm.world_state，
        此属性返回同一实例；旧代码继续用 gm.world_state 亦可。
        """
        return getattr(self, "world_state", None)

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
            "对游戏数据的所有变更（物品、金钱、HP、NPC）一律通过调用工具完成。"
            "除[状态]区块用于展示外，禁止在叙事中手写 [物品变更]/[状态变更] 文本区块。"
            "若工具调用失败或不可用，只继续叙事，不做任何数据变更（工具是唯一的写数通道）。"
            "[状态] 区块仍须输出用于状态展示。"
        )
        if self.resource_mode == RESOURCE_MODE_PACK:
            return (
                tool_note
                + "\n\n## 资源策略：查表创建\n"
                "本世界使用资源包：NPC 与物品均从资源库查询生成，不要凭空捏造。"
                "需要 NPC 时调用 create_npc 工具，name 填写资源库中真实存在的名称。"
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
            "创建 NPC：调用 create_npc 工具，字段可填：\n"
            f"{npc_form}\n"
            "示例：name=山贼首领, char_class=盗贼, level=5, hp=32, ac=15, "
            "dexterity=17, skills=隐匿/欺瞒, attitude=敌对\n"
            "创建物品：调用 create_item 工具，字段可填：\n"
            f"{item_form}\n"
            "示例：name=灰烬长刀, type=武器, damage_dice=1d8, "
            "damage_type=火焰, value_cp=500\n"
            "create_item 只定义物品；要放进背包，再调用 grant_item。"
        )

    def _build_system_prompt(self) -> str:
        char_summary = self.character.summary()
        format_rule = "\n\n[记住] [状态]必须包含'玩家:'和'目标:'两行。有敌人/NPC就写目标行并加[敌对][中立][友方]标签。多个目标每个单独一行用'其他:'（不要用xN合并）。无目标写'目标: 无'。目标/其他名称必须是稳定角色名，禁止加括号或事件描述（如「(已逃窜)」），名称一律用中文（如「哥布林」「地精喽啰」），禁止英文原名（如 Goblin、Orc）。角色信息中【装备】是穿在身上的（有槽位），【背包】是携带品，【金钱】是货币总量（单位为cp），三者不要混淆。\n角色对话用「」包裹，特殊名词（地名、物品名、法术名、组织名等）用【】包裹。\n数据变更（物品、金钱、HP、NPC）一律通过调用工具完成，禁止在叙事中手写 [物品变更]/[状态变更] 文本区块；工具失败时只继续叙事，不做数据变更。金钱统一用cp（1金=10000铜、1银=100铜），HP用hp。\n工具边界：change_status 只改生命值（HP/最大HP），change_attitude 只改态度，两者绝不互相代劳。攻击伤害由 d20_roll 工具在掷骰后由系统自动结算（DM 段直接结算，玩家段 NPC 发起的攻击留待对应行动段），你无需再调用 change_status 重复扣血；同一伤害只结算一次，重复调用会被拒绝。\n资源创建：创建 NPC/物品前请先调用 search_resource 查询本地目录（按名称/别名/类型搜索，返回库中匹配条目）；若未命中可换表述重试；若多次仍未命中，请改用库中真实存在的名称或调整叙事（除非系统已告知可以填表创建）。\n叙事中写到的 HP/AC/态度数字必须与真实数据一致，否则会被 [系统提醒] 打回修正。\nset_target 只能选择已在场的 NPC（通过 get_by_name 确认）；创建新目标 NPC 必须调用 create_npc 工具。\n选择选项：每轮在输出 [选择] 文本块的同时，必须为每个选项调用 create_choice 工具（choice_type=attack/ability_check/narrative），确保选项能被系统正确结算（攻击检定/属性检定/纯叙事）。选项文本（label）与 [选择] 块中的编号一一对应。"
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

    def _build_messages(self, player_input: str, system_override: str | None = None) -> list:
        if system_override:
            system_content = system_override
            user_content = player_input
        else:
            system_content = self._build_system_prompt()
            user_content = player_input + "\n\n[记住] [状态]必包含'玩家:'和'目标:'两行。有敌人/NPC就写目标行并加[敌对][中立][友方]标签。多个目标每个单独一行用'其他:'（不要用xN合并）。无目标写'目标: 无'。目标名称禁止加括号或事件描述（如「(已逃窜)」），状态写进[事件]，名称一律用中文（如「哥布林」「地精喽啰」），禁止英文原名（如 Goblin、Orc）。角色对话用「」包裹，特殊名词用【】包裹。数据变更（物品/金钱/HP/NPC）一律通过调用工具完成，禁止手写[物品变更]/[状态变更]区块；工具失败时只继续叙事，不做数据变更。金钱统一用cp（1金=10000铜、1银=100铜），HP用hp。工具边界：change_status 只改生命值，change_attitude 只改态度，两者不互相代劳；攻击伤害必须与 d20_roll 判定结果一致且只落账一次；叙事中的 HP/AC/态度数字必须与真实数据一致，否则会被 [系统提醒] 打回。"
        messages = [{"role": "system", "content": system_content}]
        messages.append({"role": "user", "content": user_content})
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

    def send_message_stream(self, player_input: str, tools=None, tool_executor=None, status_cb=None, system_override: str | None = None, round_num: int | None = None):
        """流式对话。round_num 传入时覆盖内部自增计数，使同一回合内多个段共享同一轮号。"""
        messages = self._build_messages(player_input, system_override=system_override)
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

                has_d20_roll = any(c["name"] == "d20_roll" for c in tool_calls_acc.values())
                if has_d20_roll and status_cb:
                    status_cb("正在结算目标检定…")

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

                if has_d20_roll and status_cb:
                    status_cb("目标检定已结算，DM 继续思考…")

            self._round_num += 1
            if round_num is not None:
                self._round_num = round_num
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

    def complete(self, messages: list[dict], max_tokens: int = 400,
                 temperature: float = 0.7) -> str:
        """非流式补全：供 NPC 行动控制器等子请求复用。

        API 未配置或请求失败时返回空串（由调用方兜底）。
        """
        if not self.client:
            return ""
        try:
            r = self.client.chat.completions.create(
                model=Config.MODEL_NAME,
                messages=messages,
                stream=False,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return r.choices[0].message.content or ""
        except Exception:
            return ""

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
