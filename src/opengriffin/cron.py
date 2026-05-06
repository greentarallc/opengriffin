"""Cron-style scheduled jobs for the Telegram Claude bot.

Each job runs a Claude Agent SDK session on a cron schedule, with optional
pre-run script output prepended to the prompt, and delivers the result to a
Telegram chat. Final responses may include `MEDIA:/abs/path` lines — those
files are sent as Telegram media after the text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
)
from telegram import Bot
from telegram.constants import ParseMode

from . import memory as memory_module

log = logging.getLogger("opengriffin.cron")

BOT_DIR = Path(__file__).resolve().parent
JOBS_FILE = BOT_DIR / "jobs.json"
SCRIPTS_DIR = BOT_DIR / "scripts"

MEDIA_RE = re.compile(r"^MEDIA:(\S+)\s*$", re.MULTILINE)
TELEGRAM_MAX = 4000

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
AUDIO_EXTS = {".mp3", ".m4a", ".ogg", ".wav", ".opus"}


@dataclass
class Job:
    id: str
    name: str
    schedule: str
    deliver_to: str
    prompt: str
    enabled: bool = True
    pre_script: Optional[str] = None


def load_jobs() -> list[Job]:
    if not JOBS_FILE.exists():
        return []
    data = json.loads(JOBS_FILE.read_text())
    out: list[Job] = []
    for j in data.get("jobs", []):
        if not j.get("enabled", True):
            continue
        out.append(
            Job(
                id=j["id"],
                name=j["name"],
                schedule=j["schedule"],
                deliver_to=str(j["deliver_to"]),
                prompt=j["prompt"],
                enabled=j.get("enabled", True),
                pre_script=j.get("pre_script"),
            )
        )
    return out


def _run_pre_script(rel_path: str) -> str:
    path = (BOT_DIR / rel_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"pre_script not found: {path}")
    proc = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"pre_script {rel_path} exited {proc.returncode}: {proc.stderr.strip()[:500]}"
        )
    return proc.stdout


async def _run_claude(prompt: str, job_id: str | None = None) -> str:
    # Local imports avoid circular import with bot.py
    from . import bot as bot_module
    from . import usage as usage_module

    append_prompt = (
        "You are running as a scheduled cron job. Deliver the result "
        "directly. Keep text portions formatted for Telegram. To attach "
        "a media file, include a line like MEDIA:/absolute/path on its own.\n\n"
        + memory_module.render_system_block()
    )
    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": append_prompt,
        },
        permission_mode="bypassPermissions",
        skills="all",
        setting_sources=["user"],
        cwd=str(Path.home()),
        max_turns=200,
        mcp_servers=bot_module.build_mcp_servers(),
    )
    chunks: list[str] = []
    last_session = None
    cost = None
    in_tok = out_tok = None
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
            elif isinstance(msg, ResultMessage):
                last_session = msg.session_id
                cost = getattr(msg, "total_cost_usd", None)
                u = getattr(msg, "usage", None)
                if isinstance(u, dict):
                    in_tok = u.get("input_tokens")
                    out_tok = u.get("output_tokens")

    usage_module.record(
        chat_id=None,
        job_id=job_id,
        session_id=last_session,
        cost_usd=cost,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )
    return "".join(chunks).strip()


async def _send_to_telegram(bot: Bot, chat_id: str, text: str) -> None:
    media_paths = MEDIA_RE.findall(text)
    body = MEDIA_RE.sub("", text).strip()

    if body:
        for i in range(0, len(body), TELEGRAM_MAX):
            chunk = body[i : i + TELEGRAM_MAX]
            try:
                await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await bot.send_message(chat_id=chat_id, text=chunk)

    for raw in media_paths:
        p = Path(raw).expanduser()
        if not p.is_file():
            await bot.send_message(chat_id=chat_id, text=f"(missing media: {p})")
            continue
        ext = p.suffix.lower()
        try:
            with p.open("rb") as fh:
                if ext in VIDEO_EXTS:
                    await bot.send_video(chat_id=chat_id, video=fh, supports_streaming=True)
                elif ext in PHOTO_EXTS:
                    await bot.send_photo(chat_id=chat_id, photo=fh)
                elif ext in AUDIO_EXTS:
                    await bot.send_audio(chat_id=chat_id, audio=fh)
                else:
                    await bot.send_document(chat_id=chat_id, document=fh)
        except Exception as e:
            log.exception("Failed to send media %s", p)
            await bot.send_message(chat_id=chat_id, text=f"(media send failed for {p.name}: {e})")


async def run_job(job: Job, bot: Bot) -> None:
    log.info("Running job %s (%s)", job.id, job.name)
    silent = job.prompt.lstrip().startswith("[SILENT]")
    prompt = job.prompt.lstrip().removeprefix("[SILENT]").lstrip() if silent else job.prompt
    if job.pre_script:
        try:
            output = _run_pre_script(job.pre_script)
        except Exception as e:
            log.exception("pre_script failed for %s", job.id)
            await bot.send_message(chat_id=job.deliver_to, text=f"[{job.name}] pre-script error: {e}")
            return
        prompt = f"=== Pre-run script output ===\n{output}\n=== End script output ===\n\n{job.prompt}"

    try:
        result = await _run_claude(prompt, job_id=job.id)
    except Exception as e:
        log.exception("Claude run failed for %s", job.id)
        await bot.send_message(chat_id=job.deliver_to, text=f"[{job.name}] Claude error: {e}")
        return

    if silent:
        log.info("Job %s ran silently (no delivery)", job.id)
        return

    if not result:
        await bot.send_message(chat_id=job.deliver_to, text=f"[{job.name}] (no output)")
        return

    await _send_to_telegram(bot, job.deliver_to, result)
    log.info("Job %s delivered", job.id)


def install_jobs(scheduler: AsyncIOScheduler, bot: Bot) -> list[Job]:
    jobs = load_jobs()
    for job in jobs:
        trigger = CronTrigger.from_crontab(job.schedule)
        scheduler.add_job(
            run_job,
            trigger=trigger,
            args=[job, bot],
            id=job.id,
            name=job.name,
            misfire_grace_time=600,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        log.info("Scheduled %s (%s) — %s", job.id, job.name, job.schedule)
    return jobs
