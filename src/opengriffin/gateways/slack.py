"""Slack gateway. Free for Slack workspace owners.

Uses Slack Bolt's Socket Mode (no public webhook URL required).

Requires: pip install 'opengriffin[slack]'
Env: SLACK_BOT_TOKEN (xoxb-…), SLACK_APP_TOKEN (xapp-…), SLACK_ALLOWED_USERS (optional)

Setup:
  1. https://api.slack.com/apps → Create New App → from scratch
  2. Socket Mode → enable; create app-level token with `connections:write`
  3. OAuth & Permissions → bot scopes: chat:write, im:history, im:read, im:write,
                                       channels:history, channels:read, app_mentions:read
  4. Event Subscriptions → enable; subscribe to bot events: message.im, app_mention
  5. Install App to Workspace → copy bot token + app token into env
"""

from __future__ import annotations

import logging
import os

from . import Handler, Message

log = logging.getLogger("opengriffin.gateways.slack")


class SlackGateway:
    name = "slack"

    def __init__(self):
        try:
            from slack_bolt.adapter.socket_mode.async_handler import (
                AsyncSocketModeHandler,  # noqa: F401
            )
            from slack_bolt.async_app import AsyncApp  # noqa: F401
        except ImportError as e:
            raise RuntimeError("Install with: pip install 'opengriffin[slack]'") from e
        self._bot_token = os.environ.get("SLACK_BOT_TOKEN")
        self._app_token = os.environ.get("SLACK_APP_TOKEN")
        if not (self._bot_token and self._app_token):
            raise RuntimeError("SLACK_BOT_TOKEN + SLACK_APP_TOKEN required")
        raw = os.environ.get("SLACK_ALLOWED_USERS", "").strip()
        self._allowed: set[str] = {x for x in raw.replace(",", " ").split() if x.strip()}
        self._handler_obj: object | None = None

    def _authorized(self, user_id: str) -> bool:
        return not self._allowed or user_id in self._allowed

    async def start(self, handler: Handler) -> None:
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        from slack_bolt.async_app import AsyncApp

        app = AsyncApp(token=self._bot_token)

        async def on_message(event, say):
            if event.get("bot_id") or event.get("subtype"):
                return
            user_id = event.get("user", "")
            if not self._authorized(user_id):
                return
            text = (event.get("text") or "").strip()
            if not text:
                return
            channel = event.get("channel", "")
            normalized = Message(
                platform="slack",
                user_id=user_id,
                user_handle=user_id,
                chat_id=channel,
                text=text,
                is_dm=channel.startswith("D"),
                raw=event,
            )
            try:
                reply = await handler(normalized)
            except Exception as e:
                log.exception("handler error")
                await say(f"Error: {e}")
                return
            for i in range(0, len(reply.text), 3500):
                await say(reply.text[i : i + 3500])

        app.message()(on_message)
        app.event("app_mention")(on_message)

        self._handler_obj = AsyncSocketModeHandler(app, self._app_token)
        await self._handler_obj.start_async()

    async def stop(self) -> None:
        if self._handler_obj:
            await self._handler_obj.close_async()
