"""Per-chat sub-sessions ("topics"). Each Telegram chat tracks an active topic
name; messages route to that topic's session_id. Switching topic preserves
each topic's separate history.

State persists to ~/.opengriffin/sessions.json so bot restarts and the daily
4am reset don't lose recall. Each (chat_id, topic) → session_id, plus an
archive of prior session_ids so the user can recover yesterday's
conversation.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

STORE_FILE = Path(__file__).resolve().parent / "sessions.json"
_lock = threading.Lock()


@dataclass
class TopicState:
    active: str = "default"
    sessions: dict[str, str] = field(default_factory=dict)  # topic_name -> session_id
    archive: list[dict] = field(
        default_factory=list
    )  # past sessions: {topic, session_id, archived_at}


_chats: dict[int, TopicState] = {}
_loaded = False


def _serialize() -> dict:
    return {
        "chats": {
            str(cid): {
                "active": s.active,
                "sessions": dict(s.sessions),
                "archive": list(s.archive),
            }
            for cid, s in _chats.items()
        }
    }


def _load_from_disk() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not STORE_FILE.is_file():
        return
    try:
        data = json.loads(STORE_FILE.read_text())
    except Exception:
        return
    for cid_str, payload in (data.get("chats") or {}).items():
        try:
            cid = int(cid_str)
        except ValueError:
            continue
        _chats[cid] = TopicState(
            active=payload.get("active", "default"),
            sessions=dict(payload.get("sessions") or {}),
            archive=list(payload.get("archive") or []),
        )


def _flush() -> None:
    """Atomic write of the entire store."""
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".sessions.", suffix=".tmp", dir=str(STORE_FILE.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(_serialize(), fh, indent=2)
        os.replace(tmp_path, STORE_FILE)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def state(chat_id: int) -> TopicState:
    with _lock:
        _load_from_disk()
        if chat_id not in _chats:
            _chats[chat_id] = TopicState()
        return _chats[chat_id]


def active_topic(chat_id: int) -> str:
    return state(chat_id).active


def session_id_for(chat_id: int) -> str | None:
    s = state(chat_id)
    return s.sessions.get(s.active) or None


def set_session_id(chat_id: int, session_id: str) -> None:
    if not session_id:
        return
    with _lock:
        _load_from_disk()
        s = _chats.setdefault(chat_id, TopicState())
        if s.sessions.get(s.active) == session_id:
            return  # no-op, avoid disk thrash
        s.sessions[s.active] = session_id
        _flush()


def switch(chat_id: int, topic: str) -> None:
    with _lock:
        _load_from_disk()
        s = _chats.setdefault(chat_id, TopicState())
        s.active = topic
        s.sessions.setdefault(topic, "")
        _flush()


def list_topics(chat_id: int) -> list[tuple[str, bool, bool]]:
    """Return (name, is_active, has_session) for each known topic."""
    s = state(chat_id)
    names = sorted({s.active, *s.sessions.keys()})
    return [(n, n == s.active, bool(s.sessions.get(n))) for n in names]


def reset(chat_id: int, topic: str | None = None, *, archive: bool = True) -> str | None:
    """Drop the active session_id for `topic` (default: active topic).

    If `archive=True`, the prior session_id is stashed in the archive list
    with a timestamp so it can be recovered via `restore_archived`.
    Returns the dropped session_id or None.
    """
    with _lock:
        _load_from_disk()
        s = _chats.setdefault(chat_id, TopicState())
        if topic is None:
            topic = s.active
        prior = s.sessions.pop(topic, None)
        if prior and archive:
            s.archive.append(
                {
                    "topic": topic,
                    "session_id": prior,
                    "archived_at": dt.datetime.now().isoformat(timespec="seconds"),
                }
            )
            # Keep the archive bounded
            s.archive = s.archive[-100:]
        _flush()
        return prior


def list_archive(chat_id: int) -> list[dict]:
    s = state(chat_id)
    return list(reversed(s.archive))  # most recent first


def restore_archived(chat_id: int, session_id: str, *, into_topic: str | None = None) -> bool:
    """Re-activate an archived session_id under `into_topic` (default: active)."""
    with _lock:
        _load_from_disk()
        s = _chats.setdefault(chat_id, TopicState())
        idx = next((i for i, e in enumerate(s.archive) if e["session_id"] == session_id), -1)
        if idx < 0:
            return False
        entry = s.archive.pop(idx)
        target_topic = into_topic or entry.get("topic") or s.active
        s.sessions[target_topic] = session_id
        s.active = target_topic
        _flush()
        return True
