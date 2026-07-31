from pathlib import Path

OPENING_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "opening_templates"


def list_opening_templates() -> list[tuple[str, str]]:
    """Return [(display_name, file_stem), ...] for all .txt in opening_templates/"""
    if not OPENING_TEMPLATES_DIR.exists():
        OPENING_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    found = sorted(OPENING_TEMPLATES_DIR.glob("*.txt"))
    result = []
    for fp in found:
        display = fp.stem.replace("-", " ").replace("_", " ").title().replace("Dnd", "DND")
        result.append((display, fp.stem))
    return result


def load_opening_template(stem: str) -> str:
    """Load the content of an opening template file by its stem (no extension)."""
    fp = OPENING_TEMPLATES_DIR / f"{stem}.txt"
    if not fp.exists():
        return ""
    return fp.read_text(encoding="utf-8").strip()
