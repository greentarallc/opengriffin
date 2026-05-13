# OpenGriffin

> A self-evolving personal agent that lives in your Telegram. Bring your own model, your own skills, your own memory.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/greentarallc/opengriffin/actions/workflows/ci.yml/badge.svg)](https://github.com/greentarallc/opengriffin/actions/workflows/ci.yml)
[![Telegram](https://img.shields.io/badge/Telegram-bot-26A5E4.svg?logo=telegram&logoColor=white)](https://core.telegram.org/bots)

OpenGriffin is a long-running agent process that talks to you on Telegram, keeps a journal, schedules its own work, learns new skills on the fly, and remembers what matters across sessions. It is built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) and degrades gracefully to OpenAI, OpenRouter, Azure, Gemini, Mistral, Groq, Bedrock, local Ollama, and 13 more backends — bring whatever key you have.

---

## Why OpenGriffin

- **Self-evolving skill graph.** The agent authors, edits, and retires its own skills at runtime. No redeploy. New capabilities ship inside a conversation.
- **Daily journal at 4:30 AM.** Every conversation, decision, and tool call is appended to a structured journal. A nightly self-improvement loop reads yesterday's entries, summarizes them, and proposes new skills.
- **21 AI providers, BYO key.** Claude Max OAuth, Anthropic, OpenAI, OpenRouter, Azure, Gemini, Mistral, Cohere, Groq, Together, Fireworks, DeepSeek, HuggingFace, Perplexity, xAI, Bedrock, Cerebras, NVIDIA NIM, Lambda Labs, Novita, Ollama. Switch with one env var.
- **Persistent memory: MEMORY / USER / SOUL.** Three flat markdown files load fresh into every session. `MEMORY.md` is the environment, `USER.md` is the profile, `SOUL.md` is the voice.
- **Multi-surface.** Telegram is the front door, but the same brain answers via CLI, webhooks, and voice notes.
- **Skill auto-discovery.** Drop a markdown file into `~/.claude/skills/`, and the agent picks it up on next turn — no registry, no config.
- **Voice round-trip.** `faster-whisper` transcribes inbound voice notes; `edge-tts` speaks replies in the user's preferred neural voice.
- **Browser automation via Playwright MCP.** Screenshots, scraping, end-to-end clicks. The agent can drive a real Chromium.
- **Kanban built in.** Multiple agent workers claim, block, and complete tasks against a shared board. Long plans get parallelized.
- **Checkpoints + rollback.** Conversation snapshots survive crashes. The agent can replay or branch off any prior point.
- **Approval inline buttons.** Risky actions ask first via Telegram inline keyboards. Confirm or deny with a tap; nothing destructive runs unsupervised.

---

## The 12 killer features

| # | Feature | What it does |
|---|---|---|
| 1 | **Skill Hub** | Install community skills directly from GitHub URLs with license auto-check, signing, and reputation tracking by *outcome*, not stars. |
| 2 | **Echo Memory + Receipts** | Autobiographical hierarchical memory (vivid → recent → fading → ancient). Every recalled fact comes with a citation receipt like `[echo:vivid/2026-05-06:abc123]` linking back to the source session. |
| 3 | **Ambient Trigger Mesh** | Compose triggers from cron, webhook, or polled URLs → optional LLM yes/no predicate → skill or prompt action. The agent acts before you notice the problem. |
| 4 | **Agent Pods** | Multiple agent personas with distinct SOUL files but shared memory. Add them to a group chat, watch them debate, converge. |
| 5 | **Agentic Wallet (x402)** | The agent can pay for things — sandbox wallet + per-skill spending caps + Telegram inline-button approval. Pays only after you tap. |
| 6 | **Soul Sync** | Mines your past chats for writing voice (sentence length, contractions, recurring phrases). Builds a `VOICE.md` the agent uses to draft *as you*. |
| 7 | **Provider Routing Auctions** | Lightweight classifier scores each prompt 0–3, routes to cheapest tier that can answer. Heavy thinking goes to Claude Opus / o1; "summarize this" goes to Groq for $0.0001. |
| 8 | **Drift Detection** | Nightly scan of `USER.md` against recent journal entries. Flags contradictions: _"3 months ago you told me you hated meetings; today you scheduled five."_ |
| 9 | **Self-Healing Skills** | When a skill fails 3+ times in a week, the agent debugs it, proposes an updated `SKILL.md`, and asks for approval before applying. |
| 10 | **Skill Graph Strategy** | Reads your usage to recommend missing skills based on co-occurrence, flags never-used skills, and surfaces your top-used ones. |
| 11 | **Memory Receipts** | Every claim the agent makes can be traced. Tap a receipt token to see the exact session and turn that established the fact. |
| 12 | **Reputation Ledger** | Signed JSON-LD profile (`/u/<handle>`) showing task count, approval rate, specialties, authored skills. A2A-discoverable for agent-to-agent trust. |

The frontier modules — **Personal World Model**, **Living Twin**, **Verifiable Refusal Proofs + Provable Forgetting**, **Generative Live UI**, **Mesa-Cognition Supervisor**, **Capability-Scoped Skill Leasing**, **Personal Causal Layer**, and the **Adversarial Improvement Market** — ship in addition. See [docs/frontier.md](docs/frontier.md) for the design notes.

---

## Nightly auto-loops

Every night, OpenGriffin runs without prompting:

| Time | Job | What |
|---|---|---|
| 04:00 | Daily session reset | Archives sessions; preserves the next morning a fresh slate while keeping recall |
| 04:30 | Self-improvement | Reads yesterday's transcripts, consolidates `MEMORY` / `USER`, writes `JOURNAL.md`, suggests skills |
| 04:45 | Echo memory consolidation | Rolls older sessions up the time hierarchy (vivid → recent → fading → ancient) |
| 05:00 | Drift detection | Surfaces contradictions in user model / behavior |
| 05:15 | World model retrain | Rebuilds the personal forecast from the event log |
| 05:30 | Mesa-cognition report | Scores the agent's own behavior for drift signatures |
| 05:45 | Causal discovery | Walks the event log for new cause→effect proposals |
| Sun 05:00 | Voice card refresh | Re-extracts writing-voice profile from past week's chats |
| per-trigger | Ambient triggers | All cron-based triggers from `triggers.json` |

---

## Quick start

```bash
# One-line install (clones, runs uv sync, writes a launchctl/systemd unit)
curl -fsSL https://raw.githubusercontent.com/greentarallc/opengriffin/main/scripts/install.sh | bash

# Or from source
git clone https://github.com/greentarallc/opengriffin.git
cd opengriffin
uv sync --all-extras
cp .env.example ~/.opengriffin/.env  # fill in TELEGRAM_BOT_TOKEN
uv run opengriffin doctor              # verify env + provider
uv run opengriffin run                 # start the bot
```

On first launch, OpenGriffin will:

1. Load `.env` from `~/.opengriffin/.env` (or `OPENGRIFFIN_HOME/.env` if you've overridden the path).
2. Detect available providers (Claude Max → Anthropic → OpenAI → Ollama).
3. Create `MEMORY.md`, `USER.md`, `SOUL.md`, and a `JOURNAL.md` under `~/.opengriffin/memories/`.
4. Drop you into a chat where the agent can already use tools.

```bash
# Use a specific provider
OPENGRIFFIN_PROVIDER=openrouter opengriffin run

# Diagnose the install
opengriffin doctor

# Run the nightly self-improvement loop manually
opengriffin improve

# Migrate state from a prior agent runtime (see docs/migration.md)
opengriffin migrate from-hermes
```

---

## Provider matrix

One env var (`OPENGRIFFIN_PROVIDER`) picks the backend. Full features (skills, MCP, hooks, sessions) on Claude; chat + function-calling fallbacks on every other provider.

| Provider | `OPENGRIFFIN_PROVIDER` | Required env | Default model |
|---|---|---|---|
| Claude (Max OAuth) | `claude` | _none — uses `~/.claude/.credentials.json`_ | `claude-opus-4-7` |
| Anthropic API | `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |
| OpenAI | `openai` | `OPENAI_API_KEY` | `gpt-4o` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` | `anthropic/claude-opus-4` |
| Azure OpenAI | `azure` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` | `gpt-4o` |
| Google Gemini | `gemini` | `GEMINI_API_KEY` | `gemini-2.5-pro` |
| Mistral | `mistral` | `MISTRAL_API_KEY` | `mistral-large-latest` |
| Cohere | `cohere` | `COHERE_API_KEY` | `command-r-plus` |
| Groq | `groq` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| Together AI | `together` | `TOGETHER_API_KEY` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| Fireworks AI | `fireworks` | `FIREWORKS_API_KEY` | `accounts/fireworks/models/llama-v3p3-70b-instruct` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| HuggingFace | `huggingface` | `HF_TOKEN` | `meta-llama/Llama-3.3-70B-Instruct` |
| Perplexity | `perplexity` | `PERPLEXITY_API_KEY` | `sonar-pro` |
| xAI (Grok) | `xai` | `XAI_API_KEY` | `grok-2-latest` |
| AWS Bedrock | `bedrock` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | `anthropic.claude-sonnet-4-6` |
| Cerebras | `cerebras` | `CEREBRAS_API_KEY` | `llama3.3-70b` |
| NVIDIA NIM | `nvidia` | `NVIDIA_API_KEY` | `meta/llama-3.1-405b-instruct` |
| Lambda Labs | `lambda` | `LAMBDA_API_KEY` | `hermes-3-llama-3.1-405b-fp8` |
| Novita | `novita` | `NOVITA_API_KEY` | `meta-llama/llama-3.1-70b-instruct` |
| Ollama (local) | `ollama` | `OLLAMA_HOST`, `OLLAMA_MODEL` | `llama3.1` |

The OpenAI-compatible providers all share a single connector under the hood — adding a new one is a short dict entry in `providers/openai_compatible.py:FLAVORS`.

---

## Configuration

Copy `.env.example` to `~/.opengriffin/.env` and fill in only the keys you intend to use.

| Variable | Purpose |
|---|---|
| `OPENGRIFFIN_HOME` | Override the runtime state root. Default `~/.opengriffin`. |
| `OPENGRIFFIN_PROVIDER` | Backend selection (see matrix above). Default `claude`. |
| `TELEGRAM_BOT_TOKEN` | BotFather token. Required to talk on Telegram. |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated Telegram user IDs. Empty = open to anyone. |
| `TELEGRAM_HOME_CHANNEL` | Default destination for cron output and proactive messages. |
| `FAL_KEY` | Enables fal.ai image generation tool. |
| `WEBHOOK_PORT` | HTTP port for the webhook gateway. Default `8645`. |
| `SELF_IMPROVE_CRON` | Cron expression for the nightly loop. Default `30 4 * * *`. |
| `CLAUDE_BOT_DISABLE_PLAYWRIGHT` | Set to `1` to skip browser automation. |

---

## Architecture

OpenGriffin is one Python package, one long-lived process, and a handful of orthogonal modules. Each does one thing and is replaceable.

```
src/opengriffin/
├── bot.py             # Telegram entrypoint; routes messages to the agent loop
├── cli.py             # `opengriffin` / `griffin` Typer CLI
├── paths.py           # Canonical filesystem layout (OPENGRIFFIN_HOME-rooted)
├── providers/         # 21 pluggable AI backends
│   ├── claude.py            # Claude Agent SDK (default; full features)
│   ├── anthropic_api.py     # Direct Anthropic API
│   ├── gemini.py            # Google Gemini
│   ├── cohere.py            # Cohere
│   ├── bedrock.py           # AWS Bedrock
│   ├── ollama.py            # Local models via Ollama
│   └── openai_compatible.py # 15 OpenAI-compatible flavors share one connector
├── memory.py          # MEMORY.md / USER.md / SOUL.md read/edit/cap logic
├── recall.py          # Long-term recall across journal entries
├── echo_memory.py     # Hierarchical autobiographical memory + citation receipts
├── topics.py          # Topic extraction and clustering for ambient memory
├── cron.py            # APScheduler bridge — agent-authored cron jobs
├── voice.py           # Whisper STT + edge-tts TTS pipeline
├── webhooks.py        # aiohttp gateway for inbound HTTP triggers
├── kanban.py          # Shared task board (claim / block / complete)
├── tools.py           # Tool registry: image gen, journal, kanban, send_message…
├── self_improve.py    # Skill authorship + nightly 4:30 AM loop
├── checkpoints.py     # Conversation snapshots; crash recovery + rollback
├── approvals.py       # Inline-keyboard confirm gate for destructive actions
├── redact.py          # Secret scrubbing on inbound + outbound payloads
├── world_model.py     # Personal predictive forecaster
├── twin.py            # Counterfactual sub-agent (Living Twin)
├── proofs.py          # Verifiable refusal + provable forgetting
├── gen_ui.py          # Generative UI with preference learning
├── mesa.py            # Mesa-cognition drift supervisor
├── skill_lease.py     # Capability-scoped skill leases (A2A)
├── causal.py          # Personal causal data layer
└── adversarial.py     # Adversarial improvement market
```

### Where state lives

| Path | Contents |
|---|---|
| `~/.opengriffin/memories/MEMORY.md` | Environment + project facts. Loaded into every system prompt. Capped at 2,200 chars. |
| `~/.opengriffin/memories/USER.md` | Stable user profile + preferences. Capped at 1,375 chars. |
| `~/.opengriffin/memories/SOUL.md` | The bot's voice and tone — edited to set personality. |
| `~/.opengriffin/memories/JOURNAL.md` | Append-only daily log of conversations and tool calls. |
| `~/.opengriffin/sessions.json` | Per-chat session resume state. |
| `~/.opengriffin/kanban.json` | Shared task board state. |
| `~/.opengriffin/jobs.json` | Scheduled jobs the agent has authored. |
| `~/.opengriffin/checkpoints/` | Crash-recovery snapshots of in-flight conversations. |
| `~/.opengriffin/usage.jsonl` | Per-call token + dollar accounting. |
| `~/.claude/skills/` | Self-evolving skill files. Auto-discovered each turn. Shared with other Claude Code installs. |

Override the root by setting `OPENGRIFFIN_HOME` before launch.

---

## Skills

Skills are markdown files with frontmatter. The agent reads them on demand and can also write new ones during a conversation.

```markdown
---
name: morning-briefing
description: Compile calendar + journal + weather into a 5-line digest.
trigger: /briefing OR mornings at 7:30 AM
---

1. Pull today's calendar from Google.
2. Read the last journal entry.
3. Grab weather for the user's location.
4. Format as 5 lines, no preamble.
```

The agent decides when a skill is relevant. Users can invoke them with `/skill-name`. The `self_improve` module governs creation, editing, and deletion — every change is journaled.

---

## Built by itself

This README, the [JOURNEY.md](JOURNEY.md), the landing site at [apps/web](apps/web), and the [dashboard module](src/opengriffin/dashboard/server.py) were drafted by a running OpenGriffin instance.

The audit trail is in [dogfood/](dogfood/):

- **Kanban tasks.** [`dogfood/kanban.json`](dogfood/kanban.json) records each artifact — created, claimed, blocked, completed — with timestamps and the worker's session ID.
- **Journal entries.** [`dogfood/journal/`](dogfood/journal/) holds the daily log entries the agent wrote while working. They include tool calls, file diffs, and the agent's own reasoning.

A self-authored repo where you cannot trace the work back to a real run is not dogfooding, it's marketing. The chain of evidence is intentional.

---

## Contributing

We welcome PRs of every size — typo fixes, new providers, new tools, new skills. See [CONTRIBUTING.md](CONTRIBUTING.md) for:

- Local dev setup (`uv`, `ruff`, `pytest`).
- The skill authoring guide.
- How to add a new provider (a short dict entry for OpenAI-compatible ones).
- The PR review bar (tests + a journal entry from a real session showing it works).

If you are unsure whether something is in-scope, open a discussion first — the project is opinionated about staying small at the core.

---

## License

OpenGriffin is released under the [Apache License 2.0](LICENSE). You are free to fork, embed, modify, and run it commercially. A copy of the license must travel with redistributions.

---

<sub>OpenGriffin is not affiliated with Anthropic, OpenAI, Google, Microsoft, AWS, Mistral, Cohere, Groq, or any other provider listed above. "Claude" is a trademark of Anthropic, PBC.</sub>
