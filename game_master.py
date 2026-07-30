import json
import random
import re
from typing import Optional
from openai import OpenAI
from config import Config
from character import Character

SYSTEM_PROMPT = """你是龙与地下城（D&D）5e 的地下城主（DM），你将用中文主持一场精彩的冒险。

## 输出格式

每一轮都必须严格按照以下格式输出（使用方括号标注区块）：

[场景] 严格按以下格式填写，每行一个字段：
地点：xxx
时间：xxx
温度：xxx
（可选字段，有多余信息再补充：湿度、光照、风速、海拔等）
注意：只填关键数据，不要写描述性语句。描述性内容放到[事件]中。

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
- 属性调整值 = (属性值-10)//2
- 熟练加值: 1级+2
- 检定: d20 + 属性调整值 + (熟练加值 if 熟练)
- 攻击: d20 + 属性调整值 + 熟练加值 vs AC
- 优势: 2d20取高; 劣势: 2d20取低
- DC: 5极简 10简单 15中等 20困难 25极难

## 对话与行动标记
- 「NPC对话」
- **关键动作或战斗**
- *环境氛围*

## 要求
1. 语言精炼，描述生动，拒绝长篇大论
2. 每一轮都必须给出[选择]
3. 用中文
4. 保持冒险节奏紧凑
5. [状态]必须包含'玩家:'和'目标:'两行，这是硬性要求"""


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


class GameMaster:
    def __init__(self, character: Character, template: str = "random"):
        self.character = character
        self.client: Optional[OpenAI] = None
        self.history: list = []
        self._init_client()
        self.last_choices: list = []
        self.last_choices_map: dict = {}
        self.last_scene: str = ""
        self.last_scene_detail: str = ""
        self.template = template

    def _init_client(self):
        if Config.is_ready():
            self.client = OpenAI(
                base_url=Config.API_BASE_URL,
                api_key=Config.API_KEY,
            )

    def _build_messages(self, player_input: str) -> list:
        char_summary = self.character.summary()
        format_rule = "\n\n[记住] [状态]必须包含'玩家:'和'目标:'两行。有敌人/NPC就写目标行并加[敌对][中立][友方]标签。多个目标每个单独一行用'其他:'（不要用xN合并）。无目标写'目标: 无'。"
        template_note = ""
        if self.template and self.template != "random" and not self.history:
            t = OPENING_TEMPLATES.get(self.template)
            if t:
                template_note = f"\n\n## 开场模板\n{t}\n严格按此模板生成第一轮输出。"
        system_content = SYSTEM_PROMPT + f"\n\n## 当前角色信息\n{char_summary}" + format_rule + template_note
        messages = [{"role": "system", "content": system_content}]
        for h in self.history:
            messages.append(h)
        messages.append({"role": "user", "content": player_input + format_rule})
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
        if player_input.startswith("/roll"):
            roll_result = self._handle_dice_roll(player_input)
            if roll_result:
                self.history.append({"role": "user",
                                    "content": f"[投骰] {player_input} -> {roll_result}"})
                yield roll_result
                return

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
                max_tokens=2048,
            )

            collected = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    collected += content
                    yield content

            self.history.append({"role": "user",
                                "content": player_input if not player_input.startswith("/roll") else f"[指令] {player_input}"})
            self.history.append({"role": "assistant", "content": collected})

        except Exception as e:
            yield f"API 请求失败: {e}"

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
        }

    def get_history(self) -> list:
        return self.history

    def set_history(self, history: list):
        self.history = history
