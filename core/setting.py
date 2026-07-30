from pathlib import Path

SETTINGS_DIR = Path(__file__).resolve().parent.parent / "settings"


def list_settings() -> list[tuple[str, str]]:
    """Return [(display_name, file_stem), ...] for all .txt in settings/"""
    if not SETTINGS_DIR.exists():
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    found = sorted(SETTINGS_DIR.glob("*.txt"))
    result = []
    for fp in found:
        display = fp.stem.replace("-", " ").replace("_", " ").title()
        result.append((display, fp.stem))
    return result


def load_setting(stem: str) -> str:
    """Load the content of a setting file by its stem (no extension)."""
    fp = SETTINGS_DIR / f"{stem}.txt"
    if not fp.exists():
        return ""
    return fp.read_text(encoding="utf-8").strip()
