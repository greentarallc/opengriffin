"""Personal World Model — predictive, not retrieval.

Every other memory module in the system (echo_memory, MEMORY/USER/SOUL,
predictive.py) stores what *happened*. This module learns what *will
happen next* and lets the agent compare reality to the forecast.

Mechanics:

1. Continuous ingestion. Other modules call `observe(...)` whenever a
   structured event lands — a Telegram message arrives, a calendar item
   fires, a tool call completes. Events are typed (category) and stamped
   with weekday + hour-of-day + ISO timestamp so the model can reason
   about temporal rhythm.

2. The forecaster is small on purpose. For each (weekday, hour) bucket
   we maintain:
     - a categorical distribution over event-categories that fire in that
       slot (Bayesian update via Laplace smoothing — no neural net needed
       for personal-scale data)
     - the median inter-arrival gap, so we can forecast "next message is
       expected in ~47 minutes"
   The forecaster is rebuilt from `events.jsonl` nightly. No training run,
   no GPU — counts + normalisation in pure Python.

3. Forecasts are first-class. `forecast(horizon_hours)` returns a ranked
   list of expected event-categories with probabilities and ETA estimates.
   The agent can render them into the morning briefing, watch for drift,
   or hand them to the Living Twin for counterfactual exploration.

4. Surprise is a signal. When an event lands that the forecast assigned
   very low probability, we log it to `surprise_log.jsonl`. High-surprise
   weeks compound into MEMORY.md edits via the dream cycle — the agent
   becomes attentive to whatever's actually changing.

Storage:
  ~/.opengriffin/world_model/events.jsonl     — append-only event log
  ~/.opengriffin/world_model/model.json       — current forecast snapshot
  ~/.opengriffin/world_model/surprise.jsonl   — forecast-vs-reality misses

Honest scope: this is NOT a general probabilistic programming framework
or a deep sequence model. It's a tiny, transparent, debuggable forecaster
matched to one human's calendar-scale data. The point is that *no one
else has even this much* wired into a personal agent.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.world_model")

WM_DIR = Path.home() / ".opengriffin" / "world_model"
WM_DIR.mkdir(parents=True, exist_ok=True)
EVENTS_LOG = WM_DIR / "events.jsonl"
MODEL_FILE = WM_DIR / "model.json"
SURPRISE_LOG = WM_DIR / "surprise.jsonl"

# Laplace smoothing constant — keeps any category from being assigned
# zero probability after only one observation
SMOOTHING = 0.5

# A "surprise" event is one the model gave less than this probability
SURPRISE_THRESHOLD = 0.05


def observe(category: str, *, value: str = "", source: str = "") -> dict:
    """Record a single event observation. Lightweight — no model rebuild."""
    now = dt.datetime.now()
    entry = {
        "ts": now.isoformat(timespec="seconds"),
        "weekday": now.weekday(),  # 0=Mon, 6=Sun
        "hour": now.hour,
        "category": category,
        "value": value[:500],
        "source": source,
    }
    with EVENTS_LOG.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    # Inline surprise check, cheap. If we predicted ~0 probability for this
    # event right now and it just fired, log it.
    p = _slot_probability(category, now.weekday(), now.hour)
    if p < SURPRISE_THRESHOLD:
        _record_surprise(entry, p)
    return {**entry, "predicted_probability": p}


def _all_events(days: int = 90) -> list[dict]:
    if not EVENTS_LOG.is_file():
        return []
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    out: list[dict] = []
    for line in EVENTS_LOG.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if dt.datetime.fromisoformat(entry["ts"]) >= cutoff:
                out.append(entry)
        except Exception:
            continue
    return out


def _load_model() -> dict:
    if not MODEL_FILE.is_file():
        return {"slots": {}, "trained_at": None, "n_events": 0}
    try:
        return json.loads(MODEL_FILE.read_text())
    except Exception:
        return {"slots": {}, "trained_at": None, "n_events": 0}


def _save_model(model: dict) -> None:
    MODEL_FILE.write_text(json.dumps(model, indent=2) + "\n")


def _slot_key(weekday: int, hour: int) -> str:
    return f"{weekday}:{hour:02d}"


def _slot_probability(category: str, weekday: int, hour: int) -> float:
    """Look up P(category | weekday, hour) under the current model."""
    model = _load_model()
    slot = model.get("slots", {}).get(_slot_key(weekday, hour))
    if not slot:
        return 0.0
    counts = slot.get("category_counts", {})
    total = slot.get("total", 0)
    if total == 0:
        return 0.0
    cats = max(1, len(counts))
    return (counts.get(category, 0) + SMOOTHING) / (total + SMOOTHING * cats)


def _record_surprise(entry: dict, predicted_p: float) -> None:
    rec = {**entry, "predicted_probability": predicted_p}
    with SURPRISE_LOG.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


def train() -> dict:
    """Rebuild the forecaster from events.jsonl. Idempotent, cheap.

    The 'model' is just sufficient statistics per (weekday, hour) slot:
      - category_counts: how often each category fired in this slot
      - inter_arrival_seconds: median gap between events in this slot
      - total: events seen in this slot
    """
    events = _all_events()
    if not events:
        model = {"slots": {}, "trained_at": dt.datetime.now().isoformat(), "n_events": 0}
        _save_model(model)
        return model

    # Group by slot and by (slot, category) for inter-arrival computation
    slot_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    slot_total: dict[str, int] = defaultdict(int)
    by_slot_ts: dict[str, list[float]] = defaultdict(list)

    for e in events:
        slot = _slot_key(e["weekday"], e["hour"])
        slot_counts[slot][e["category"]] += 1
        slot_total[slot] += 1
        try:
            by_slot_ts[slot].append(dt.datetime.fromisoformat(e["ts"]).timestamp())
        except Exception:
            continue

    slots: dict[str, dict] = {}
    for slot, counts in slot_counts.items():
        timestamps = sorted(by_slot_ts[slot])
        if len(timestamps) >= 2:
            gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
            inter_arrival = statistics.median(gaps)
        else:
            inter_arrival = None
        slots[slot] = {
            "category_counts": dict(counts),
            "total": slot_total[slot],
            "inter_arrival_seconds": inter_arrival,
        }

    model = {
        "slots": slots,
        "trained_at": dt.datetime.now().isoformat(timespec="seconds"),
        "n_events": len(events),
    }
    _save_model(model)
    return model


def forecast(horizon_hours: int = 24, top_n: int = 10) -> dict:
    """Forecast event-categories likely to fire in the next `horizon_hours`.

    Returns a ranked list of (category, expected_count, peak_eta) tuples,
    plus a per-hour grid of the most likely category for each upcoming hour.
    """
    model = _load_model()
    slots = model.get("slots", {})
    if not slots:
        return {"horizon_hours": horizon_hours, "events": [], "hourly": [], "note": "untrained"}

    now = dt.datetime.now()
    expected_by_cat: dict[str, float] = defaultdict(float)
    peak_eta: dict[str, dt.datetime] = {}
    hourly: list[dict] = []

    for h_offset in range(horizon_hours):
        future = now + dt.timedelta(hours=h_offset)
        slot = _slot_key(future.weekday(), future.hour)
        slot_data = slots.get(slot)
        if not slot_data or slot_data["total"] == 0:
            hourly.append({"ts": future.isoformat(timespec="seconds"), "top_category": None})
            continue
        cats = slot_data["category_counts"]
        total = slot_data["total"]
        # Add each category's expected count contribution for this hour
        top_cat, top_p = None, 0.0
        for cat, n in cats.items():
            p = (n + SMOOTHING) / (total + SMOOTHING * max(1, len(cats)))
            expected_by_cat[cat] += p
            if p > top_p:
                top_cat, top_p = cat, p
            if cat not in peak_eta or p > _slot_probability(
                cat, peak_eta[cat].weekday(), peak_eta[cat].hour
            ):
                peak_eta[cat] = future
        hourly.append(
            {
                "ts": future.isoformat(timespec="seconds"),
                "top_category": top_cat,
                "top_probability": round(top_p, 3),
            }
        )

    ranked = sorted(expected_by_cat.items(), key=lambda kv: -kv[1])[:top_n]
    return {
        "horizon_hours": horizon_hours,
        "trained_at": model.get("trained_at"),
        "n_events_trained_on": model.get("n_events", 0),
        "events": [
            {
                "category": cat,
                "expected_occurrences": round(expected, 2),
                "peak_eta": peak_eta[cat].isoformat(timespec="seconds")
                if cat in peak_eta
                else None,
            }
            for cat, expected in ranked
        ],
        "hourly": hourly,
    }


def recent_surprises(limit: int = 10) -> list[dict]:
    if not SURPRISE_LOG.is_file():
        return []
    lines = [line for line in SURPRISE_LOG.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines[-limit:]]


def health() -> dict:
    """Quick state dump — used by the dashboard and by tests."""
    model = _load_model()
    events = _all_events(days=7)
    by_cat: dict[str, int] = defaultdict(int)
    for e in events:
        by_cat[e["category"]] += 1
    return {
        "trained_at": model.get("trained_at"),
        "n_events_total": sum(s.get("total", 0) for s in model.get("slots", {}).values()),
        "n_events_last_7d": len(events),
        "n_slots": len(model.get("slots", {})),
        "category_counts_last_7d": dict(by_cat),
        "surprise_count_7d": sum(
            1
            for s in recent_surprises(1000)
            if dt.datetime.fromisoformat(s["ts"]) >= dt.datetime.now() - dt.timedelta(days=7)
        ),
    }


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "pwm_observe",
    "Record an event observation in the personal world model. Other modules + cron jobs call this when something happens (message arrives, calendar fires, tool completes). Returns the predicted probability the model had assigned to this event — a low value signals surprise.",
    {
        "category": Annotated[
            str,
            "Event type. Use stable strings like 'message_in', 'message_out', 'meeting_start', 'tool_use', 'sleep_start', 'workout', 'commit_pushed'.",
        ],
        "value": Annotated[str | None, "Optional brief context (≤500 chars)"],
        "source": Annotated[str | None, "Originating subsystem name"],
    },
)
async def _observe(args: dict) -> dict:
    entry = observe(
        category=args["category"],
        value=args.get("value") or "",
        source=args.get("source") or "",
    )
    p = entry["predicted_probability"]
    surprise = "SURPRISE" if p < SURPRISE_THRESHOLD else "expected"
    return {
        "content": [
            {
                "type": "text",
                "text": f"observed {entry['category']} @ wd={entry['weekday']} h={entry['hour']} | P(cat|slot)={p:.3f} → {surprise}",
            }
        ]
    }


@tool(
    "pwm_forecast",
    "Forecast which event categories are likely to fire over the next N hours. Returns ranked categories with expected occurrence counts + the most-likely category for each hour. Use this for morning briefings, drift detection, and seeding Living Twin counterfactuals.",
    {
        "horizon_hours": Annotated[
            int | None, "How far ahead to forecast in hours (default 24, max 168 = 1 week)"
        ],
        "top_n": Annotated[int | None, "How many top categories to return (default 10)"],
    },
)
async def _forecast(args: dict) -> dict:
    horizon = min(int(args.get("horizon_hours") or 24), 168)
    top_n = int(args.get("top_n") or 10)
    f = forecast(horizon_hours=horizon, top_n=top_n)
    return {"content": [{"type": "text", "text": json.dumps(f, indent=2)}]}


@tool(
    "pwm_train",
    "Rebuild the forecaster from the event log. Run nightly via cron or manually after a model anomaly. Cheap (counts in Python, no GPU).",
    {},
)
async def _train(args: dict) -> dict:
    model = train()
    return {
        "content": [
            {
                "type": "text",
                "text": f"trained on {model['n_events']} events into {len(model['slots'])} slots at {model['trained_at']}",
            }
        ]
    }


@tool(
    "pwm_surprises",
    f"Show the most recent forecast-vs-reality misses. Each entry is an event the model gave less than {SURPRISE_THRESHOLD} probability when it fired. High surprise → the agent should pay attention.",
    {"limit": Annotated[int | None, "How many recent surprises to return (default 10)"]},
)
async def _surprises(args: dict) -> dict:
    items = recent_surprises(int(args.get("limit") or 10))
    if not items:
        return {"content": [{"type": "text", "text": "(no recorded surprises)"}]}
    lines = [
        f"{e['ts']}  {e['category']:<20} P={e['predicted_probability']:.3f}  «{e.get('value', '')[:60]}»"
        for e in items
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "pwm_health",
    "Summary of the world model's current state: training freshness, event volume, distribution of categories, surprise count.",
    {},
)
async def _health(args: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(health(), indent=2)}]}


WORLD_MODEL_SERVER = create_sdk_mcp_server(
    name="world_model",
    version="1.0.0",
    tools=[_observe, _forecast, _train, _surprises, _health],
)


__all__ = [
    "observe",
    "forecast",
    "train",
    "recent_surprises",
    "health",
    "WORLD_MODEL_SERVER",
    "SURPRISE_THRESHOLD",
]
