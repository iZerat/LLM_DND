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

[场景]
只描述环境本身：地点、时间、温度、天气。不要写人物行为或事件。1-2句话。

[场景细节]
额外列出海拔、湿度、光照、风速等物理环境参数，供 /scene 命令使用。如果没有则不写。

[事件]
描述当前发生了什么。承接上一轮玩家的选择结果。描述要有画面感，但保持精炼。3-5句话。

[状态] 严格按以下格式填表——每行一个字段，不要用 |
玩家: 荷鲁斯 Lv.1 龙裔 邪术师, AC:13, HP:8/8
目标: [敌对]活化盔甲, AC:15, HP:12/12   ← 无目标则写：目标: 无
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
- [场景] 1-2句话
- [场景细节] 可选，3-5个参数
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
5. [状态]必须包含 | 分隔符，有敌人/NPC必须写在 | 右侧，这是硬性要求"""


class GameMaster:
    def __init__(self, character: Character):
        self.character = character
        self.client: Optional[OpenAI] = None
        self.history: list = []
        self._init_client()
        self.last_choices: list = []
        self.last_choices_map: dict = {}
        self.last_scene: str = ""

    def _init_client(self):
        if Config.is_ready():
            self.client = OpenAI(
                base_url=Config.API_BASE_URL,
                api_key=Config.API_KEY,
            )

    def _build_messages(self, player_input: str) -> list:
        char_summary = self.character.summary()
        format_rule = "\n\n[记住] [状态]必须包含'玩家:'和'目标:'两行。有敌人/NPC就写目标行并加[敌对][中立][友方]标签。无目标写'目标: 无'。"
        messages = [
            {"role": "system",
             "content": SYSTEM_PROMPT + f"\n\n## 当前角色信息\n{char_summary}" + format_rule},
        ]
        for h in self.history:
            messages.append(h)
        messages.append({"role": "user", "content": player_input + format_rule})
        return messages

    def _handle_dice_roll(self, player_input: str) -> Optional[str]:
        match = re.match(r"^/roll\s+(.+)", player_input.strip())
        if not match:
            return None
        expr = match.group(1).strip()

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
        for name, content in re.findall(r"\[(场景|场景细节|事件|状态|选择|历史)\]\s*(.*?)(?=\[.*?\]|\Z)", response_text, re.DOTALL):
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
            m = re.search(r"\[状态\].*?(?=\[|\Z)", repair, re.DOTALL)
            if m:
                new_status = m.group(0).strip()
                response_text = re.sub(r"\[状态\].*?(?=\[|\Z)", new_status, response_text, count=1, flags=re.DOTALL)
                self.history.append({"role": "assistant", "content": "\n（补全的目标信息）\n" + repair})
        except:
            pass
        return response_text

    def _repair_status(self, response_text: str) -> str:
        """检查[状态]是否缺目标信息，缺则反问DM补全"""
        sections = {}
        pattern = r"\[(场景|场景细节|事件|状态|选择|历史)\]\s*(.*?)(?=\[.*?\]|\Z)"
        for name, content in re.findall(pattern, response_text, re.DOTALL):
            sections[name] = content.strip()

        status_text = sections.get("状态", "")
        event_text = sections.get("事件", "")

        has_target_line = bool(re.search(r"目标\s*:", status_text))
        has_enemy_keywords = any(w in event_text for w in ["攻击", "敌人", "敌对", "战斗", "拔刀", "挥剑", "射击", "敌对"])

        if has_target_line or not has_enemy_keywords:
            return response_text

        follow_up = (
            "你的[状态]区块缺少目标信息。请重新输出[状态]区块（只输出[状态]），"
            "包含'玩家:'和'目标:'两行。如果当前场景确实没有敌人/NPC，目标行写'目标: 无'。"
        )
        messages = [{"role": "user", "content": follow_up}]
        try:
            r = self.client.chat.completions.create(
                model=Config.MODEL_NAME,
                messages=messages,
                temperature=0.3,
                max_tokens=300,
            )
            repair = r.choices[0].message.content or ""
            m = re.search(r"\[状态\].*?(?=\[|\Z)", repair, re.DOTALL)
            if m:
                new_status = m.group(0).strip()
                response_text = re.sub(r"\[状态\].*?(?=\[|\Z)", new_status, response_text, count=1, flags=re.DOTALL)
        except:
            pass
        return response_text

    def to_dict(self) -> dict:
        return {
            "character": self.character.to_dict(),
            "history": self.history,
            "last_scene": self.last_scene,
        }

    def get_history(self) -> list:
        return self.history

    def set_history(self, history: list):
        self.history = history
