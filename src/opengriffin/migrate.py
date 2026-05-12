"""Migration tools — import state from Hermes Agent or OpenClaw.

Usage:
  griffin migrate from-hermes   [--src ~/.hermes]
  griffin migrate from-openclaw [--src ~/.openclaw]

What gets ported:

From Hermes (~/.hermes/):
  memories/MEMORY.md, USER.md, SOUL.md  → ~/.opengriffin/memories/*
  cron/jobs.json                        → ~/.opengriffin/jobs.json (translated)
  channel_directory.json                → identity.json platforms
  state.db (SQLite)                     → message previews into echo memory `recent` tier
  scripts/                              → ~/.opengriffin/scripts/

From OpenClaw (~/.openclaw/):
  memory.md / memories/                 → ~/.opengriffin/memories/MEMORY.md (merged)
  config.{yaml,toml}                    → reported only (manual review)
  any *.skill.md files                  → ~/.claude/skills/<name>/SKILL.md
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path

import typer

from . import echo_memory  # type: ignore — package-relative

app = typer.Typer(name="migrate", help="Import from Hermes or OpenClaw")


def _say(msg: str) -> None:
    print(f"  • {msg}")


# ----------------------------- Hermes -----------------------------


def _port_hermes_memories(src: Path, dst_dir: Path) -> int:
    n = 0
    for fname in ("MEMORY.md", "USER.md", "SOUL.md"):
        s = src / "memories" / fname
        if s.is_file():
            target = dst_dir / fname
            if target.is_file():
                # Merge: append Hermes content as a separator block
                target.write_text(
                    target.read_text()
                    + f"\n\n§\n\n# Imported from Hermes {dt.date.today()}\n\n"
                    + s.read_text()
                )
            else:
                shutil.copy2(s, target)
            _say(f"memories/{fname}")
            n += 1
    return n


def _port_hermes_cron(src: Path, dst: Path) -> int:
    s = src / "cron" / "jobs.json"
    if not s.is_file():
        return 0
    try:
        data = json.loads(s.read_text())
    except Exception:
        return 0
    # Hermes job schema → OpenGriffin schema
    out_jobs = []
    for j in data.get("jobs", []):
        if not j.get("enabled", True):
            continue
        sched = j.get("schedule", {})
        expr = sched.get("expr") or sched.get("display") if isinstance(sched, dict) else sched
        if not expr:
            continue
        deliver_to = ""
        origin = j.get("origin")
        if isinstance(origin, dict) and origin.get("platform") == "telegram":
            deliver_to = origin.get("chat_id", "")
        out_jobs.append(
            {
                "id": j.get("id", "imported-" + str(len(out_jobs))),
                "name": j.get("name", "(imported)"),
                "schedule": expr,
                "enabled": True,
                "deliver_to": deliver_to,
                "prompt": j.get("prompt", ""),
            }
        )
    if not out_jobs:
        return 0
    if dst.is_file():
        try:
            existing = json.loads(dst.read_text())
            existing.setdefault("jobs", []).extend(out_jobs)
            dst.write_text(json.dumps(existing, indent=2) + "\n")
        except Exception:
            dst.write_text(json.dumps({"jobs": out_jobs}, indent=2) + "\n")
    else:
        dst.write_text(json.dumps({"jobs": out_jobs}, indent=2) + "\n")
    _say(f"{len(out_jobs)} cron jobs")
    return len(out_jobs)


def _port_hermes_channels(src: Path) -> int:
    s = src / "channel_directory.json"
    if not s.is_file():
        return 0
    try:
        data = json.loads(s.read_text())
    except Exception:
        return 0
    n = 0
    try:
        from . import identity  # type: ignore
    except Exception:
        return 0
    handle = "imported"
    identity.create_account(handle)
    for platform, contacts in (data.get("platforms") or {}).items():
        for c in contacts:
            cid = c.get("id") or c.get("chat_id")
            if cid:
                identity.link_platform(handle, platform, str(cid))
                n += 1
    if n:
        _say(f"linked {n} platform handles to identity 'imported'")
    return n


def _port_hermes_sessions(src: Path, max_msgs: int = 50) -> int:
    """Pull recent message previews from Hermes' SQLite into echo memory."""
    db = src / "state.db"
    if not db.is_file():
        return 0
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = conn.execute(
            "SELECT timestamp, role, substr(content, 1, 200) FROM messages "
            "WHERE role='user' ORDER BY timestamp DESC LIMIT ?",
            (max_msgs,),
        )
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return 0
    n = 0
    for ts, _role, content in rows:
        if not content:
            continue
        echo_memory.write("recent", f"[hermes import @ {ts}] {content}", key=str(ts)[:10])
        n += 1
    if n:
        _say(f"imported {n} message previews → echo memory 'recent'")
    return n


