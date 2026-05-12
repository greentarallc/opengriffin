"""Discord gateway. Free.

Requires: pip install 'opengriffin[discord]'  (installs discord.py)
Env: DISCORD_BOT_TOKEN, DISCORD_ALLOWED_USERS (comma-separated user ids; optional)

Setup:
  1. https://discord.com/developers/applications → New Application → Bot tab → reset token
  2. OAuth2 → URL Generator → scopes: bot, applications.commands; perms: Send Messages, Read Message History
  3. Invite to your server with that URL
  4. Set DISCORD_BOT_TOKEN env, run `opengriffin run --gateway discord`
"""

from __future__ import annotations

import logging
import os

from . import Handler, Message

log = logging.getLogger("opengriffin.gateways.discord")


class DiscordGateway:
    name = "discord"

    def __init__(self):
        try:
            import discord  # noqa: F401
        except ImportError as e:
            raise RuntimeError("Install with: pip install 'opengriffin[discord]'") from e
        self._token = os.environ.get("DISCORD_BOT_TOKEN")
        if not self._token:
            raise RuntimeError("DISCORD_BOT_TOKEN not set")
        raw = os.environ.get("DISCORD_ALLOWED_USERS", "").strip()
        self._allowed: set[int] = {
            int(x) for x in raw.replace(",", " ").split() if x.strip().isdigit()
        }
        self._client: object | None = None

    def _authorized(self, user_id: int) -> bool:
        return not self._allowed or user_id in self._allowed

    async def start(self, handler: Handler) -> None:
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready():
            log.info("Discord ready as %s", client.user)

        @client.event
        async def on_message(msg):
            if msg.author.bot:
                return
            if not self._authorized(msg.author.id):
                return
            text = (msg.content or "").strip()
            if not text:
                return
            normalized = Message(
                platform="discord",
                user_id=str(msg.author.id),
                user_handle=str(msg.author),
                chat_id=str(msg.channel.id),
                text=text,
                is_dm=isinstance(msg.channel, discord.DMChannel),
                raw=msg,
            )
            try:
                reply = await handler(normalized)
            except Exception as e:
                log.exception("handler error")
                await msg.channel.send(f"Error: {e}")
                return
            # Discord max msg length 2000
            for i in range(0, len(reply.text), 1900):
                await msg.channel.send(reply.text[i : i + 1900])
            for path in reply.media_paths or []:
                try:
                    await msg.channel.send(file=discord.File(path))
                except Exception as e:
                    log.warning("Couldn't send attachment %s: %s", path, e)

        self._client = client
        await client.start(self._token)

    async def stop(self) -> None:
        if self._client:
            await self._client.close()
