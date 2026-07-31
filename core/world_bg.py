from pathlib import Path

WORLD_BACKGROUNDS_DIR = Path(__file__).resolve().parent.parent / "world_backgrounds"


def list_world_backgrounds() -> list[tuple[str, str]]:
    """Return [(display_name, file_stem), ...] for all .txt in world_backgrounds/"""
    if not WORLD_BACKGROUNDS_DIR.exists():
        WORLD_BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)
    found = sorted(WORLD_BACKGROUNDS_DIR.glob("*.txt"))
    result = []
    for fp in found:
        display = fp.stem.replace("-", " ").replace("_", " ").title().replace("Dnd", "DND")
        result.append((display, fp.stem))
    return result


def load_world_background(stem: str) -> str:
    """Load the content of a world background file by its stem (no extension)."""
    fp = WORLD_BACKGROUNDS_DIR / f"{stem}.txt"
    if not fp.exists():
        return ""
    return fp.read_text(encoding="utf-8").strip()
