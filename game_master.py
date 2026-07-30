import json
import random
import re
from typing import Optional
from pathlib import Path
from openai import OpenAI
from config import Config
from character import Character

SYSTEM_PROMPT_TEMPLATE = """你是基于 D&D 5e 规则的地城主（GM），你将用中文主持一场精彩的冒险。

当前游戏的世界背景如下：
{setting_content}

## 输出格式

每一轮都必须严格按照以下格式输出（使用方括号标注区块）：

[场景] 严格按以下格式填写，每行一个字段：
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
（每轮都必须填写，与[场景]中的时间保持一致）

[事件]
描述当前发生了什么。承接上一轮玩家的选择结果。描述要有画面感，但保持精炼。3-5句话。

[状态] 严格按以下格式填表——每行一个字段，不要用 |
玩家: 荷鲁斯 Lv.1 龙裔 邪术师, AC:13, HP:8/8
目标: [敌对]活化盔甲, AC:15, HP:12/12   ← 主要目标（固定一个），无目标则写：目标: 无
其他: [敌对]地精喽啰, AC:12, HP:5/5     ← 其他目标（每个目标单独一行，不要用xN合并）
标签说明：[敌对]敌人 [中立]中立NPC [友方]友方NPC  —— 必须存在

[选择]
1. 选项一
2. 选项二
3. 选项三
(给出3个具体的行动选项，让玩家可以选。玩家也可以自己输入其他行动。)

[历史]
- 上一轮的行动记录(只记录事实，不要写判定和结果，结果会在本轮[事件]中描述)

## 字数控制
- 每轮总输出控制在200字以内
- [场景] 3-6行字段
- 场景字段只填数据，不要写句子
- [事件] 3-5句话
- [状态] 1行
- [选择] 3个选项，每个一行
- [历史] 1行
- 描述精炼，不啰嗦

## 核心规则
{core_rules}

## 对话与行动标记
- 「NPC对话」
- **关键动作或战斗**
- *环境氛围*

## 要求
1. 语言精炼，描述生动，拒绝长篇大论
2. 每一轮都必须给出[场景]、[事件]、[状态]、[选择]四个区块，缺一不可
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
    # Try with explicit DC
    m = re.search(r'[（(]\s*(\S+).*?DC\s*(\d+).*?[）)]', text)
    if m:
        ability_cn = m.group(1)
        if ability_cn in ABILITY_CN_TO_EN:
            return (ability_cn, ABILITY_CN_TO_EN[ability_cn], int(m.group(2)))
    # Try check name without DC -> default 10
    m = re.search(r'[（(]\s*(\S+?)\s*检定.*?[）)]', text)
    if m:
        ability_cn = m.group(1)
        if ability_cn in ABILITY_CN_TO_EN:
            return (ability_cn, ABILITY_CN_TO_EN[ability_cn], 10)
    return None


OPENING_TEMPLATES = {
    "random": None,
    "guide": (
        "开场模板：中立向导\n"
        "角色来到一座新的城镇/营地/驿站，一位神秘的中立向导主动搭话，"
        "提供当地的信息或警告。角色可以信任他、怀疑他或无视他。\n"
        "[状态]中必须包含：目标: [中立]向导, ..."
    ),
    "ambush": (
        "开场模板：敌对突袭\n"
        "角色刚抵达某处就遭到敌对生物或匪徒的突袭，必须立即应对。\n"
        "[状态]中必须包含：目标: [敌对]<敌人>, ..."
    ),
    "ally": (
        "开场模板：友方旅伴\n"
        "角色在路上遇到一位友善的旅人/商人/冒险者，对方主动示好并提出结伴同行或请求帮助。\n"
        "[状态]中必须包含：目标: [友方]<NPC名>, ..."
    ),
}


RULES_DIR = Path(__file__).parent / "rules"


def _load_rules() -> str:
    return CORE_RULES


class GameMaster:
    def __init__(self, character: Character, template: str = "random", setting_content: str = "", setting_stem: str = ""):
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
        self.compressed_history: list = []
        self._round_num: int = 0
        self._truncated: bool = False

    def _init_client(self):
        if Config.is_ready():
            self.client = OpenAI(
                base_url=Config.API_BASE_URL,
                api_key=Config.API_KEY,
            )

    def _build_system_prompt(self) -> str:
        char_summary = self.character.summary()
        format_rule = "\n\n[记住] [状态]必须包含'玩家:'和'目标:'两行。有敌人/NPC就写目标行并加[敌对][中立][友方]标签。多个目标每个单独一行用'其他:'（不要用xN合并）。无目标写'目标: 无'。角色信息中【装备】是穿在身上的（有槽位），【背包】是携带品，【金币】是货币，三者不要混淆。\n角色对话用「」包裹，特殊名词（地名、物品名、法术名、组织名等）用【】包裹。"
        template_note = ""
        if self.template and self.template != "random" and not self.history:
            t = OPENING_TEMPLATES.get(self.template)
            if t:
                template_note = f"\n\n## 开场模板\n{t}\n严格按此模板生成第一轮输出。"

        setting = self.setting_content if self.setting_content else "一个标准的 D&D 奇幻世界。"
        core_rules_text = _load_rules()

        prompt = SYSTEM_PROMPT_TEMPLATE.format(setting_content=setting, core_rules=core_rules_text)
        prompt += f"\n\n## 当前角色信息\n{char_summary}" + format_rule + template_note

        if self.compressed_history:
            history_lines = []
            for h in self.compressed_history:
                history_lines.append(f"第{h['round']}轮：{h['summary']}")
            prompt += f"\n\n## 冒险历程\n" + "\n".join(history_lines)

        return prompt

    def _build_messages(self, player_input: str) -> list:
        system_content = self._build_system_prompt()
        messages = [{"role": "system", "content": system_content}]
        messages.append({"role": "user", "content": player_input + "\n\n[记住] [状态]必须包含'玩家:'和'目标:'两行。有敌人/NPC就写目标行并加[敌对][中立][友方]标签。多个目标每个单独一行用'其他:'（不要用xN合并）。无目标写'目标: 无'。角色对话用「」包裹，特殊名词用【】包裹。"})
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

    def send_message_stream(self, player_input: str):
        messages = self._build_messages(player_input)

        if not self.client:
            yield "错误: API 未配置"
            return

        try:
            response = self.client.chat.completions.create(
                model=Config.MODEL_NAME,
                messages=messages,
                stream=True,
                temperature=0.8,
                max_tokens=8192,
            )

            collected = ""
            self._truncated = False
            for chunk in response:
                if chunk.choices[0].finish_reason == "length":
                    self._truncated = True
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    collected += content
                    yield content

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

    def needs_repair(self, response_text: str) -> bool:
        sections = {}
        for name, content in re.findall(r"\[(场景|场景细节|事件|状态|选择|历史)\]\s*(.*?)(?=\[(?:场景|场景细节|事件|状态|选择|历史)\]|\Z)", response_text, re.DOTALL):
            sections[name] = content.strip()
        status_text = sections.get("状态", "")
        event_text = sections.get("事件", "")
        has_target = bool(re.search(r"目标\s*:", status_text))
        has_enemy = any(w in event_text for w in ["攻击", "敌人", "敌对", "战斗", "拔刀", "挥剑", "敌对", "追", "冲突"])
        return not has_target and has_enemy

    def repair_status(self, response_text: str) -> str:
        """反问DM补全目标信息，返回修复后的完整文本"""
        follow_up = (
            "你上一轮回复中[状态]缺少目标信息。请只输出补充后的[状态]区块。"
        )
        messages = [{"role": "user", "content": follow_up}]
        try:
            r = self.client.chat.completions.create(
                model=Config.MODEL_NAME,
                messages=messages,
                stream=False,
                temperature=0.3,
                max_tokens=300,
            )
            repair = r.choices[0].message.content or ""
            m = re.search(r"\[状态\](.*?)(?=\[(?:场景|场景细节|事件|状态|选择|历史)\]|\Z)", repair, re.DOTALL)
            if m:
                raw = m.group(0)
                if not raw.startswith("[状态]"):
                    raw = "[状态]" + raw
                new_status = raw.strip()
                response_text = re.sub(r"\[状态\](.*?)(?=\[(?:场景|场景细节|事件|状态|选择|历史)\]|\Z)", new_status, response_text, count=1, flags=re.DOTALL)
                self.history.append({"role": "assistant", "content": "\n（补全的目标信息）\n" + repair})
        except:
            pass
        return response_text

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
        }

    def get_history(self) -> list:
        return self.history

    def set_history(self, history: list):
        self.history = history