def _port_hermes_scripts(src: Path) -> int:
    s = src / "scripts"
    if not s.is_dir():
        return 0
    dst = Path.home() / ".opengriffin" / "scripts"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in s.glob("*.py"):
        target = dst / f.name
        if not target.exists():
            shutil.copy2(f, target)
            n += 1
    if n:
        _say(f"copied {n} scripts")
    return n


@app.command("from-hermes")
def from_hermes(
    src: str = typer.Option(str(Path.home() / ".hermes"), help="Hermes home directory"),
):
    """Import memories, cron jobs, channels, scripts, and recent sessions from Hermes."""
    src_path = Path(src)
    if not src_path.is_dir():
        typer.echo(f"✗ {src_path} not found")
        raise typer.Exit(1)
    dst_mem = Path.home() / ".opengriffin" / "memories"
    dst_mem.mkdir(parents=True, exist_ok=True)
    dst_jobs = Path.home() / ".opengriffin" / "jobs.json"
    typer.echo(f"📦 Importing from Hermes at {src_path}")
    _port_hermes_memories(src_path, dst_mem)
    _port_hermes_cron(src_path, dst_jobs)
    _port_hermes_channels(src_path)
    _port_hermes_sessions(src_path)
    _port_hermes_scripts(src_path)
    typer.echo("✓ Hermes import done")


# ----------------------------- OpenClaw -----------------------------


def _port_openclaw_memory(src: Path, dst: Path) -> int:
    """OpenClaw stores memory as a single markdown file or under memories/."""
    candidates = [src / "memory.md", src / "memories" / "MEMORY.md"]
    found = None
    for c in candidates:
        if c.is_file():
            found = c
            break
    if found is None:
        return 0
    if dst.is_file():
        dst.write_text(
            dst.read_text()
            + f"\n\n§\n\n# Imported from OpenClaw {dt.date.today()}\n\n"
            + found.read_text()
        )
    else:
        shutil.copy2(found, dst)
    _say(f"memory from {found}")
    return 1


def _port_openclaw_skills(src: Path) -> int:
    """OpenClaw skills sometimes live as *.skill.md files."""
    skills_dst = Path.home() / ".claude" / "skills"
    skills_dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in src.rglob("*.skill.md"):
        name = f.stem.replace(".skill", "")
        dst_dir = skills_dst / name
        if dst_dir.exists():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        # Add Apache-2.0 frontmatter if not present
        text = f.read_text()
        if not text.startswith("---"):
            text = (
                f"---\nname: {name}\ndescription: (imported from OpenClaw)\nlicense: imported\n---\n\n"
                + text
            )
        (dst_dir / "SKILL.md").write_text(text)
        n += 1
    if n:
        _say(f"imported {n} skills from OpenClaw")
    return n


def _port_openclaw_config(src: Path) -> None:
    for fname in ("config.yaml", "config.toml", "config.json", "openclaw.yaml"):
        f = src / fname
        if f.is_file():
            target = Path.home() / ".opengriffin" / f"openclaw.{fname.split('.')[-1]}.imported"
            shutil.copy2(f, target)
            _say(f"config saved to {target} for manual review")


@app.command("from-openclaw")
def from_openclaw(
    src: str = typer.Option(str(Path.home() / ".openclaw"), help="OpenClaw home directory"),
):
    """Import memory + skills + config from OpenClaw."""
    src_path = Path(src)
    if not src_path.is_dir():
        typer.echo(f"✗ {src_path} not found")
        raise typer.Exit(1)
    dst_mem = Path.home() / ".opengriffin" / "memories" / "MEMORY.md"
    dst_mem.parent.mkdir(parents=True, exist_ok=True)
    typer.echo(f"📦 Importing from OpenClaw at {src_path}")
    _port_openclaw_memory(src_path, dst_mem)
    _port_openclaw_skills(src_path)
    _port_openclaw_config(src_path)
    typer.echo("✓ OpenClaw import done")


if __name__ == "__main__":
    app()
