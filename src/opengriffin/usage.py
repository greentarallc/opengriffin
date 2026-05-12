"""Token & cost usage logger.

Each Claude run appends a line to usage.jsonl. /usage in Telegram summarizes
last 24h / 7d / 30d.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

LOG_FILE = Path(__file__).resolve().parent / "usage.jsonl"


def record(
    *,
    chat_id: str | None,
    job_id: str | None,
    session_id: str | None,
    cost_usd: float | None,
    input_tokens: int | None,
    output_tokens: int | None,
    extra: dict[str, Any] | None = None,
) -> None:
    entry = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "chat_id": chat_id,
        "job_id": job_id,
        "session_id": session_id,
        "cost_usd": cost_usd,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if extra:
        entry.update(extra)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def _read_since(cutoff: dt.datetime) -> list[dict]:
    if not LOG_FILE.is_file():
        return []
    out = []
    for line in LOG_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        try:
            ts = dt.datetime.fromisoformat(e["ts"])
        except Exception:
            continue
        if ts >= cutoff:
            out.append(e)
    return out


def insights() -> str:
    """Deeper view than /usage — patterns, top jobs, top topics, daily totals."""
    if not LOG_FILE.is_file():
        return "_(no usage data yet)_"
    rows = []
    for line in LOG_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    if not rows:
        return "_(no usage data yet)_"

    cutoff_30d = dt.datetime.now() - dt.timedelta(days=30)
    cutoff_7d = dt.datetime.now() - dt.timedelta(days=7)
    rows30 = [r for r in rows if dt.datetime.fromisoformat(r["ts"]) >= cutoff_30d]

    # Per-day totals (last 7d)
    by_day: dict[str, dict] = {}
    for r in rows30:
        ts = dt.datetime.fromisoformat(r["ts"])
        if ts < cutoff_7d:
            continue
        day = ts.date().isoformat()
        d = by_day.setdefault(day, {"runs": 0, "cost": 0.0, "tok": 0})
        d["runs"] += 1
        d["cost"] += r.get("cost_usd") or 0
        d["tok"] += (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)

    # Top jobs (30d)
    jobs: dict[str, int] = {}
    for r in rows30:
        jid = r.get("job_id")
        if jid:
            jobs[jid] = jobs.get(jid, 0) + 1

    # Top topics (30d)
    topics: dict[str, int] = {}
    for r in rows30:
        t = (r.get("topic") if "topic" in r else None) or "?"
        topics[t] = topics.get(t, 0) + 1

    lines = ["*Insights — last 30 days*"]
    total_cost = sum(r.get("cost_usd") or 0 for r in rows30)
    total_runs = len(rows30)
    avg_per_day = total_runs / 30
    lines.append(f"_Total:_ {total_runs} runs · ${total_cost:.2f} · {avg_per_day:.1f}/day avg")

    if by_day:
        lines.append("\n_Daily breakdown (last 7d):_")
        for day in sorted(by_day.keys(), reverse=True)[:7]:
            d = by_day[day]
            lines.append(f"  {day}: {d['runs']} runs · ${d['cost']:.2f}")

    if jobs:
        lines.append("\n_Top cron jobs (30d):_")
        for jid, n in sorted(jobs.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  {jid}: {n}")

    if topics:
        lines.append("\n_Top topics (30d):_")
        for t, n in sorted(topics.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  {t}: {n}")

    return "\n".join(lines)


def summary() -> str:
    now = dt.datetime.now()
    spans = [
        ("24h", now - dt.timedelta(hours=24)),
        ("7d", now - dt.timedelta(days=7)),
        ("30d", now - dt.timedelta(days=30)),
    ]
    lines = ["*Usage summary*"]
    for label, cutoff in spans:
        rows = _read_since(cutoff)
        if not rows:
            lines.append(f"_{label}_: no data")
            continue
        cost = sum((r.get("cost_usd") or 0) for r in rows)
        ti = sum((r.get("input_tokens") or 0) for r in rows)
        to_ = sum((r.get("output_tokens") or 0) for r in rows)
        lines.append(f"_{label}_: {len(rows)} runs · ${cost:.2f} · {ti:,} in / {to_:,} out")
    return "\n".join(lines)
