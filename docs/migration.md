# Migration

`griffin migrate` ports state from a prior agent runtime into OpenGriffin's
canonical `~/.opengriffin/` layout. Each subcommand reads a known source
directory and writes into the destination paths below. All importers are
idempotent.

## Available importers

Run `griffin migrate --help` to see every importer registered in your install.

### `griffin migrate from-hermes`

Imports from a Hermes Agent install. Source defaults to `~/.hermes`; override
with `--src <path>`.

| Source | Destination | Notes |
|---|---|---|
| `<src>/memories/MEMORY.md` | `~/.opengriffin/memories/MEMORY.md` | Merged with `§` separator if existing |
| `<src>/memories/USER.md` | `~/.opengriffin/memories/USER.md` | Same merge logic |
| `<src>/memories/SOUL.md` | `~/.opengriffin/memories/SOUL.md` | Same merge logic |
| `<src>/cron/jobs.json` | `~/.opengriffin/jobs.json` | Schema translated to OpenGriffin format |
| `<src>/channel_directory.json` | `~/.opengriffin/identity.json` | Per-platform handles linked to a single account |
| `<src>/state.db` | `echo memory recent tier` | Last 50 user messages imported as previews |
| `<src>/scripts/*.py` | `~/.opengriffin/scripts/` | Pre-run scripts for cron jobs |

The importer does NOT delete the source install. Both layouts can coexist.

### `griffin migrate from-openclaw`

Imports from an OpenClaw install. Source defaults to `~/.openclaw`; override
with `--src <path>`.

| Source | Destination | Notes |
|---|---|---|
| `<src>/memory.md` or `<src>/memories/MEMORY.md` | `~/.opengriffin/memories/MEMORY.md` | Merged with separator |
| `<src>/**/*.skill.md` | `~/.claude/skills/<name>/SKILL.md` | Frontmatter auto-added if missing |
| `<src>/config.{yaml,toml,json}` | `~/.opengriffin/openclaw.{ext}.imported` | Saved verbatim — no auto-translate |

Config files are saved alongside the imported state for manual review rather
than translated, since config syntax differs meaningfully across tools.

## Hosted SaaS (ChatGPT Plus, Claude Pro, etc.)

Hosted services rarely expose full conversation history. Best path:

1. Export what you can via the vendor's account → data-export flow.
2. Hand-curate the most durable preferences into `~/.opengriffin/memories/USER.md`.
3. Don't try to import every chat — most of it isn't useful long-term.

The 4:30am self-improvement loop will rebuild the high-leverage memory
automatically as you use OpenGriffin.

## Manual migration from anywhere

If your previous tool stored memory as plain markdown, append it directly:

```bash
echo ""  >> ~/.opengriffin/memories/MEMORY.md
echo "§" >> ~/.opengriffin/memories/MEMORY.md
echo ""  >> ~/.opengriffin/memories/MEMORY.md
cat /path/to/old/memory.md >> ~/.opengriffin/memories/MEMORY.md
```

Or split into entries first (one fact per `§` block) for cleaner consolidation later.

## After any migration

```bash
opengriffin doctor                          # confirm provider + token are visible
cat ~/.opengriffin/memories/MEMORY.md       # eyeball the merge
opengriffin run                             # start fresh
```

## Adding a new importer

If you'd like to support another previous runtime (LangChain Memory, AutoGPT,
Letta, MemGPT, etc.), see [CONTRIBUTING.md](../CONTRIBUTING.md). The pattern is:

1. Add a function to `src/opengriffin/migrate.py` named `_port_<source>_<artifact>`.
2. Register a typer subcommand `from-<source>` that calls them in order.
3. Document the schema mapping in this file.

PRs welcome.
