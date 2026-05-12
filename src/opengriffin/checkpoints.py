"""File checkpoint / rollback.

Before Claude calls Write/Edit on a file, we snapshot the existing file (if
any) into ~/.opengriffin/checkpoints/<timestamp>/<original_path_safe>. The
`/rollback` Telegram command restores from the most recent snapshot set.
"""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path
from typing import Any

from claude_agent_sdk import HookMatcher

CHECKPOINT_ROOT = Path(__file__).resolve().parent / "checkpoints"
WATCHED_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def _now_dir() -> Path:
    return CHECKPOINT_ROOT / dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _safe_relpath(p: Path) -> str:
    s = str(p).replace("/", "_").replace(":", "_").replace("\\", "_")
    return s.lstrip("_") or "root"


async def pre_tool_use_hook(
    input_data: dict[str, Any], tool_use_id: str | None, context: Any
) -> dict[str, Any]:
    """Snapshot files before Write/Edit/MultiEdit fires."""
    tool_name = input_data.get("tool_name", "")
    if tool_name not in WATCHED_TOOLS:
        return {}
    tool_input = input_data.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return {}
    p = Path(file_path)
    if not p.is_file():
        return {}
    try:
        snap_dir = _now_dir()
        snap_dir.mkdir(parents=True, exist_ok=True)
        dest = snap_dir / _safe_relpath(p)
        shutil.copy2(p, dest)
        marker = snap_dir / "ORIGIN.txt"
        marker.write_text(f"{file_path}\n{tool_name}\n{tool_use_id or ''}\n")
    except Exception:
        pass  # never block tool use over a snapshot failure
    return {}


def list_checkpoints(limit: int = 20) -> list[Path]:
    if not CHECKPOINT_ROOT.is_dir():
        return []
    dirs = sorted(
        (p for p in CHECKPOINT_ROOT.iterdir() if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    return dirs[:limit]


def rollback_latest() -> tuple[bool, str]:
    """Restore files from the most recent checkpoint set. Returns (ok, message)."""
    snaps = list_checkpoints(limit=1)
    if not snaps:
        return False, "no checkpoints"
    snap_dir = snaps[0]
    origin = snap_dir / "ORIGIN.txt"
    restored: list[str] = []
    failed: list[str] = []
    if origin.is_file():
        # single-file checkpoint
        original_path = origin.read_text().splitlines()[0]
        for f in snap_dir.iterdir():
            if f.name == "ORIGIN.txt":
                continue
            try:
                shutil.copy2(f, original_path)
                restored.append(original_path)
            except Exception as e:
                failed.append(f"{original_path}: {e}")
    msg = f"restored {len(restored)} file(s) from {snap_dir.name}"
    if failed:
        msg += f"\nfailed: {failed}"
    return True, msg


HOOKS_SPEC = {
    "PreToolUse": [
        HookMatcher(matcher="Write|Edit|MultiEdit|NotebookEdit", hooks=[pre_tool_use_hook])
    ],
}
