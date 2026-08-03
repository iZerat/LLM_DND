import io
import sys

from core.character import Character
from core.game_master import GameMaster
from core.rounds.game_round import GameRound
from core.rounds.base_round import PromptResult
from world.state import WorldState
from world.entity import NPC


def make_char():
    return Character(name="荷鲁斯", level=1, hp=10, max_hp=10, strength=14,
                     dexterity=12, char_class="warlock")


PRELUDE = """[环境]
地点：森林小径
时间：午后
温度：20℃（温暖）

[事件]
山贼目标A拦住去路，拔出弯刀。

[选择]
1. 拔剑迎战（攻击 检定）
2. 尝试说服（魅力 DC 12）
3. 转身逃跑（敏捷 DC 10）
"""
NPC_NARR = "[副事件]\n目标A挥刀向你扑来。"
PLAYER_NARR = "[副事件]\n你的长剑划破空气斩向目标A。"


class FakeGM(GameMaster):
    def __init__(self, char, lazy_choices=False):
        super().__init__(char)
        self.lazy_choices = lazy_choices

    def _make_choices(self, tool_executor):
        if tool_executor:
            for label, ctype in [
                ("拔剑迎战", "attack"),
                ("尝试说服", "ability_check"),
                ("转身逃跑", "narrative"),
            ]:
                tool_executor("create_choice", {
                    "label": label, "choice_type": ctype,
                    "reason": "为玩家提供本轮的决策选项",
                })

    def send_message_stream(self, user_text, tools=None, tool_executor=None,
                            status_cb=None, system_override=None, round_num=None):
        if "战斗已经开始" in user_text or "新一轮战斗开始" in user_text:
            if not self.lazy_choices:
                self._make_choices(tool_executor)
            yield PRELUDE
        elif "[系统要求]" in user_text:
            self._make_choices(tool_executor)
            yield PRELUDE
        elif "玩家本轮行动" in user_text:
            yield PLAYER_NARR
        else:
            yield NPC_NARR

    def complete(self, messages, max_tokens=400, temperature=0.7):
        return "行动: 攻击\n目标: 玩家"


def run_combat(seed_quit=True, lazy_choices=False):
    gm = FakeGM(make_char(), lazy_choices=lazy_choices)
    ws = WorldState()
    ws.add_active(NPC(id="t1", name="目标A", char_class="thug", hp=12, max_hp=12,
                      base_ac=15, dexterity=10, strength=14, attitude=-40,
                      inventory=["长剑"]))
    gm.world_state = ws
    inputs = iter(["1", "我是自由行动", "/quit"] if seed_quit else ["1"])

    def fake_prompt(self):
        val = next(inputs, "/quit")
        if val == "/quit":
            return PromptResult(action="quit")
        return PromptResult(player_input=val)

    GameRound._prompt = fake_prompt
    return GameRound(gm).run()


def run_noncombat(lazy_choices=False):
    canned = """[环境]
地点：微风港
时间：黄昏
温度：15℃（凉爽）

[事件]
你在酒馆醒来。

[选择]
1. 与酒保交谈（魅力 检定 DC 10）
2. 离开酒馆
"""
    gm = FakeGM(make_char(), lazy_choices=lazy_choices)

    def send(self, user_text, tools=None, tool_executor=None,
             status_cb=None, system_override=None, round_num=None):
        if not self.lazy_choices or "[系统要求]" in user_text:
            self._make_choices(tool_executor)
        yield canned

    gm.send_message_stream = send.__get__(gm, FakeGM)
    inputs = iter(["1", "/quit"])

    def fake_prompt(self):
        val = next(inputs, "/quit")
        if val == "/quit":
            return PromptResult(action="quit")
        return PromptResult(player_input=val)

    GameRound._prompt = fake_prompt
    return GameRound(gm).run()


if __name__ == "__main__":
    res1 = run_noncombat()
    print("noncombat returned:", res1)
    res2 = run_combat()
    print("combat returned:", res2)
    res3 = run_combat(lazy_choices=True)
    print("combat+repair returned:", res3)
    print("SMOKE OK")
