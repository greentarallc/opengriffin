## Summary

What does this PR change, in one or two sentences?

## Motivation

Why this change? Link any issue, discussion, or journal entry that surfaced the need.

## Test plan

- [ ] `uv run ruff check src tests`
- [ ] `uv run ruff format --check src tests`
- [ ] `uv run pytest -q`
- [ ] Manual: <describe>

## Risk + blast radius

- [ ] No breaking changes
- [ ] Breaking change — migration steps documented in the PR body
- [ ] Touches `bot.py`, `paths.py`, or `cli.py` — reviewer should restart their local bot to verify

## Checklist

- [ ] New code has docstrings explaining the WHY, not just the WHAT
- [ ] New modules registered in `bot.py:build_mcp_servers()` if they expose tools
- [ ] State paths go through `paths.py`, not hardcoded
- [ ] No secrets, tokens, or real personal identifiers in the diff
- [ ] If a feature is documented in `README.md`, the doc matches the code
