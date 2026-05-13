# GitHub repo settings cheatsheet

Paste-ready values for https://github.com/greentarallc/opengriffin/settings.

## About → Description

```
Self-evolving personal AI agent. Telegram-first. Multi-provider BYO key. Persistent memory, daily journal, skill graph, dream cycle. Free forever. Apache 2.0.
```

## About → Website

```
https://opengriffin.com
```

## About → Topics (comma-separated)

```
ai, agent, claude, anthropic, telegram-bot, llm, oss, apache2, python, mcp, model-context-protocol, personal-assistant, self-hosted, byo-key, autonomous-agents, openai, gemini, deepseek, agentic, self-improving
```

## Settings → General → Features

- ✅ Wikis — disable (use `docs/` in the repo)
- ✅ Issues — keep on
- ✅ Sponsorships — opt-in if you want
- ✅ Preserve this repository
- ✅ Discussions — turn ON (lets users ask questions without filing issues)
- ❌ Projects — off unless you actively use them

## Settings → General → Pull Requests

- ✅ Allow squash merging
- ❌ Allow merge commits (keeps `main` clean)
- ❌ Allow rebase merging
- ✅ Always suggest updating pull request branches
- ✅ Automatically delete head branches

## Settings → Branches → Branch protection rule for `main`

- ✅ Require a pull request before merging
- ✅ Require status checks (after CI runs at least once: select `test (3.11)` and `test (3.12)`)
- ✅ Require branches to be up to date before merging
- ✅ Do not allow bypassing the above settings

## Settings → Pages

If you want a fallback github.io deploy:

- Source: Deploy from a branch
- Branch: `main` / folder: `/website`
- Save

(Vercel is the primary deploy via `vercel.json`. GitHub Pages is just a backup.)

## Settings → Social preview

Upload `assets/social-card.png` (convert the SVG first — see `assets/README.md`).

## Settings → Secrets and variables → Actions

If you set up CI tokens for PyPI publishing later:
- `PYPI_API_TOKEN` (for `uv publish`)

For the v0.1 launch you don't need any secrets.

## Settings → Code security → Code scanning

- Enable Dependabot alerts (free)
- Enable Dependabot security updates (free)
- Code scanning with default CodeQL setup (free for public repos)

These are all one-click enables and add real security signal at zero cost.
