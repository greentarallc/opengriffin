"""In-process MCP tools the agent calls via SDK.

All tools registered into a single SDK MCP server (`bot_tools`). Tools rely on
`botctx.CTX` for bot/scheduler access, so the bot context must be set before
any tool runs.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Annotated, Any

import requests
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from claude_agent_sdk import create_sdk_mcp_server, tool

from . import cron as cron_module
from .botctx import CTX

JOBS_FILE = cron_module.JOBS_FILE
SKILLS_DIR = Path.home() / ".claude" / "skills"

# ----------------------- helpers -----------------------


def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _err(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def _load_jobs_raw() -> dict:
    if JOBS_FILE.exists():
        return json.loads(JOBS_FILE.read_text())
    return {"jobs": []}


def _save_jobs_raw(data: dict) -> None:
    JOBS_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _parse_schedule(spec: str) -> tuple[str, Any]:
    """Parse a schedule spec into (kind, trigger).

    Accepts:
      - cron: "0 9 * * *", "*/15 * * * *", etc. (5 fields)
      - interval: "every 30m", "every 2h", "every 1d"
      - relative: "30m", "2h", "1d" (one-shot from now)
      - ISO: "2026-05-06T15:00:00" (one-shot)
    """
    spec = spec.strip()
    if spec.startswith("every "):
        rest = spec[len("every ") :].strip()
        m = re.fullmatch(r"(\d+)([smhdw])", rest)
        if not m:
            raise ValueError(f"interval format must be 'every <N><s|m|h|d|w>': {rest}")
        n, u = int(m.group(1)), m.group(2)
        kw = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[u]
        return "interval", IntervalTrigger(**{kw: n})
    if re.fullmatch(r"\d+[smhdw]", spec):
        n, u = int(spec[:-1]), spec[-1]
        kw = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[u]
        import datetime as dt

        return "date", DateTrigger(run_date=dt.datetime.now() + dt.timedelta(**{kw: n}))
    if "T" in spec and re.match(r"^\d{4}-\d{2}-\d{2}T", spec):
        import datetime as dt

        return "date", DateTrigger(run_date=dt.datetime.fromisoformat(spec))
    return "cron", CronTrigger.from_crontab(spec)


# ----------------------- cron job tools -----------------------


@tool(
    "cronjob_list",
    "List all scheduled cron jobs with their schedule and next run time.",
    {},
)
async def _cron_list(args: dict) -> dict:
    sched = CTX.scheduler
    if sched is None:
        return _err("scheduler not running")
    lines = []
    for j in sched.get_jobs():
        nxt = j.next_run_time.isoformat() if j.next_run_time else "—"
        lines.append(f"{j.id} | {j.name} | next: {nxt}")
    return _ok("\n".join(lines) if lines else "(no jobs scheduled)")


@tool(
    "cronjob_create",
    "Create a new scheduled cron job. Schedule accepts cron ('0 9 * * *'), interval ('every 30m'), relative ('30m' for one-shot from now), or ISO timestamp.",
    {
        "id": Annotated[str, "Unique job id (kebab-case)"],
        "name": Annotated[str, "Human-readable name"],
        "schedule": Annotated[str, "Cron expr / 'every Nm/h/d' / relative / ISO"],
        "prompt": Annotated[str, "The prompt for Claude when the job fires"],
        "deliver_to": Annotated[
            str,
            "Telegram chat_id to deliver result. Pass 'home' for the configured home chat.",
        ],
        "pre_script": Annotated[
            str | None, "Optional path to a Python script run before the prompt (output prepended)"
        ],
    },
)
async def _cron_create(args: dict) -> dict:
    data = _load_jobs_raw()
    if any(j["id"] == args["id"] for j in data["jobs"]):
        return _err(f"job id already exists: {args['id']}")
    deliver = args["deliver_to"]
    if deliver == "home":
        deliver = CTX.home_chat_id or ""
    new = {
        "id": args["id"],
        "name": args["name"],
        "schedule": args["schedule"],
        "enabled": True,
        "deliver_to": deliver,
        "prompt": args["prompt"],
    }
    if args.get("pre_script"):
        new["pre_script"] = args["pre_script"]
    data["jobs"].append(new)
    _save_jobs_raw(data)

    sched = CTX.scheduler
    if sched is not None and CTX.bot is not None:
        try:
            _, trigger = _parse_schedule(args["schedule"])
        except Exception as e:
            return _err(f"saved to jobs.json but schedule invalid: {e}")
        job = cron_module.Job(
            id=new["id"],
            name=new["name"],
            schedule=new["schedule"],
            deliver_to=str(new["deliver_to"]),
            prompt=new["prompt"],
            enabled=True,
            pre_script=new.get("pre_script"),
        )
        sched.add_job(
            cron_module.run_job,
            trigger=trigger,
            args=[job, CTX.bot],
            id=job.id,
            name=job.name,
            misfire_grace_time=600,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
    return _ok(f"created job {args['id']} on schedule '{args['schedule']}'")


@tool(
    "cronjob_remove",
    "Delete a scheduled job by id.",
    {"id": Annotated[str, "Job id to remove"]},
)
async def _cron_remove(args: dict) -> dict:
    data = _load_jobs_raw()
    before = len(data["jobs"])
    data["jobs"] = [j for j in data["jobs"] if j["id"] != args["id"]]
    if len(data["jobs"]) == before:
        return _err(f"job not found: {args['id']}")
    _save_jobs_raw(data)
    if CTX.scheduler is not None:
        with contextlib.suppress(Exception):
            CTX.scheduler.remove_job(args["id"])
    return _ok(f"removed job {args['id']}")


@tool(
    "cronjob_pause",
    "Pause a job (keeps definition, suspends triggers).",
    {"id": Annotated[str, "Job id to pause"]},
)
async def _cron_pause(args: dict) -> dict:
    data = _load_jobs_raw()
    for j in data["jobs"]:
        if j["id"] == args["id"]:
            j["enabled"] = False
            _save_jobs_raw(data)
            if CTX.scheduler is not None:
                with contextlib.suppress(Exception):
                    CTX.scheduler.pause_job(args["id"])
            return _ok(f"paused {args['id']}")
    return _err(f"job not found: {args['id']}")


@tool(
    "cronjob_resume",
    "Resume a paused job.",
    {"id": Annotated[str, "Job id to resume"]},
)
async def _cron_resume(args: dict) -> dict:
    data = _load_jobs_raw()
    for j in data["jobs"]:
        if j["id"] == args["id"]:
            j["enabled"] = True
            _save_jobs_raw(data)
            if CTX.scheduler is not None:
                with contextlib.suppress(Exception):
                    CTX.scheduler.resume_job(args["id"])
            return _ok(f"resumed {args['id']}")
    return _err(f"job not found: {args['id']}")


@tool(
    "cronjob_run_now",
    "Run a scheduled job immediately, in addition to its normal schedule.",
    {"id": Annotated[str, "Job id to run"]},
)
async def _cron_run_now(args: dict) -> dict:
    jobs = cron_module.load_jobs()
    job = next((j for j in jobs if j.id == args["id"]), None)
    if job is None:
        return _err(f"job not found: {args['id']}")
    if CTX.bot is None:
        return _err("bot not ready")
    import asyncio

    asyncio.create_task(cron_module.run_job(job, CTX.bot))
    return _ok(f"running {job.id} now (will deliver to {job.deliver_to})")


# ----------------------- cross-chat send -----------------------


@tool(
    "send_message",
    "Send a message to any Telegram chat by id. Useful for fan-out, alerting other chats, or scheduling deferred deliveries from one chat into another.",
    {
        "chat_id": Annotated[
            str, "Telegram chat id (numeric). Pass 'home' for the configured home chat."
        ],
        "text": Annotated[str, "Message text (markdown)"],
    },
)
async def _send_message(args: dict) -> dict:
    if CTX.bot is None:
        return _err("bot not ready")
    chat_id = args["chat_id"]
    if chat_id == "home":
        chat_id = CTX.home_chat_id or ""
    if not chat_id:
        return _err("no chat_id (and no home chat configured)")
    try:
        await CTX.bot.send_message(chat_id=chat_id, text=args["text"])
    except Exception as e:
        return _err(f"send failed: {e}")
    return _ok(f"sent to {chat_id}")


# ----------------------- skill management -----------------------


_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")


def _skill_path(name: str) -> Path:
    if not _SKILL_NAME_RE.match(name):
        raise ValueError(f"invalid skill name (lowercase, hyphens, 2-64 chars): {name}")
    return SKILLS_DIR / name


@tool(
    "skill_create",
    "Create a new user-level skill at ~/.claude/skills/<name>/SKILL.md. Skills are auto-discovered by Claude in future sessions.",
    {
        "name": Annotated[str, "Skill directory name (lowercase, hyphens)"],
        "description": Annotated[str, "One-line description used for auto-invocation"],
        "body": Annotated[str, "Markdown body of the skill (instructions for Claude)"],
    },
)
async def _skill_create(args: dict) -> dict:
    try:
        path = _skill_path(args["name"])
    except ValueError as e:
        return _err(str(e))
    if path.exists():
        return _err(f"skill already exists: {args['name']}")
    path.mkdir(parents=True)
    skill_md = (
        "---\n"
        f"name: {args['name']}\n"
        f"description: {args['description']}\n"
        "---\n\n"
        f"{args['body'].strip()}\n"
    )
    (path / "SKILL.md").write_text(skill_md)
    return _ok(f"created skill at {path}")


@tool(
    "skill_edit",
    "Replace the SKILL.md body for an existing skill (preserves frontmatter unless overridden).",
    {
        "name": Annotated[str, "Skill name"],
        "body": Annotated[str, "New markdown body"],
        "description": Annotated[str | None, "If set, also update the frontmatter description"],
    },
)
async def _skill_edit(args: dict) -> dict:
    try:
        path = _skill_path(args["name"]) / "SKILL.md"
    except ValueError as e:
        return _err(str(e))
    if not path.is_file():
        return _err(f"skill not found: {args['name']}")
    text = path.read_text()
    fm_match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    fm = fm_match.group(1) if fm_match else f"name: {args['name']}\ndescription: (no description)"
    if args.get("description"):
        fm = re.sub(
            r"^description:.*$",
            f"description: {args['description']}",
            fm,
            count=1,
            flags=re.MULTILINE,
        )
    new = f"---\n{fm}\n---\n\n{args['body'].strip()}\n"
    path.write_text(new)
    return _ok(f"updated skill {args['name']}")


@tool(
    "skill_delete",
    "Delete a user-level skill directory.",
    {"name": Annotated[str, "Skill name"]},
)
async def _skill_delete(args: dict) -> dict:
    try:
        path = _skill_path(args["name"])
    except ValueError as e:
        return _err(str(e))
    if not path.is_dir():
        return _err(f"skill not found: {args['name']}")
    shutil.rmtree(path)
    return _ok(f"deleted skill {args['name']}")


@tool(
    "skill_list",
    "List all user-level skills available at ~/.claude/skills/.",
    {},
)
async def _skill_list(args: dict) -> dict:
    if not SKILLS_DIR.is_dir():
        return _ok("(no skills directory)")
    entries = []
    for p in sorted(SKILLS_DIR.iterdir()):
        if (p / "SKILL.md").is_file():
            text = (p / "SKILL.md").read_text()
            m = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
            desc = m.group(1).strip() if m else ""
            entries.append(f"{p.name} — {desc}")
    return _ok("\n".join(entries) if entries else "(no skills)")


# ----------------------- image generation -----------------------


@tool(
    "image_generate",
    "Generate an image via FAL.ai. Requires FAL_KEY env var. Returns a URL to the generated image (download with curl/requests if needed).",
    {
        "prompt": Annotated[str, "Image description"],
        "model": Annotated[
            str | None,
            "FAL model slug; defaults to fal-ai/flux/schnell (fast, free-tier-friendly)",
        ],
    },
)
async def _image_generate(args: dict) -> dict:
    key = os.environ.get("FAL_KEY")
    if not key:
        return _err("FAL_KEY not set in env. Add to ~/.opengriffin/.env to use image generation.")
    model = args.get("model") or "fal-ai/flux/schnell"
    url = f"https://fal.run/{model}"
    try:
        r = requests.post(
            url,
            json={"prompt": args["prompt"]},
            headers={"Authorization": f"Key {key}"},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return _err(f"FAL request failed: {e}")
    images = data.get("images") or []
    if not images:
        return _err(f"no images returned: {json.dumps(data)[:300]}")
    return _ok(f"generated: {images[0].get('url', images[0])}")


# ----------------------- server export -----------------------


# ----------------------- journal -----------------------


@tool(
    "journal_append",
    "Append a structured entry to the bot's daily journal (~/.opengriffin/memories/JOURNAL.md). Used by the daily self-improvement turn. Pass the full markdown entry including the '## YYYY-MM-DD' header.",
    {"entry": Annotated[str, "Markdown entry, including its own '## date' header"]},
)
async def _journal_append(args: dict) -> dict:
    from . import self_improve

    try:
        self_improve.append_journal_entry(args["entry"])
    except Exception as e:
        return _err(f"journal write failed: {e}")
    return _ok("journal entry appended")


_TOOLS = [
    _cron_list,
    _cron_create,
    _cron_remove,
    _cron_pause,
    _cron_resume,
    _cron_run_now,
    _send_message,
    _skill_create,
    _skill_edit,
    _skill_delete,
    _skill_list,
    _image_generate,
    _journal_append,
]


BOT_TOOLS_SERVER = create_sdk_mcp_server(
    name="bot_tools",
    version="1.0.0",
    tools=_TOOLS,
)
