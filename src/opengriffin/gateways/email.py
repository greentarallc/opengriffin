"""Email gateway. Free.

IMAP IDLE for inbound, SMTP for outbound. Stdlib only.

Env:
  EMAIL_IMAP_HOST, EMAIL_IMAP_PORT (default 993), EMAIL_IMAP_USER, EMAIL_IMAP_PASS
  EMAIL_SMTP_HOST, EMAIL_SMTP_PORT (default 587), EMAIL_SMTP_USER, EMAIL_SMTP_PASS
  EMAIL_FROM_ADDR, EMAIL_ALLOWED_SENDERS (comma-separated; optional)

Workflow style: send the bot an email; it replies inline. Great for async or
mobile-without-Telegram setups.
"""

from __future__ import annotations

import asyncio
import email as stdlib_email
import imaplib
import logging
import os
import smtplib
from email.message import EmailMessage

from . import Handler, Message

log = logging.getLogger("opengriffin.gateways.email")


class EmailGateway:
    name = "email"

    def __init__(self):
        self._imap_host = os.environ.get("EMAIL_IMAP_HOST")
        self._imap_port = int(os.environ.get("EMAIL_IMAP_PORT", "993"))
        self._imap_user = os.environ.get("EMAIL_IMAP_USER")
        self._imap_pass = os.environ.get("EMAIL_IMAP_PASS")
        self._smtp_host = os.environ.get("EMAIL_SMTP_HOST", self._imap_host)
        self._smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
        self._smtp_user = os.environ.get("EMAIL_SMTP_USER", self._imap_user)
        self._smtp_pass = os.environ.get("EMAIL_SMTP_PASS", self._imap_pass)
        self._from_addr = os.environ.get("EMAIL_FROM_ADDR", self._imap_user)
        if not all([self._imap_host, self._imap_user, self._imap_pass, self._from_addr]):
            raise RuntimeError("EMAIL_* env vars not fully set")
        raw = os.environ.get("EMAIL_ALLOWED_SENDERS", "").strip()
        self._allowed: set[str] = {x.strip().lower() for x in raw.split(",") if x.strip()}
        self._stop = False

    def _authorized(self, addr: str) -> bool:
        return not self._allowed or addr.lower() in self._allowed

    async def start(self, handler: Handler) -> None:
        # Poll every 60 seconds (no IMAP IDLE in stdlib; for production use aioimaplib)
        while not self._stop:
            try:
                await asyncio.to_thread(self._poll_once, handler)
            except Exception as e:
                log.exception("poll failed: %s", e)
            await asyncio.sleep(60)

    def _poll_once(self, handler: Handler) -> None:
        with imaplib.IMAP4_SSL(self._imap_host, self._imap_port) as M:
            M.login(self._imap_user, self._imap_pass)
            M.select("INBOX")
            typ, data = M.search(None, "UNSEEN")
            if typ != "OK":
                return
            for num in data[0].split():
                typ, raw = M.fetch(num, "(RFC822)")
                if typ != "OK":
                    continue
                msg_obj = stdlib_email.message_from_bytes(raw[0][1])
                from_addr = stdlib_email.utils.parseaddr(msg_obj["From"])[1]
                if not self._authorized(from_addr):
                    log.info("rejecting unauthorized sender %s", from_addr)
                    continue
                subject = msg_obj.get("Subject", "")
                body = self._extract_text(msg_obj)
                # Run the async handler synchronously inside this thread
                normalized = Message(
                    platform="email",
                    user_id=from_addr,
                    user_handle=from_addr,
                    chat_id=msg_obj.get("Message-Id", from_addr),
                    text=f"Subject: {subject}\n\n{body}",
                    is_dm=True,
                    raw=msg_obj,
                )
                loop = asyncio.new_event_loop()
                try:
                    reply = loop.run_until_complete(handler(normalized))
                finally:
                    loop.close()
                self._send(
                    from_addr, "Re: " + subject, reply.text, in_reply_to=msg_obj.get("Message-Id")
                )

    @staticmethod
    def _extract_text(msg) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")
        return msg.get_payload(decode=True).decode("utf-8", errors="replace")

    def _send(self, to_addr: str, subject: str, body: str, in_reply_to: str | None = None) -> None:
        em = EmailMessage()
        em["From"] = self._from_addr
        em["To"] = to_addr
        em["Subject"] = subject
        if in_reply_to:
            em["In-Reply-To"] = in_reply_to
            em["References"] = in_reply_to
        em.set_content(body)
        with smtplib.SMTP(self._smtp_host, self._smtp_port) as s:
            s.starttls()
            s.login(self._smtp_user, self._smtp_pass)
            s.send_message(em)

    async def stop(self) -> None:
        self._stop = True
