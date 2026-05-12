"""Secret redaction + memory-injection blocklist."""

from __future__ import annotations

import re

# Patterns that look like secrets in tool output. We redact before the LLM sees them.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-ant-(api03|oat01)-[A-Za-z0-9_\-]{40,}"), "<REDACTED:anthropic_key>"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{40,}"), "<REDACTED:openai_key>"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "<REDACTED:google_key>"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "<REDACTED:aws_access_key>"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "<REDACTED:github_token>"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{60,}"), "<REDACTED:github_pat>"),
    (re.compile(r"xox[abops]-[A-Za-z0-9-]{20,}"), "<REDACTED:slack_token>"),
    (re.compile(r"\d{8,12}:AA[A-Za-z0-9_\-]{32,}"), "<REDACTED:telegram_bot_token>"),
    (
        re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+PRIVATE KEY-----"),
        "<REDACTED:private_key>",
    ),
]


def redact(text: str) -> str:
    if not text:
        return text
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


# Patterns that look like prompt-injection attempts. We refuse to write memory entries
# matching any of these — they could be planted by a user, web page, or tool output.
_INJECTION_PATTERNS = [
    re.compile(r"ignore (all |the |your )?previous (instructions|prompts)", re.IGNORECASE),
    re.compile(r"disregard (all |the |your )?(prior|earlier|above)", re.IGNORECASE),
    re.compile(r"</?(system|user|assistant)>", re.IGNORECASE),
    re.compile(r"<\|im_(start|end)\|>", re.IGNORECASE),
    re.compile(r"\[\[INST\]\]|\[/INST\]\]", re.IGNORECASE),
    re.compile(r"forget (everything|all (instructions|prompts))", re.IGNORECASE),
    re.compile(r"reveal (your |the )?(system )?prompt", re.IGNORECASE),
    re.compile(r"\bDAN (mode|prompt)\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
]


def looks_like_injection(text: str) -> bool:
    return any(pat.search(text) for pat in _INJECTION_PATTERNS)
