"""Multi-platform gateway adapters.

Each adapter normalizes its platform's events to a common Message shape
and pipes them through the bot's `ask_claude_with_progress` pipeline.
Replies are rendered back via the platform's API.

All free-pricing gateways are first-class. Paid platforms (WhatsApp via
Twilio, SMS via Twilio, Microsoft Teams) are intentionally NOT included
in the OSS distribution.

Currently shipped:
  - telegram (default, the canonical implementation)
  - discord
  - slack
  - email   (IMAP listener + SMTP sender)
  - imessage (macOS only, via imsg CLI)
  - signal   (via signal-cli)
  - matrix   (via matrix-nio)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Message:
    """Normalized inbound message from any gateway."""

    platform: str  # "telegram" | "discord" | "slack" | "email" | "imessage" | "signal" | "matrix"
    user_id: str  # platform-specific stable ID
    user_handle: str  # display name / handle
    chat_id: str  # platform-specific channel/DM id
    text: str  # message body
    voice_bytes: bytes | None = None  # if present, transcribe before processing
    is_dm: bool = True  # vs group/channel
    raw: object = None  # original event for adapters that need it


@dataclass
class Reply:
    """Outbound reply produced by the bot."""

    text: str
    media_paths: list[str] = None  # optional file attachments


# A handler the gateway calls for each inbound message; returns a Reply.
Handler = Callable[[Message], Awaitable[Reply]]


class Gateway(Protocol):
    """Each gateway implements start/stop. They run as background asyncio tasks."""

    name: str

    async def start(self, handler: Handler) -> None: ...
    async def stop(self) -> None: ...
