# Memory

OpenGriffin has six memory layers. They compose. None require a database.

## The six layers

| Layer | File | Purpose | Lifespan |
|---|---|---|---|
| `MEMORY.md` | `~/.opengriffin/memories/MEMORY.md` | Environment, project conventions, lessons | persistent, capped at 2200 chars |
| `USER.md` | `~/.opengriffin/memories/USER.md` | User profile + preferences | persistent, capped at 1375 chars |
| `SOUL.md` | `~/.opengriffin/memories/SOUL.md` | Personality / voice | persistent, no cap |
| `CONSTRAINTS.md` | `~/.opengriffin/memories/CONSTRAINTS.md` | Hard rules the agent must NEVER violate | persistent, override-proof |
| **Echo Memory** | `~/.opengriffin/memories/echo/{tier}/*.md` | Autobiographical hierarchical (vivid → ancient) | tier-based decay |
| **Daily journal** | `~/.opengriffin/memories/JOURNAL.md` | Self-improvement entries | persistent, capped at 90 entries |

All loaded fresh into every session's system prompt at session start.

## How they compose in the system prompt

```
1. CONSTRAINTS.md             ← absolute rules, override-proof
2. SOUL.md                    ← personality
3. MEMORY.md (environment)    ← what the bot needs to remember about the world
4. USER.md (profile)          ← what the bot needs to remember about you
5. Per-chat sysprompt (opt)   ← chat-specific addendum
6. (Echo Memory + JOURNAL accessible via tools, NOT auto-injected)
```

CONSTRAINTS go first because order matters — they take precedence in case of conflict.

## MEMORY.md / USER.md

Two flat markdown files. Entries separated by a `§` line.

```markdown
The production deploy uses Cloudflare Workers + R2.
§
PR titles must follow conventional commit format.
§
Homebrew Node 24 is at /opt/homebrew/opt/node@24/bin.
```

The agent edits them via three MCP tools:

- `memory_add target=memory|user content="..."` — append a new entry
- `memory_replace target find="..." replace="..."` — substring-find, full-replace
- `memory_remove target find="..."` — drop entries containing substring

When the file approaches its cap (default 80%), the daily self-improvement turn at 4:30am consolidates duplicates and drops stale entries.

### What goes in MEMORY vs USER

| Kind of fact | Goes in |
|---|---|
| "User prefers terse responses" | USER.md |
| "User is in US Central time" | USER.md |
| "User wants daily summaries at 7am" | USER.md |
| "Production deploy uses CF Workers" | MEMORY.md |
| "Tests fail on Python 3.10 because X" | MEMORY.md |
| "PR titles must follow conventional commits" | MEMORY.md |

Rule of thumb: **USER.md is what changes if the user changes; MEMORY.md is what changes if the project changes**.

## SOUL.md (personality)

A free-form markdown file describing voice, tone, and behavior preferences. Loaded *after* CONSTRAINTS but *before* MEMORY/USER.

Six built-in presets in `memories.example/SOUL.presets.md`:

- `default` — direct, capable, concise
- `terse` — minimum words, no preamble
- `mentor` — patient senior engineer
- `ruthless` — push back on assumptions
- `detective` — hypothesis-driven
- `night-owl` — extra cautious for late hours

Apply via Telegram: `/personality terse`

Or edit `~/.opengriffin/memories/SOUL.md` directly. Future sessions pick it up.

## CONSTRAINTS.md

Hard rules. Never overridden. Loaded at the very top of the system prompt with explicit "violating these is a failure" language.

```markdown
- Never push to main without explicit approval in this chat
- Never spend more than $5 in a single action without confirming
- Never email contacts in my "personal" Telegram label about work
```

The agent will refuse requests that would violate constraints, even if you write a clever prompt asking it to.

## Echo Memory (hierarchical autobiographical)

Four time tiers. Older entries decay automatically into less-detailed summaries.

| Tier | File pattern | Source granularity | Age cutoff |
|---|---|---|---|
| `vivid` | `echo/vivid/YYYY-MM-DD.md` | Full session-level entries | < 7 days |
| `recent` | `echo/recent/YYYY-MM-DD.md` | Day-summaries | 7–30 days |
| `fading` | `echo/fading/YYYY-Wxx.md` | Week-summaries | 30–365 days |
| `ancient` | `echo/ancient/YYYY-MM.md` | Month-summaries | > 365 days |

The 4:45am consolidation job rolls older entries up the hierarchy nightly, summarizing as it goes. Rule of thumb: vivid keeps every detail; ancient keeps only what would matter a year from now.

### Memory receipts

Every Echo entry has a citation token:

```
[echo:vivid/2026-05-06:abc12345]
```

The agent emits these *inline* when answering recall queries:

> User: "When's my anniversary?"
> Agent: "Your anniversary is May 12 [echo:recent/2026-04-22:7f3a4b88]."

Tap the token (in supporting clients) or grep the file to see the exact session that established the fact.

### Using Echo

```
mcp__echo_memory__echo_remember content="My anniversary is May 12"
mcp__echo_memory__echo_recall query="anniversary"
```

The recall tool searches all four tiers, weights by recency × tier, and returns hits with their receipt tokens. The agent uses recall transparently — it won't claim a fact unless it can produce a receipt.

## Daily journal

`~/.opengriffin/memories/JOURNAL.md` is appended once per day at 4:30am by the self-improvement loop. Each entry:

```markdown
## 2026-05-06

**Recap:** 3-5 line summary of what happened
**Memory:** "consolidated 3 entries; added 2"
**Failures:** "(none)" or list with severity
**Suggested skills:** "(none)" or proposals
**Stalled kanban:** "(none)" or list
**Notes:** anything else worth remembering
```

Capped at the last 90 entries. Older entries are not deleted — they're rotated by trimming the file (keeping the markdown header + the last 90 entries).

View with `/journal` in Telegram or `opengriffin journal` from CLI.

## Drift detection

The `drift` module nightly compares USER.md against recent JOURNAL behavior, using the agent's own reasoning to detect contradictions.

> "3 months ago you told me you hated meetings; today you scheduled five. Want to talk about it?"

Logged to `~/.opengriffin/drift.jsonl`. Use `drift_check` on demand or wait for the 5am cron.

## How memory survives bot restarts

- All memory files are plain markdown on disk — restart loses nothing
- `sessions.json` maps `chat_id` → `session_id` for resume
- Claude Agent SDK stores transcripts under `~/.claude/projects/<encoded-cwd>/<session_id>.jsonl`
- After daily 4am reset, the previous session is *archived* (still readable via `/sessions` and `/resume <id>`), not deleted

## Importing memory from a prior runtime

Use the migration importers documented in [migration.md](migration.md):

```bash
griffin migrate --list                   # show every available importer
griffin migrate from-<source>            # run one
```

Each importer ports MEMORY/USER/SOUL into the canonical
`~/.opengriffin/memories/` layout, merging with `§` separators so re-runs
don't duplicate.

## Editing memory by hand

All memory files are plain markdown — `vim ~/.opengriffin/memories/MEMORY.md` works. The agent picks up your edits on the next session start.

There's no schema enforcement. The `§` separator is a convention; the agent reads everything between separators as one entry.
