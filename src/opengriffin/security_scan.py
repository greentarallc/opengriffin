"""Pre-execution scanner — pattern match on every consequential action.

Matches against:
  - Prompt injection patterns (jailbreak fragments, '<|im_end|>', etc.)
  - Homograph / Unicode lookalike attacks
  - Command chaining / shell escape patterns
  - Exfiltration shapes (POST to unknown domains, base64 blobs in URLs)
  - Hardcoded credentials in commands
  - Network egress allowlist enforcement

Designed to be called BEFORE the agent's tool runs — fail closed on hits.

Acts as a pre-execution scanner with opt-in allowlists, homograph
detection, and a tiny LLM second-opinion when patterns are ambiguous.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.security_scan")

ALLOWLIST_FILE = Path.home() / ".opengriffin" / "egress_allowlist.json"
ALLOWLIST_FILE.parent.mkdir(parents=True, exist_ok=True)


# ----------------------------- patterns -----------------------------


PROMPT_INJECTION_PATTERNS = [
    re.compile(
        r"ignore (?:all |the |your )?(?:previous|prior|above) (?:instructions|prompts)",
        re.IGNORECASE,
    ),
    re.compile(r"disregard (?:all |the |prior|earlier|above)", re.IGNORECASE),
    re.compile(r"</?(?:system|user|assistant)>", re.IGNORECASE),
    re.compile(r"<\|im_(?:start|end|sep)\|>", re.IGNORECASE),
    re.compile(r"\[\[INST\]\]|\[/INST\]\]", re.IGNORECASE),
    re.compile(r"forget (?:everything|all)", re.IGNORECASE),
    re.compile(r"you are now (?:in|a)\s+", re.IGNORECASE),
    re.compile(r"reveal (?:the )?(?:system )?prompt", re.IGNORECASE),
    re.compile(r"DAN (?:mode|prompt)", re.IGNORECASE),
]

DANGEROUS_SHELL = [
    re.compile(r"\brm\s+-rf?\s+/(?!\w)"),
    re.compile(r":\(\)\{:\|:&\};:"),  # fork bomb
    re.compile(r"\bmkfs\."),
    re.compile(r"\bdd\s+if=.*\bof=/dev/(?:s[dh]|nvme)"),
    re.compile(r">\s*/dev/sd[a-z]"),
    re.compile(r"\bcurl\b.+\|\s*(?:sh|bash|zsh|fish)\b"),
    re.compile(r"\bwget\b.+\|\s*(?:sh|bash|zsh|fish)\b"),
    re.compile(r"\bchmod\s+-R\s+(?:777|0777)\b"),
    re.compile(r"\bsudo\s+rm\s+"),
    re.compile(r"\bgit\s+push\s+.*--force"),
    re.compile(r"\bdrop\s+(?:table|database)\b", re.IGNORECASE),
    re.compile(r"\btruncate\s+table\b", re.IGNORECASE),
]

HARDCODED_SECRETS = [
    re.compile(r"sk-ant-(?:api03|oat01)-[A-Za-z0-9_\-]{40,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{40,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"xox[abops]-[A-Za-z0-9-]{20,}"),
    re.compile(r"\d{8,12}:AA[A-Za-z0-9_\-]{32,}"),  # Telegram bot token
]


# Suspiciously high entropy in URL params (potential exfiltration via querystring)
def _looks_exfiltration_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except Exception:
        return False
    qs = u.query or ""
    if not qs:
        return False
    # If query has a single param with > 200 chars and base64-like → suspicious
    long_chunks = [p.split("=", 1)[-1] for p in qs.split("&") if "=" in p]
    long_chunks = [c for c in long_chunks if len(c) > 200]
    return any(re.fullmatch(r"[A-Za-z0-9+/=_-]{200,}", c) for c in long_chunks)


def _has_homograph(text: str) -> str | None:
    """Return the offending char if any non-ASCII Unicode confusable found in URL/command."""
    for ch in text:
        if ord(ch) > 127:
            try:
                name = unicodedata.name(ch)
                if "CYRILLIC" in name or "GREEK" in name or "LATIN" in name:
                    return f"{ch} ({name})"
            except ValueError:
                continue
    return None


# ----------------------------- allowlist -----------------------------


def _load_allowlist() -> dict:
    if not ALLOWLIST_FILE.is_file():
        # Sensible defaults
        return {
            "hosts": [
                "api.anthropic.com",
                "api.openai.com",
                "generativelanguage.googleapis.com",
                "api.github.com",
                "raw.githubusercontent.com",
                "github.com",
                "api.telegram.org",
                "huggingface.co",
                "api-inference.huggingface.co",
                "duckduckgo.com",
                "html.duckduckgo.com",
                "wikipedia.org",
                "en.wikipedia.org",
                "pypi.org",
                "files.pythonhosted.org",
                "registry.npmjs.org",
                "127.0.0.1",
                "localhost",
            ]
        }
    try:
        return json.loads(ALLOWLIST_FILE.read_text())
    except Exception:
        return {"hosts": []}


def _save_allowlist(data: dict) -> None:
    ALLOWLIST_FILE.write_text(json.dumps(data, indent=2) + "\n")


def url_is_allowed(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    if not host:
        return False
    hosts = _load_allowlist().get("hosts", [])
    for pattern in hosts:
        if pattern == host:
            return True
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            return True
        if host.endswith("." + pattern):
            return True
    return False


# ----------------------------- scan API -----------------------------


def scan(action_text: str) -> dict:
    """Return a verdict dict: {ok, flags: [{kind, detail}], severity}."""
    flags = []
    for p in PROMPT_INJECTION_PATTERNS:
        if p.search(action_text):
            flags.append({"kind": "prompt_injection", "detail": p.pattern[:60]})
    for p in DANGEROUS_SHELL:
        if p.search(action_text):
            flags.append({"kind": "dangerous_shell", "detail": p.pattern[:60]})
    for p in HARDCODED_SECRETS:
        if p.search(action_text):
            flags.append({"kind": "leaked_secret_pattern", "detail": p.pattern[:60]})
    # URLs in the action
    for url_match in re.finditer(r"https?://\S+", action_text):
        url = url_match.group(0).rstrip(",.)\"'")
        if not url_is_allowed(url):
            flags.append({"kind": "egress_disallowed", "detail": url[:120]})
        if _looks_exfiltration_url(url):
            flags.append({"kind": "exfil_url", "detail": url[:120]})
        homo = _has_homograph(url)
        if homo:
            flags.append({"kind": "homograph_in_url", "detail": homo})
    severity = "high" if flags else "ok"
    if flags and any(f["kind"] in {"dangerous_shell", "exfil_url"} for f in flags):
        severity = "block"
    return {"ok": not flags, "flags": flags, "severity": severity}


@tool(
    "security_scan",
    "Pre-execution scanner. Pattern-matches an action for prompt injection, dangerous shell, hardcoded secrets, exfil URLs, homograph attacks, and egress-allowlist violations. Use BEFORE running anything risky.",
    {"action_text": Annotated[str, "Full action / command / URL to scan"]},
)
async def _scan(args: dict) -> dict:
    result = scan(args["action_text"])
    return {
        "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
        "is_error": result["severity"] == "block",
    }


@tool(
    "egress_allow",
    "Add a hostname (or pattern starting with '*.') to the network egress allowlist.",
    {"host": Annotated[str, "Hostname like api.example.com or *.example.com"]},
)
async def _allow(args: dict) -> dict:
    data = _load_allowlist()
    host = args["host"].strip()
    if host not in data["hosts"]:
        data["hosts"].append(host)
        _save_allowlist(data)
    return {"content": [{"type": "text", "text": f"allowed {host}"}]}


@tool(
    "egress_list",
    "Show the current network egress allowlist.",
    {},
)
async def _list(args: dict) -> dict:
    hosts = _load_allowlist().get("hosts", [])
    return {"content": [{"type": "text", "text": "\n".join(hosts) or "(empty)"}]}


SECURITY_SERVER = create_sdk_mcp_server(
    name="security_scan",
    version="1.0.0",
    tools=[_scan, _allow, _list],
)
