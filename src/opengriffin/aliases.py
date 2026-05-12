"""Quick-command aliases. Map short strings → prompt templates.

Stored in ~/.opengriffin/aliases.json. The user types `/run <alias-name> <args>`
and the alias's template is rendered with $1, $2, ..., $* replacement, then
sent to Claude as if the user typed it.

Also: per-chat custom system prompt addendum lives in the same file.
"""

from __future__ import annotations

import json
from pathlib import Path

STORE_FILE = Path(__file__).resolve().parent / "aliases.json"


def _load() -> dict:
    if not STORE_FILE.is_file():
        return {"aliases": {}, "chat_sysprompts": {}, "chat_models": {}}
    try:
        d = json.loads(STORE_FILE.read_text())
    except Exception:
        d = {}
    d.setdefault("aliases", {})
    d.setdefault("chat_sysprompts", {})
    d.setdefault("chat_models", {})
    return d


def _save(data: dict) -> None:
    STORE_FILE.write_text(json.dumps(data, indent=2) + "\n")


# --- aliases ---


def list_aliases() -> dict[str, str]:
    return _load().get("aliases", {})


def get_alias(name: str) -> str | None:
    return list_aliases().get(name)


def set_alias(name: str, template: str) -> None:
    data = _load()
    data.setdefault("aliases", {})[name] = template
    _save(data)


def remove_alias(name: str) -> bool:
    data = _load()
    if name in data.get("aliases", {}):
        del data["aliases"][name]
        _save(data)
        return True
    return False


def render(template: str, args: list[str]) -> str:
    """Replace $1, $2, ..., $* in template."""
    out = template
    for i, a in enumerate(args, start=1):
        out = out.replace(f"${i}", a)
    out = out.replace("$*", " ".join(args))
    return out


# --- per-chat sysprompt addendum ---


def get_chat_sysprompt(chat_id: int) -> str:
    return _load().get("chat_sysprompts", {}).get(str(chat_id), "")


def set_chat_sysprompt(chat_id: int, text: str) -> None:
    data = _load()
    sp = data.setdefault("chat_sysprompts", {})
    if text.strip():
        sp[str(chat_id)] = text.strip()
    else:
        sp.pop(str(chat_id), None)
    _save(data)


# --- per-chat AI provider/model selection ---


def get_chat_model(chat_id: int) -> dict:
    """Return {'provider': str, 'model': str} for this chat (or empty dict)."""
    return _load().get("chat_models", {}).get(str(chat_id), {})


def set_chat_model(chat_id: int, provider: str | None, model: str | None) -> None:
    data = _load()
    cm = data.setdefault("chat_models", {})
    if not provider and not model:
        cm.pop(str(chat_id), None)
    else:
        entry = cm.get(str(chat_id), {})
        if provider:
            entry["provider"] = provider
        if model:
            entry["model"] = model
        cm[str(chat_id)] = entry
    _save(data)
