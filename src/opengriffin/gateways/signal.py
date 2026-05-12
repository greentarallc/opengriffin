"""Signal gateway. Free.

Wraps signal-cli's JSON-RPC mode (`signal-cli -a +<number> jsonRpc`).

Setup:
  1. brew install signal-cli   (or download from github.com/AsamK/signal-cli)
  2. signal-cli -a +YOURNUMBER register   (requires SMS verification)
  3. signal-cli -a +YOURNUMBER verify <code-from-SMS>
  4. Set env: SIGNAL_NUMBER=+15551234567, SIGNAL_ALLOWED_NUMBERS=+15555551111,...

Note: signal-cli needs Java 21+. The lib is jankier than telegram/discord.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess

from . import Handler, Message

log = logging.getLogger("opengriffin.gateways.signal")


class SignalGateway:
    name = "signal"

    def __init__(self):
        self._number = os.environ.get("SIGNAL_NUMBER")
        if not self._number:
            raise RuntimeError("SIGNAL_NUMBER not set (e.g. +15551234567)")
        if subprocess.run(["which", "signal-cli"], capture_output=True).returncode != 0:
            raise RuntimeError("signal-cli not in PATH; brew install signal-cli")
        raw = os.environ.get("SIGNAL_ALLOWED_NUMBERS", "").strip()
        self._allowed = {x.strip() for x in raw.split(",") if x.strip()}
        self._proc: asyncio.subprocess.Process | None = None
        self._stop = False

    def _authorized(self, number: str) -> bool:
        return not self._allowed or number in self._allowed

    async def start(self, handler: Handler) -> None:
        # signal-cli daemon mode: outputs incoming messages as JSON lines
        self._proc = await asyncio.create_subprocess_exec(
            "signal-cli",
            "-a",
            self._number,
            "--output",
            "json",
            "receive",
            "--timeout",
            "10",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log.info("Signal listening as %s", self._number)
        while not self._stop and self._proc.stdout:
            line = await self._proc.stdout.readline()
            if not line:
                # Re-spawn on EOF
                await asyncio.sleep(2)
                self._proc = await asyncio.create_subprocess_exec(
                    "signal-cli",
                    "-a",
                    self._number,
                    "--output",
                    "json",
                    "receive",
                    "--timeout",
                    "10",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                continue
            try:
                evt = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            envelope = evt.get("envelope") or {}
            data = envelope.get("dataMessage") or {}
            text = data.get("message")
            sender = envelope.get("source")
            if not (text and sender and self._authorized(sender)):
                continue
            normalized = Message(
                platform="signal",
                user_id=sender,
                user_handle=sender,
                chat_id=sender,
                text=text.strip(),
                is_dm=True,
                raw=evt,
            )
            try:
                reply = await handler(normalized)
            except Exception as e:
                log.exception("handler error")
                self._send(sender, f"Error: {e}")
                continue
            self._send(sender, reply.text)

    def _send(self, recipient: str, body: str) -> None:
        try:
            subprocess.run(
                ["signal-cli", "-a", self._number, "send", "-m", body, recipient],
                check=True,
                capture_output=True,
                timeout=15,
            )
        except subprocess.CalledProcessError as e:
            log.warning("signal send failed: %s", e.stderr[:200])

    async def stop(self) -> None:
        self._stop = True
        if self._proc:
            self._proc.terminate()
