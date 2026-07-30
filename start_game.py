import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from core.main import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        from core.ui import console
        console.print("\n[yellow]再见！[/yellow]")
        sys.exit(0)
