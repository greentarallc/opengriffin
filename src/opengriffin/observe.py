"""Live observability — Server-Sent Events stream of every agent event.

Real-time view of what the agent is thinking and doing. Datadog APM for
cognition. Bot writes events to an in-memory ring buffer; clients subscribe
via SSE at GET /observe/stream.

Routes:
  GET /observe/         → simple HTML page tailing the stream
  GET /observe/stream   → text/event-stream of JSON events
  GET /observe/events   → last N events as JSON (for snapshots)
  POST /observe/event   → emit an event (for non-bot writers)
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
from collections import deque
from typing import Any

from aiohttp import web

# Ring buffer of recent events. Bot writes; subscribers read.
_EVENTS: deque[dict] = deque(maxlen=2000)
_subscribers: list[asyncio.Queue] = []


def emit(kind: str, **fields: Any) -> None:
    """Emit an event to all subscribers + the ring buffer.

    Call from anywhere in the bot:
        observe.emit("tool_use", tool="Bash", input="ls /tmp", chat_id=123)
    """
    evt = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        **fields,
    }
    _EVENTS.append(evt)
    for q in list(_subscribers):
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(evt)


async def _handle_stream(request: web.Request) -> web.StreamResponse:
    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.append(q)
    try:
        # Replay last 50 events so the client gets context
        for evt in list(_EVENTS)[-50:]:
            await resp.write(f"data: {json.dumps(evt)}\n\n".encode())
        while True:
            evt = await q.get()
            await resp.write(f"data: {json.dumps(evt)}\n\n".encode())
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        if q in _subscribers:
            _subscribers.remove(q)
    return resp


async def _handle_events(request: web.Request) -> web.Response:
    n = int(request.query.get("n", "100"))
    return web.json_response(list(_EVENTS)[-n:])


async def _handle_emit(request: web.Request) -> web.Response:
    body = await request.json()
    if "kind" not in body:
        return web.json_response({"error": "kind required"}, status=400)
    emit(body.pop("kind"), **body)
    return web.json_response({"ok": True})


INDEX_HTML = """<!doctype html>
<html><head><title>OpenGriffin Observability</title>
<style>
  body { background: #0b0b0d; color: #e7e7ea; font: 13px ui-monospace, Menlo, monospace; margin: 0; padding: 16px; }
  header { padding: 8px 0 16px; border-bottom: 1px solid #2a2a30; margin-bottom: 16px; }
  h1 { margin: 0; font-size: 20px; color: #6cf; }
  .evt { padding: 6px 8px; border-left: 3px solid #2a2a30; margin: 4px 0; background: #14141a; }
  .evt.tool_use { border-color: #3aa; }
  .evt.message { border-color: #6cf; }
  .evt.error { border-color: #d33; }
  .evt.cron { border-color: #8a3; }
  .evt.worker { border-color: #c8a; }
  .ts { color: #777; margin-right: 8px; }
  .kind { color: #fc6; margin-right: 8px; font-weight: bold; }
  .body { color: #ddd; white-space: pre-wrap; }
  #log { max-height: 90vh; overflow-y: auto; }
</style></head>
<body>
<header><h1>🦅 OpenGriffin · live observability</h1></header>
<div id="log"></div>
<script>
const log = document.getElementById('log');
const es = new EventSource('/observe/stream');
es.onmessage = (e) => {
  const evt = JSON.parse(e.data);
  const div = document.createElement('div');
  div.className = 'evt ' + (evt.kind || '');
  const meta = JSON.parse(JSON.stringify(evt));
  delete meta.ts; delete meta.kind;
  div.innerHTML = `<span class="ts">${evt.ts}</span><span class="kind">${evt.kind}</span><span class="body">${JSON.stringify(meta)}</span>`;
  log.prepend(div);
  while (log.children.length > 500) log.removeChild(log.lastChild);
};
</script></body></html>
"""


async def _handle_index(request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html")


def attach(app: web.Application) -> None:
    """Mount observability routes onto an existing aiohttp app."""
    app.router.add_get("/observe/", _handle_index)
    app.router.add_get("/observe/stream", _handle_stream)
    app.router.add_get("/observe/events", _handle_events)
    app.router.add_post("/observe/event", _handle_emit)
