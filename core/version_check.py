"""启动时检查游戏是否有新版本（对比本地 HEAD 与远程）。

仅回答「是否有更新」，不检测本地未提交变更、不显示本地 commit、不自动拉取。
约束：
- 无 git / 非 git 目录 / 无网络 / 无上游分支 → 返回 None，调用方静默跳过。
- `git fetch` 仅更新 remote-tracking refs，不改动工作区；超时被终止。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _run(cmd, timeout):
    return subprocess.run(
        cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=timeout)


def check_update(timeout=8):
    """返回状态 dict；失败返回 None。

    {"status": "up_to_date", "behind": 0, "remote_url": str}
    {"status": "update_available", "behind": int, "new_commit": str, "remote_url": str}
    """
    try:
        proc = _run(["git", "rev-parse", "--is-inside-work-tree"], timeout)
        if proc.returncode != 0 or proc.stdout.strip() != "true":
            return None

        proc = _run(["git", "fetch", "--quiet"], timeout)
        if proc.returncode != 0:
            return None

        proc = _run(["git", "rev-parse", "HEAD"], timeout)
        if proc.returncode != 0:
            return None
        local_sha = proc.stdout.strip()

        proc = _run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
            timeout)
        if proc.returncode != 0:
            return None
        upstream = proc.stdout.strip()

        remote_url = ""
        remote_name = upstream.split("/", 1)[0]
        proc = _run(["git", "remote", "get-url", remote_name], timeout)
        if proc.returncode == 0:
            remote_url = proc.stdout.strip()

        proc = _run(["git", "rev-parse", upstream], timeout)
        if proc.returncode != 0:
            return None
        remote_sha = proc.stdout.strip()

        if local_sha == remote_sha:
            return {"status": "up_to_date", "behind": 0, "remote_url": remote_url}

        proc = _run(["git", "rev-list", "--count", f"HEAD..{upstream}"], timeout)
        if proc.returncode != 0:
            return None
        behind = int(proc.stdout.strip() or "0")
        if behind <= 0:
            return {"status": "up_to_date", "behind": 0, "remote_url": remote_url}

        new_commit = ""
        proc = _run(["git", "log", "-1", "--format=%h %s", upstream], timeout)
        if proc.returncode == 0:
            new_commit = proc.stdout.strip()

        return {
            "status": "update_available",
            "behind": behind,
            "new_commit": new_commit,
            "remote_url": remote_url,
        }
    except Exception:
        return None
