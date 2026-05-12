"""iMessage gateway. macOS only. Free.

Polls the local Messages.app SQLite database for new messages from
authorized contacts, then sends replies via osascript / `imsg` CLI.

Env:
  IMESSAGE_ALLOWED_HANDLES — comma-separated phone numbers / Apple IDs (required)
  IMESSAGE_DB_PATH — defaults to ~/Library/Messages/chat.db

Setup:
  1. Grant Terminal/your shell Full Disk Access (System Settings → Privacy)
  2. Optional: brew install steipete/tap/imsg for friendlier sending
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import subprocess
from pathlib import Path

from . import Handler, Message

log = logging.getLogger("opengriffin.gateways.imessage")


class IMessageGateway:
    name = "imessage"

    def __init__(self):
        raw = os.environ.get("IMESSAGE_ALLOWED_HANDLES", "").strip()
        self._allowed = {x.strip() for x in raw.split(",") if x.strip()}
        if not self._allowed:
            raise RuntimeError("IMESSAGE_ALLOWED_HANDLES must list at least one handle")
        self._db = Path(
            os.environ.get(
                "IMESSAGE_DB_PATH", str(Path.home() / "Library" / "Messages" / "chat.db")
            )
        )
        if not self._db.is_file():
            raise RuntimeError(f"chat.db not found at {self._db}; grant Full Disk Access?")
        self._last_rowid = 0
        self._stop = False

    async def start(self, handler: Handler) -> None:
        # Initialize cursor
        self._last_rowid = self._max_rowid()
        log.info("iMessage starting at rowid %d", self._last_rowid)
        while not self._stop:
            try:
                await asyncio.to_thread(self._poll_once, handler)
            except Exception:
                log.exception("poll failed")
            await asyncio.sleep(3)

    def _max_rowid(self) -> int:
        with sqlite3.connect(f"file:{self._db}?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT MAX(ROWID) FROM message").fetchone()
            return row[0] or 0

    def _poll_once(self, handler) -> None:
        with sqlite3.connect(f"file:{self._db}?mode=ro", uri=True) as conn:
            cur = conn.execute(
                """
                SELECT m.ROWID, m.text, m.is_from_me, h.id AS handle
                FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.ROWID > ? AND m.is_from_me = 0
                ORDER BY m.ROWID
                """,
                (self._last_rowid,),
            )
            for rowid, text, _is_from_me, handle in cur.fetchall():
                self._last_rowid = rowid
                if handle not in self._allowed:
                    continue
                if not text:
                    continue
                normalized = Message(
                    platform="imessage",
                    user_id=handle,
                    user_handle=handle,
                    chat_id=handle,
                    text=text.strip(),
                    is_dm=True,
                )
                loop = asyncio.new_event_loop()
                try:
                    reply = loop.run_until_complete(handler(normalized))
                finally:
                    loop.close()
                self._send(handle, reply.text)

    @staticmethod
    def _send(handle: str, body: str) -> None:
        # AppleScript via osascript — send to Messages.app
        body = body.replace("\\", "\\\\").replace('"', '\\"')
        script = f'''
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{handle}" of targetService
            send "{body}" to targetBuddy
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=15)
        except subprocess.CalledProcessError as e:
            log.warning("osascript send failed: %s", e.stderr.decode(errors="replace")[:200])

    async def stop(self) -> None:
        self._stop = True
