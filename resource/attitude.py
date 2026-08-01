from __future__ import annotations
"""统一态度系统（Attitude System）单一事实源。

设计见 `design/好感度态度系统.md`：每个 NPC 一条 -100..+100 的可演化分数，
阈值 -40/+40 映射官方三态（Friendly/Hostile/Indifferent）。

本模块只放常量与纯函数，不落账、不接触 world/UI；所有修改走调节器。
"""
from typing import Optional

# ── 分数范围与阈值 ──

ATTITUDE_MIN = -100
ATTITUDE_MAX = 100

FRIENDLY_THRESHOLD = 40    # >= 40 → Friendly
HOSTILE_THRESHOLD = -40    # <= -40 → Hostile
DEFAULT_ATTITUDE = 0       # Indifferent

# ── 等级（沿用现有代码的英文键） ──

FRIENDLY = "friendly"
INDIFFERENT = "neutral"
HOSTILE = "hostile"

LEVEL_CN = {FRIENDLY: "友方", INDIFFERENT: "中立", HOSTILE: "敌对"}

# 创建路径的标签 → 分数落点（落到边界即对应等级）
# 中文标签 + 英文键都接受；未识别返回 None。
LABEL_TO_VALUE = {
    "敌对": HOSTILE_THRESHOLD,
    "中立": DEFAULT_ATTITUDE,
    "友方": FRIENDLY_THRESHOLD,
    HOSTILE: HOSTILE_THRESHOLD,
    INDIFFERENT: DEFAULT_ATTITUDE,
    FRIENDLY: FRIENDLY_THRESHOLD,
}

# 旧档字符串态度 → 分数落点（兼容 str attitude 的存档）
LEGACY_STR_TO_VALUE = LABEL_TO_VALUE


# ── 事件表（14 条，数值为自定义，参考策略游戏加权模型） ──
# 每条：{delta, desc}。阶段 4 的 Supervisor 行为分类按事件 id 落账。

EVENT_TABLE: dict[str, dict] = {
    "attack":            {"delta": -8,  "desc": "攻击（未致死），含打斗/施法伤害"},
    "kill_comrade":      {"delta": -20, "desc": "击杀其亲友/同伴，当面或知情"},
    "steal":             {"delta": -10, "desc": "偷窃/欺诈它"},
    "insult":            {"delta": -6,  "desc": "公开侮辱/威吓"},
    "betray":            {"delta": -15, "desc": "背弃承诺/撕毁协议"},
    "heal":              {"delta": +10, "desc": "治疗/救助它"},
    "save_life":         {"delta": +15, "desc": "救命（濒死救回）"},
    "gift":              {"delta": +5,  "desc": "送礼/行贿"},
    "complete_quest":    {"delta": +12, "desc": "完成它的委托"},
    "support_battle":    {"delta": +8,  "desc": "战斗中支援它（同侧参战）"},
    "praise":            {"delta": +3,  "desc": "当众礼遇/赞美"},
    "defeat_rival":      {"delta": +10, "desc": "击败它的仇敌（共同的敌人）"},
    "refuse_request":    {"delta": -4,  "desc": "拒绝它的请求"},
    "trample_faith":     {"delta": -12, "desc": "践踏它的信仰/荣誉"},
}


# ── 纯函数 ──

def clamp(value) -> int:
    """夹取分数到 [-100, 100]。"""
    v = int(value)
    return max(ATTITUDE_MIN, min(ATTITUDE_MAX, v))


def level(value) -> str:
    """分数 → 等级英文键（friendly / neutral / hostile）。"""
    v = clamp(value)
    if v >= FRIENDLY_THRESHOLD:
        return FRIENDLY
    if v <= HOSTILE_THRESHOLD:
        return HOSTILE
    return INDIFFERENT


def level_cn(value) -> str:
    """分数 → 中文标签（友方 / 中立 / 敌对）。"""
    return LEVEL_CN[level(value)]


def int_to_label(value) -> str:
    """分数 → 中文标签（供 UI / [状态] 展示）。"""
    return level_cn(value)


def label_to_int(label) -> Optional[int]:
    """创建路径标签 → 分数落点；未识别返回 None（由调用方兜底 0）。

    接受中文（敌对/中立/友方）与英文键（hostile/neutral/friendly）。
    """
    if label is None:
        return None
    return LABEL_TO_VALUE.get(str(label).strip())


def coerce_legacy(value) -> int:
    """旧档/旧代码的 attitude 值 → 分数。

    - int 直接夹取；
    - str（"hostile"/"neutral"/"friendly" 或中文）走落点表；
    - 其他一律 0（默认 Indifferent）。
    """
    if isinstance(value, bool):
        return DEFAULT_ATTITUDE
    if isinstance(value, int):
        return clamp(value)
    if isinstance(value, str):
        v = label_to_int(value)
        return DEFAULT_ATTITUDE if v is None else v
    return DEFAULT_ATTITUDE


def decay_step(value) -> int:
    """每轮向 0 漂移的步长：绝对值越大消得越快（建议 1–2 点/轮）。"""
    v = clamp(value)
    if v == 0:
        return 0
    return max(1, abs(v) // 40)


def decay(value) -> int:
    """向 0 漂移一档，返回夹取后的新分数。"""
    v = clamp(value)
    if v == 0:
        return 0
    step = decay_step(v)
    return v - step if v > 0 else v + step
