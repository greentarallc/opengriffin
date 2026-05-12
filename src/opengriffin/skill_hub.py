"""Skill Hub — install/list/publish skills with attribution + reputation.

Sources supported:
  github://owner/repo[/path]@ref     — clone a single skill from a GitHub repo
  github-org://owner/repo            — install all skills from skills/ in a repo
  https://...                          — direct URL to a SKILL.md (single skill)

Every install records an entry in `~/.opengriffin/skill_hub.json` capturing source,
license, install_time, signature (sha256 of SKILL.md bytes), and outcome
(used? uninstalled? errored?). Outcome telemetry stays local — opt-in upload
to a shared registry comes later.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

SKILLS_ROOT = Path.home() / ".claude" / "skills"
HUB_FILE = Path.home() / ".opengriffin" / "skill_hub.json"
HUB_FILE.parent.mkdir(parents=True, exist_ok=True)

GITHUB_RE = re.compile(r"^github(?:-org)?://([\w.-]+)/([\w.-]+)(?:/([\w./-]+))?(?:@([\w./-]+))?$")
HTTPS_RE = re.compile(r"^https?://")


# ----------------------------- registry persistence -----------------------------


def _load() -> dict:
    if not HUB_FILE.is_file():
        return {"installed": {}}
    try:
        return json.loads(HUB_FILE.read_text())
    except Exception:
        return {"installed": {}}


def _save(data: dict) -> None:
    HUB_FILE.write_text(json.dumps(data, indent=2) + "\n")


# ----------------------------- license check -----------------------------


def _read_license(repo_dir: Path) -> tuple[str, str]:
    """Returns (kind, header_snippet)."""
    for fname in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        p = repo_dir / fname
        if p.is_file():
            head = p.read_text(errors="replace")[:1500].lower()
            if "apache license" in head:
                return "apache-2.0", head[:300]
            if "mit license" in head:
                return "mit", head[:300]
            if "bsd " in head:
                return "bsd", head[:300]
            if "gnu general public license" in head or "gpl" in head:
                return "gpl", head[:300]
            return "unknown", head[:300]
    return "missing", ""


PERMISSIVE = {"apache-2.0", "mit", "bsd"}


# ----------------------------- install paths -----------------------------


def _install_skill_dir(src_dir: Path, name: str, *, source: str, license_kind: str) -> dict:
    """Copy a single skill into ~/.claude/skills/<name>/ and record the install."""
    if not (src_dir / "SKILL.md").is_file():
        raise ValueError(f"no SKILL.md in {src_dir}")
    dest = SKILLS_ROOT / name
    if dest.exists():
        raise ValueError(f"skill already installed: {name} (uninstall first)")
    shutil.copytree(src_dir, dest, symlinks=False)
    sig = hashlib.sha256((dest / "SKILL.md").read_bytes()).hexdigest()[:16]
    entry = {
        "name": name,
        "source": source,
        "license": license_kind,
        "installed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "signature": sig,
        "use_count": 0,
        "uninstalled_at": None,
    }
    data = _load()
    data["installed"][name] = entry
    _save(data)
    return entry


def install(source: str, *, allow_unknown_license: bool = False) -> dict:
    """Install one or many skills from a source URI. Returns summary."""
    m = GITHUB_RE.match(source)
    is_org_install = source.startswith("github-org://")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        if m:
            owner, repo, sub_path, ref = m.groups()
            url = f"https://github.com/{owner}/{repo}.git"
            cmd = ["git", "clone", "--depth", "1"]
            if ref:
                cmd += ["--branch", ref]
            cmd += [url, str(td_path / "repo")]
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            repo_dir = td_path / "repo"
            license_kind, _ = _read_license(repo_dir)

            if license_kind not in PERMISSIVE and not allow_unknown_license:
                raise PermissionError(
                    f"license is '{license_kind}'. Pass allow_unknown_license=True to install anyway."
                )

            if is_org_install:
                # Find every dir containing SKILL.md
                skills_found = []
                for sm in repo_dir.rglob("SKILL.md"):
                    skill_dir = sm.parent
                    name = skill_dir.name
                    try:
                        skills_found.append(
                            _install_skill_dir(
                                skill_dir,
                                name,
                                source=f"github://{owner}/{repo}/{skill_dir.relative_to(repo_dir)}",
                                license_kind=license_kind,
                            )
                        )
                    except ValueError as e:
                        skills_found.append({"name": name, "error": str(e)})
                return {"mode": "org", "installed": skills_found, "license": license_kind}
            else:
                target = repo_dir / sub_path if sub_path else repo_dir
                # Find SKILL.md in target
                if not (target / "SKILL.md").is_file():
                    candidates = list(target.rglob("SKILL.md"))
                    if not candidates:
                        raise ValueError(f"no SKILL.md found under {target}")
                    target = candidates[0].parent
                name = sub_path.split("/")[-1] if sub_path else target.name
                entry = _install_skill_dir(target, name, source=source, license_kind=license_kind)
                return {"mode": "single", "installed": [entry], "license": license_kind}
        elif HTTPS_RE.match(source):
            # Direct URL to a SKILL.md
            tmp_skill = td_path / "skill"
            tmp_skill.mkdir()
            urllib.request.urlretrieve(source, tmp_skill / "SKILL.md")
            text = (tmp_skill / "SKILL.md").read_text()
            m = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
            if not m:
                raise ValueError("frontmatter `name:` required")
            name = m.group(1).strip().strip("\"'")
            entry = _install_skill_dir(
                tmp_skill, name, source=source, license_kind="unknown-direct-url"
            )
            return {"mode": "single", "installed": [entry], "license": "unknown"}
        else:
            raise ValueError(f"unrecognized source: {source}")


def uninstall(name: str) -> bool:
    """Remove a skill and update its install record."""
    p = SKILLS_ROOT / name
    if not p.is_dir():
        return False
    shutil.rmtree(p)
    data = _load()
    if name in data["installed"]:
        data["installed"][name]["uninstalled_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _save(data)
    return True


def list_installed() -> list[dict]:
    return list(_load().get("installed", {}).values())


def increment_use(name: str) -> None:
    """Bot calls this when a skill is invoked, for outcome reputation tracking."""
    data = _load()
    if name in data["installed"]:
        data["installed"][name]["use_count"] += 1
        data["installed"][name]["last_used_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _save(data)


def reputation(name: str) -> dict:
    """Local-only: how 'good' is this skill based on use_count / lifetime / uninstall."""
    data = _load()
    e = data["installed"].get(name)
    if not e:
        return {"name": name, "score": 0, "reason": "not installed"}
    if e.get("uninstalled_at"):
        return {"name": name, "score": 0, "reason": "uninstalled"}
    age_days = (dt.datetime.now() - dt.datetime.fromisoformat(e["installed_at"])).days or 1
    use = e.get("use_count", 0)
    score = min(100, int(use * 10 / age_days**0.5))
    return {"name": name, "score": score, "use_count": use, "age_days": age_days}


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "skill_hub_install",
    "Install a skill from GitHub or a URL. Source examples: 'github://owner/repo' (whole repo's skills/), 'github://owner/repo/path/to/skill', 'github-org://owner/repo' (every SKILL.md in the repo), or a direct https:// URL to a SKILL.md.",
    {
        "source": Annotated[str, "Source URI"],
        "allow_unknown_license": Annotated[
            bool | None, "Skip the permissive-license check (use with care)"
        ],
    },
)
async def _install(args: dict) -> dict:
    try:
        result = install(
            args["source"], allow_unknown_license=bool(args.get("allow_unknown_license"))
        )
    except (subprocess.CalledProcessError, ValueError, PermissionError) as e:
        return {"content": [{"type": "text", "text": f"install failed: {e}"}], "is_error": True}
    summary = f"installed {len(result['installed'])} skill(s) (license={result['license']})"
    return {"content": [{"type": "text", "text": summary + "\n" + json.dumps(result, indent=2)}]}


@tool(
    "skill_hub_uninstall",
    "Remove an installed skill.",
    {"name": Annotated[str, "Skill name"]},
)
async def _uninstall(args: dict) -> dict:
    ok = uninstall(args["name"])
    return {
        "content": [{"type": "text", "text": "removed" if ok else "not installed"}],
        "is_error": not ok,
    }


@tool(
    "skill_hub_list",
    "List installed skills with their source, license, use count, and reputation.",
    {},
)
async def _list(args: dict) -> dict:
    items = list_installed()
    if not items:
        return {"content": [{"type": "text", "text": "(no skills installed)"}]}
    lines = []
    for e in items:
        if e.get("uninstalled_at"):
            continue
        rep = reputation(e["name"])
        lines.append(
            f"{e['name']} ({e['license']}) — used {e['use_count']}× — score {rep['score']} — from {e['source']}"
        )
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


SKILL_HUB_SERVER = create_sdk_mcp_server(
    name="skill_hub",
    version="1.0.0",
    tools=[_install, _uninstall, _list],
)
