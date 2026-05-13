"""Canonical filesystem layout for OpenGriffin.

Every module that touches persistent state reads its location from this
module so the layout can be relocated by setting `OPENGRIFFIN_HOME` in
the environment. Default home is `~/.opengriffin/`.

Public API:
  OG_HOME    — root for all runtime state (env, memory, sessions, etc.)
  ENV_FILE   — primary .env path (loaded by bot.py at startup)
  MEM_DIR    — MEMORY / USER / SOUL / JOURNAL / VOICE
  SESSIONS   — sessions.json
  KANBAN     — kanban.json
  ALIASES    — aliases.json
  USAGE_LOG  — usage.jsonl
  WEBHOOKS   — webhooks.json
  CHECKPOINTS — checkpoints/
  SKILLS_DIR — ~/.claude/skills (Claude Code skill graph; not under OG_HOME)

A one-time `migrate_legacy_state()` function is also exposed; bot.py calls
it at startup so users with state in the older `~/claude-bot/` layout get
auto-migrated. The migrator is idempotent and never overwrites existing
files at the new location.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger("opengriffin.paths")

OG_HOME = Path(os.environ.get("OPENGRIFFIN_HOME") or str(Path.home() / ".opengriffin")).expanduser()
OG_HOME.mkdir(parents=True, exist_ok=True)

ENV_FILE = OG_HOME / ".env"
MEM_DIR = OG_HOME / "memories"
MEM_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS = OG_HOME / "sessions.json"
KANBAN = OG_HOME / "kanban.json"
ALIASES = OG_HOME / "aliases.json"
USAGE_LOG = OG_HOME / "usage.jsonl"
WEBHOOKS = OG_HOME / "webhooks.json"
CHECKPOINTS = OG_HOME / "checkpoints"
CHECKPOINTS.mkdir(parents=True, exist_ok=True)

# Claude Code skill graph lives outside OG_HOME — that's intentional. Skills
# are shared across the user's Claude Code installs and any agent that
# embeds the SDK.
SKILLS_DIR = Path.home() / ".claude" / "skills"

# Memory file convenience handles (callers can still build their own paths).
MEMORY_FILE = MEM_DIR / "MEMORY.md"
USER_FILE = MEM_DIR / "USER.md"
SOUL_FILE = MEM_DIR / "SOUL.md"
JOURNAL_FILE = MEM_DIR / "JOURNAL.md"
VOICE_FILE = MEM_DIR / "VOICE.md"
CONSTRAINTS_FILE = MEM_DIR / "CONSTRAINTS.md"


_LEGACY_HOME = Path.home() / "claude-bot"


def migrate_legacy_state(*, verbose: bool = False) -> dict:
    """Move state out of `~/claude-bot/` into OG_HOME if it exists there.

    Idempotent. Skips any file/dir that already exists at the destination
    so re-runs are safe and never overwrite live state. Returns a dict
    summarising what (if anything) was moved.

    The legacy root itself is NOT deleted — the user removes it once
    they've verified the migration is clean. Surface that hint in the bot
    boot log via the returned summary.
    """
    moved: list[tuple[str, str]] = []
    skipped: list[str] = []

    if not _LEGACY_HOME.is_dir():
        return {"migrated": False, "reason": "no legacy layout present"}

    # .env — copy, don't move. The file is small and the user may want
    # to keep a backup at the legacy location until they're confident.
    legacy_env = _LEGACY_HOME / ".env"
    if legacy_env.is_file():
        if ENV_FILE.exists():
            skipped.append(f"{legacy_env} (target exists)")
        else:
            shutil.copy2(legacy_env, ENV_FILE)
            ENV_FILE.chmod(0o600)
            moved.append((str(legacy_env), str(ENV_FILE)))

    # memories/ — copy each file individually so partial migrations are
    # recoverable. We do NOT remove the source.
    legacy_mem = _LEGACY_HOME / "memories"
    if legacy_mem.is_dir():
        for src in legacy_mem.iterdir():
            if src.is_file():
                dst = MEM_DIR / src.name
                if dst.exists():
                    skipped.append(f"{src} (target exists)")
                else:
                    shutil.copy2(src, dst)
                    moved.append((str(src), str(dst)))
            elif src.is_dir():
                dst = MEM_DIR / src.name
                if dst.exists():
                    skipped.append(f"{src} (target exists)")
                else:
                    shutil.copytree(src, dst)
                    moved.append((str(src) + "/", str(dst) + "/"))

    # Per-deployment state files — sessions, scheduled jobs, kanban board,
    # aliases, dead-man's switch state, usage log, webhook routes. Copy
    # one-by-one so existing state at the destination wins.
    for fname in (
        "sessions.json",
        "kanban.json",
        "aliases.json",
        "jobs.json",
        "deadman.json",
        "usage.jsonl",
        "webhooks.json",
    ):
        src = _LEGACY_HOME / fname
        dst = OG_HOME / fname
        if not src.is_file():
            continue
        if dst.exists():
            skipped.append(f"{src} (target exists)")
            continue
        shutil.copy2(src, dst)
        moved.append((str(src), str(dst)))

    # Runtime subdirs created by various modules. Each is copied wholesale
    # if the target doesn't already exist.
    for dname in (
        "agents",
        "checkpoints",
        "predictions",
        "skill_proposals",
        "workers",
        "scripts",
    ):
        src = _LEGACY_HOME / dname
        dst = OG_HOME / dname
        if not src.is_dir():
            continue
        if dst.exists() and any(dst.iterdir()):
            skipped.append(f"{src}/ (target non-empty)")
            continue
        if dst.exists():
            dst.rmdir()  # empty placeholder created by another module
        shutil.copytree(src, dst)
        moved.append((str(src) + "/", str(dst) + "/"))

    if moved and verbose:
        for src, dst in moved:
            log.info("paths.migrate: %s → %s", src, dst)
    if skipped and verbose:
        for s in skipped:
            log.info("paths.migrate: skipped %s", s)

    return {
        "migrated": bool(moved),
        "moved": moved,
        "skipped": skipped,
        "legacy_root_still_present": _LEGACY_HOME.is_dir(),
        "hint": (
            f"Migration copied {len(moved)} item(s). Once you've verified "
            f"the bot works against {OG_HOME}, delete the legacy root: "
            f"rm -rf {_LEGACY_HOME}"
            if moved
            else None
        ),
    }


__all__ = [
    "OG_HOME",
    "ENV_FILE",
    "MEM_DIR",
    "SESSIONS",
    "KANBAN",
    "ALIASES",
    "USAGE_LOG",
    "WEBHOOKS",
    "CHECKPOINTS",
    "SKILLS_DIR",
    "MEMORY_FILE",
    "USER_FILE",
    "SOUL_FILE",
    "JOURNAL_FILE",
    "VOICE_FILE",
    "CONSTRAINTS_FILE",
    "migrate_legacy_state",
]
