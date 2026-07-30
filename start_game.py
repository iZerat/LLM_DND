import sys
import io
import subprocess
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
VENV_DIR = BASE_DIR / "venv"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
VENV_PIP = VENV_DIR / "Scripts" / "pip.exe"
REQUIREMENTS = BASE_DIR / "requirements.txt"


def _is_venv():
    return sys.executable.startswith(str(VENV_DIR))


def _re_execute():
    cmd = [str(VENV_PYTHON), str(__file__)]
    try:
        proc = subprocess.run(cmd)
        sys.exit(proc.returncode)
    except Exception as e:
        print(f"无法使用 venv Python 启动: {e}")
        sys.exit(1)


def _check_deps():
    try:
        from rich.panel import Panel
        return True
    except ImportError:
        return False


def _venv_has_deps():
    try:
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", "from rich.panel import Panel"],
            capture_output=True, timeout=5)
        return proc.returncode == 0
    except:
        return False


def _ask(prompt):
    try:
        ans = input(prompt).strip().lower()
        return ans in ("y", "yes", "是", "")
    except (EOFError, KeyboardInterrupt):
        return False


def _install_deps():
    print("\n正在安装依赖（可能需要几分钟）...")
    proc = subprocess.run(
        [str(VENV_PIP), "install", "-r", str(REQUIREMENTS),
         "--trusted-host", "pypi.org",
         "--trusted-host", "files.pythonhosted.org"],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        print(f"安装失败:\n{proc.stderr}")
        return False
    print("依赖安装完成！")
    return True


def _create_venv():
    print("正在创建虚拟环境...")
    proc = subprocess.run(
        [sys.executable, "-m", "venv", str(VENV_DIR)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"创建虚拟环境失败:\n{proc.stderr}")
        return False
    print("虚拟环境创建成功！")
    return True


def _launch():
    from core.main import main
    try:
        main()
    except KeyboardInterrupt:
        try:
            from core.ui import console
            console.print("\n[yellow]再见！[/yellow]")
        except ImportError:
            print("\n再见！")
        sys.exit(0)


def bootstrap():
    if _is_venv():
        if _check_deps():
            _launch()
            return
        print("依赖未安装。")
        if _ask("是否安装依赖？（y/n）: "):
            if _install_deps():
                _launch()
                return
        sys.exit(1)

    if VENV_PYTHON.exists():
        if _venv_has_deps():
            _re_execute()
            return
        print("虚拟环境存在但依赖未安装。")
        if _ask("是否安装依赖？（y/n）: "):
            if _install_deps():
                _re_execute()
                return
        sys.exit(1)

    print("检测到未使用虚拟环境。是否创建并安装依赖？")
    if not _ask("一键配置环境并启动游戏？（y/n）: "):
        print("已取消。请手动创建 venv 后执行: python start_game.py")
        sys.exit(1)

    if not _create_venv():
        sys.exit(1)
    if not _install_deps():
        sys.exit(1)
    _re_execute()


if __name__ == "__main__":
    bootstrap()
