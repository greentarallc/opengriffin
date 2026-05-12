"""Matrix gateway. Free.

Uses matrix-nio (the official Python client). Works with any Matrix
homeserver (matrix.org, your own Synapse, Beeper, etc.).

Requires: pip install 'opengriffin[matrix]'  (installs matrix-nio[e2e])
Env:
  MATRIX_HOMESERVER (e.g. https://matrix.org)
  MATRIX_USER_ID    (e.g. @bot:matrix.org)
  MATRIX_PASSWORD   (or MATRIX_ACCESS_TOKEN to skip login)
  MATRIX_ALLOWED_USERS — comma-separated user IDs (optional)
"""

from __future__ import annotations

import logging
import os

from . import Handler, Message

log = logging.getLogger("opengriffin.gateways.matrix")


class MatrixGateway:
    name = "matrix"

    def __init__(self):
        try:
            from nio import AsyncClient  # noqa: F401
        except ImportError as e:
            raise RuntimeError("Install with: pip install 'opengriffin[matrix]'") from e
        self._homeserver = os.environ.get("MATRIX_HOMESERVER", "https://matrix.org")
        self._user_id = os.environ.get("MATRIX_USER_ID")
        self._password = os.environ.get("MATRIX_PASSWORD")
        self._access_token = os.environ.get("MATRIX_ACCESS_TOKEN")
        if not self._user_id or not (self._password or self._access_token):
            raise RuntimeError("MATRIX_USER_ID + (MATRIX_PASSWORD or MATRIX_ACCESS_TOKEN) required")
        raw = os.environ.get("MATRIX_ALLOWED_USERS", "").strip()
        self._allowed = {x.strip() for x in raw.split(",") if x.strip()}
        self._client: object | None = None

    def _authorized(self, user_id: str) -> bool:
        return not self._allowed or user_id in self._allowed

    async def start(self, handler: Handler) -> None:
        from nio import AsyncClient, RoomMessageText

        client = AsyncClient(self._homeserver, self._user_id)
        if self._access_token:
            client.access_token = self._access_token
            client.user_id = self._user_id
        else:
            await client.login(self._password)
        self._client = client

        async def on_message(room, event):
            if event.sender == self._user_id:
                return
            if not self._authorized(event.sender):
                return
            text = (event.body or "").strip()
            if not text:
                return
            normalized = Message(
                platform="matrix",
                user_id=event.sender,
                user_handle=event.sender,
                chat_id=room.room_id,
                text=text,
                is_dm=room.is_group
                is False,  # nio doesn't expose DM cleanly; treat all as DM-equivalent
                raw=event,
            )
            try:
                reply = await handler(normalized)
            except Exception as e:
                log.exception("handler error")
                await client.room_send(
                    room.room_id,
                    "m.room.message",
                    {"msgtype": "m.text", "body": f"Error: {e}"},
                )
                return
            await client.room_send(
                room.room_id,
                "m.room.message",
                {"msgtype": "m.text", "body": reply.text},
            )

        client.add_event_callback(on_message, RoomMessageText)
        await client.sync_forever(timeout=30000)

    async def stop(self) -> None:
        if self._client:
            await self._client.close()
