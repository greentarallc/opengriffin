# Migration

Coming from Hermes Agent or OpenClaw? Built-in migration imports memory, cron jobs, and recent sessions in one command.

## From Hermes Agent

```bash
griffin migrate from-hermes
# or with a custom source
griffin migrate from-hermes --src ~/.hermes
```

What gets ported:

| Hermes source | Destination | Notes |
|---|---|---|
| `~/.hermes/memories/MEMORY.md` | `~/.opengriffin/memories/MEMORY.md` | Merged with `§` separator if existing |
| `~/.hermes/memories/USER.md` | `~/.opengriffin/memories/USER.md` | Same merge logic |
| `~/.hermes/memories/SOUL.md` | `~/.opengriffin/memories/SOUL.md` | Same merge logic |
| `~/.hermes/cron/jobs.json` | `~/.opengriffin/jobs.json` | Schema translated to OpenGriffin format |
| `~/.hermes/channel_directory.json` | `identity.json` | Per-platform handles linked to a single account |
| `~/.hermes/state.db` | `echo memory recent tier` | Last 50 user messages imported as previews |
| `~/.hermes/scripts/*.py` | `~/.opengriffin/scripts/` | Pre-run scripts for cron jobs |

The migration is **idempotent** — safe to run twice. Existing entries aren't duplicated (merge respects the `§` separator).

### What's NOT ported

- Hermes-specific gateways (Discord, Slack, etc.) — re-configure these in OpenGriffin's `.env`
- Atropos RL training data — research-grade, no analog
- Tirith pre-execution policies — replaced by `security_scan`
- FTS5 session search — OpenGriffin has substring search; FTS index is on the roadmap
- Container sandboxes (Docker / Modal / Daytona) — not in OSS Core

### After migration

```bash
opengriffin doctor                          # confirm provider + token
cat ~/.opengriffin/memories/MEMORY.md       # eyeball
opengriffin run                              # start fresh
```

The migration tool DOES NOT delete the Hermes install. Both can coexist.

## From OpenClaw

```bash
griffin migrate from-openclaw
# or with a custom source
griffin migrate from-openclaw --src ~/.openclaw
```

What gets ported:

| OpenClaw source | Destination | Notes |
|---|---|---|
| `memory.md` (or `memories/MEMORY.md`) | `~/.opengriffin/memories/MEMORY.md` | Merged with separator |
| `*.skill.md` files (anywhere) | `~/.claude/skills/<name>/SKILL.md` | Frontmatter auto-added if missing |
| `config.{yaml,toml,json}` | `~/.opengriffin/openclaw.{ext}.imported` | Saved for manual review (no auto-translate) |

### What's NOT ported

OpenClaw's config syntax differs from OpenGriffin's. We save the imported config to a side file rather than auto-translating; you decide what to copy over.

## Manual migration from anywhere

Both tools rely on plain markdown for state. If your previous tool stored memory in any markdown file, you can hand-merge it:

```bash
# Append to MEMORY.md with a separator
echo "" >> ~/.opengriffin/memories/MEMORY.md
echo "§" >> ~/.opengriffin/memories/MEMORY.md
echo "" >> ~/.opengriffin/memories/MEMORY.md
cat /path/to/old/memory.md >> ~/.opengriffin/memories/MEMORY.md
```

Or split into entries first (one fact per `§` block) for cleaner consolidation later.

## Coming from a hosted SaaS (ChatGPT Plus, Claude Pro, etc.)

These tools generally don't expose your full history. Best path:

1. Export what you can via their UI (account → data export)
2. Hand-curate the most durable preferences into `~/.opengriffin/memories/USER.md`
3. Don't try to import every chat — most of it isn't useful long-term

The 4:30am self-improvement loop will rebuild the high-leverage memory automatically as you use OpenGriffin.

## Adding a migration source

If you'd like to support another tool (LangChain Memory, AutoGPT, Letta, MemGPT, etc.), see [CONTRIBUTING.md](../CONTRIBUTING.md). The pattern is:

1. Add a new function to `src/opengriffin/migrate.py` named `_port_<source>_<artifact>`
2. Register a typer subcommand `from-<source>` that calls them in order
3. Document the schema mapping in this file

PR welcome.
