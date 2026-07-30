from __future__ import annotations
import json
from pathlib import Path

_LOCALE: str = "zh_CN"
_TABLE: dict[str, dict[str, str]] = {}  # ns -> {key -> text}
_LOC_DIR = Path(__file__).resolve().parent


def loc_init(locale: str = "zh_CN"):
    global _LOCALE, _TABLE
    _LOCALE = locale
    _TABLE.clear()
    fpath = _LOC_DIR / f"{locale}.json"
    if not fpath.exists():
        return
    raw = json.loads(fpath.read_text(encoding="utf-8"))
    for ns, entries in raw.items():
        _TABLE[ns] = entries


def tr(key: str, ns: str = "", default: str = "") -> str:
    if ns:
        full_ns = ns
    else:
        if ":" in key:
            ns_part, _, key_part = key.partition(":")
            full_ns = ns_part
            key = key_part
        else:
            full_ns = "general"
    ns_table = _TABLE.get(full_ns)
    if ns_table:
        val = ns_table.get(key)
        if val is not None:
            return val
    if ns_table and key in ns_table:
        return ns_table[key]
    return default if default else key


def T(key: str, ns: str = "", default: str = "") -> str:
    """Alias: translate with explicit namespace or 'ns:key' syntax."""
    return tr(key, ns, default)


def L(key: str, ns: str = "general") -> str:
    """Shorthand for common lookups within a namespace."""
    return tr(key, ns)


loc_init()
