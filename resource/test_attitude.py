from __future__ import annotations
"""attitude.py 的轻量单测（无 pytest 依赖，直接 `python resource/test_attitude.py` 运行）。"""
import resource.attitude as at


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_clamp():
    _check(at.clamp(-1000) == -100, "clamp 下界")
    _check(at.clamp(1000) == 100, "clamp 上界")
    _check(at.clamp(-40) == -40, "clamp 边界保留")
    _check(at.clamp(3.7) == 3, "clamp 取整")


def test_level_thresholds():
    _check(at.level(40) == "friendly", "40 落 Friendly 边界")
    _check(at.level(39) == "neutral", "39 中立")
    _check(at.level(0) == "neutral", "0 中立")
    _check(at.level(-40) == "hostile", "-40 落 Hostile 边界")
    _check(at.level(-39) == "neutral", "-39 中立")


def test_label_roundtrip():
    _check(at.label_to_int("敌对") == -40, "中文敌对")
    _check(at.label_to_int("友方") == 40, "中文友方")
    _check(at.label_to_int("中立") == 0, "中文中立")
    _check(at.label_to_int("hostile") == -40, "英文 hostile")
    _check(at.label_to_int("friendly") == 40, "英文 friendly")
    _check(at.label_to_int(None) is None, "None 不识别")
    _check(at.label_to_int("未知") is None, "未知标签不识别")
    _check(at.int_to_label(60) == "友方", "int→中文")
    _check(at.int_to_label(-50) == "敌对", "int→中文 敌")
    _check(at.int_to_label(10) == "中立", "int→中文 中立")


def test_coerce_legacy():
    _check(at.coerce_legacy("hostile") == -40, "旧档 hostile→-40")
    _check(at.coerce_legacy("friendly") == 40, "旧档 friendly→40")
    _check(at.coerce_legacy("neutral") == 0, "旧档 neutral→0")
    _check(at.coerce_legacy(-30) == -30, "int 直接夹取")
    _check(at.coerce_legacy("??") == 0, "未知字符串→0")
    _check(at.coerce_legacy(None) == 0, "None→0")


def test_event_table():
    _check(len(at.EVENT_TABLE) == 14, "事件表 14 条")
    for k, v in at.EVENT_TABLE.items():
        _check(-100 <= v["delta"] <= 100 and v["delta"] != 0, f"事件 {k} 修正量非法")
        _check(bool(v["desc"]), f"事件 {k} 缺描述")


def test_decay():
    _check(at.decay(0) == 0, "0 不漂移")
    _check(at.decay(5) == 4, "小正值向 0 移 1")
    _check(at.decay(-5) == -4, "小负值向 0 移 1")
    _check(at.decay(100) == 98, "大值快消（步长 2）")
    _check(at.decay(40) == 39, "边界值向 0")
    _check(at.decay(39) == 38, "中性区向 0")
    _check(abs(at.decay(90)) < abs(90), "绝不反向")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("all passed")


if __name__ == "__main__":
    main()
