# JOURNEY.md

## How OpenGriffin built itself

It started as a workaround.

In late 2025 I was running a Telegram bridge for Claude that someone else had written. It hit a wall. Claude Max billing limits started biting hard, mid-conversation, and the bridge had no graceful way to drop down to a cheaper model or queue. I cracked it open intending to add a fallback. An hour in I had a fork. By the end of the weekend I had a fresh repo and the realization that I didn't want a patched bridge — I wanted a long-running agent of my own.

So I built one. Plain Python, [`python-telegram-bot`](https://python-telegram-bot.org/), and the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) underneath. The first version could read a message, call a tool, and reply. It had no memory, no schedule, no skills. It forgot everything between turns. But it ran on my own keys, on my own machine, and it didn't fall over when Anthropic threw 429s.

Then it got greedy.

The first thing I added was **memory** — three flat markdown files (`MEMORY.md`, `USER.md`, `SOUL.md`) that load fresh into every session, with the agent allowed to edit them mid-conversation. The second was a **journal** — append-only, one file per day, capturing every conversation and every tool call. Together those two changes turned a chatbot into something that compounded: it remembered who I was and what I'd asked it to do last Tuesday at 9 PM.

Skills came next. The agent was allowed to author its own. The first was a 12-line file teaching it to keep a daily standup. The hundredth was a multi-agent orchestrator. Today there are **650+ skills** in `~/.claude/skills/`, organized into categories the agent picked itself. Most of them I have never read.

After that the architecture filled in fast:

- **Cron** so it could schedule its own work — including the **4:30 AM self-improvement loop** that reads yesterday's journal entries and proposes new skills.
- **Webhooks** so external events (Stripe, GitHub, Linear) could nudge it.
- **Voice in / voice out**, Whisper for transcription, edge-tts for replies.
- **Browser automation** via Playwright MCP.
- **Approval flows** with inline-keyboard confirm gates for destructive actions.
- **Checkpoints + rollback**, so a crashed conversation could resume — or branch.
- **Kanban**, a shared board where multiple agent workers claim, block, and complete tasks in parallel.
- **Sub-conversation topics**, so the journal became searchable by theme, not just date.

By April the 4:30 AM run was reliably proposing better versions of itself. I'd wake up to a kanban full of self-suggested PRs. Some I merged. Some I argued with. A few it argued back about, citing earlier journal entries by date.

In May I made one more change: I rebranded the project as **OpenGriffin** and asked the running instance to draft its own [README](README.md), [dashboard module](src/opengriffin/dashboard/server.py), and the [JOURNEY.md](JOURNEY.md) you are reading right now.

It did. The evidence is auditable end-to-end:

- **Kanban tasks.** Each artifact has a row in `dogfood/kanban.json` showing it created, claimed, and completed by the agent — with timestamps and the worker's session ID.
- **Journal entries.** The 4:30 AM loop appended entries that day describing the work; they're under `dogfood/journal/`.
- **Session IDs.** Conversation IDs survive restarts via `sessions.json`, and every transcript is preserved at `sessions/<session_id>.jsonl`. Grep any line in this file back to the run that produced it.

You're reading this because the agent wrote it. Welcome.
