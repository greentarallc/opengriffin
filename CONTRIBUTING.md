# Contributing to OpenGriffin

Thanks for considering a contribution. OpenGriffin is built to compound — every well-scoped PR makes the next one easier. This guide tells you how to ship one without wasted cycles.

## TL;DR

1. **Open an issue first** for anything beyond a typo or one-line bug fix.
2. **Branch from `main`**, name it `feat/<short-name>` or `fix/<short-name>`.
3. **Run the tests + linter** before pushing. They are the contract.
4. **Write tests** for new logic. PRs without tests get pushed back unless you explain why none are possible.
5. **Update docs in the same PR** as the code. README, docstrings, and `examples/` should never lag the code.
6. **Sign your commits** with the [Developer Certificate of Origin](https://developercertificate.org/). `git commit -s` adds the line.

---

## Project structure

```
opengriffin/
├── src/opengriffin/        Python package — the agent runtime
│   ├── bot.py               Telegram entry point
│   ├── cli.py               opengriffin / griffin CLI
│   ├── memory.py            MEMORY/USER/SOUL/JOURNAL
│   ├── echo_memory.py       Hierarchical autobiographical memory
│   ├── triggers.py          Cron / webhook / poll → predicate → action DAG
│   ├── workers.py           Long-running background agents
│   ├── critic.py            Adversarial-twin reviewer
│   ├── capabilities.py      Signed capability tokens
│   ├── ...                  ~30 single-purpose modules
│   ├── providers/           21 AI provider adapters
│   ├── gateways/            7 platform adapters (Telegram, Discord, …)
│   └── dashboard/           SSE observability dashboard
├── bundled_skills/          Apache-2.0 bundled SKILL.md files
├── docs/                    Long-form documentation
├── examples/                Ready-to-run config snippets
├── scripts/install.sh       One-line installer for end users
├── tests/                   pytest suite
├── website/                 opengriffin.com landing source
└── pyproject.toml           Package definition
```

A new feature usually lands in:

- `src/opengriffin/<feature>.py` (the module)
- `tests/test_<feature>.py` (unit tests)
- README feature row + bullet in `docs/features.md` (if applicable)
- Optional: `examples/<feature>.json` (a concrete config example)

---

## Development setup

### Prerequisites
- Python 3.11+
- `uv` (preferred) or `pip` + `venv`
- Telegram bot token (from `@BotFather`) for end-to-end testing
- At least one AI provider key (Anthropic, OpenAI, etc.) or local Ollama

### First-time setup

```bash
git clone https://github.com/greentarallc/opengriffin
cd opengriffin
uv sync --all-extras           # installs deps + dev tools
cp .env.example .env           # then edit with your keys
uv run pytest                   # confirms install
uv run opengriffin doctor       # confirms config
```

### Running locally

```bash
# Foreground (ctrl-c to stop)
uv run opengriffin run

# One-shot a prompt without starting the bot
uv run opengriffin ask "summarize today's journal"

# Open the dashboard
uv run opengriffin dashboard
```

---

## What to work on

Good first issues are tagged [`good first issue`](https://github.com/greentarallc/opengriffin/labels/good%20first%20issue). Beyond those, the highest-leverage areas:

| Area | Why |
|---|---|
| **Provider adapters** | Each new backend in `src/opengriffin/providers/` adds dozens of models. Adapter shape is consistent — copy `openai.py` and rewire base URL + auth. |
| **Gateway adapters** | `src/opengriffin/gateways/` is where new platforms (Mastodon, IRC, Twilio SMS) plug in. The `Message` interface is the contract. |
| **Bundled skills** | Pure markdown. Add Apache-2.0-licensed skills in `bundled_skills/<name>/SKILL.md`. They ship in the next release. |
| **Migration importers** | `src/opengriffin/migrate.py` ships importers for prior agent runtimes — add more sources (LangChain Memory, AutoGPT runs, Letta, etc.). |
| **Docs** | The agent space moves fast. Out-of-date docs are worse than missing docs. PRs welcome. |
| **Performance** | Cold-start time, memory loading speed, dashboard SSE throughput — all measurable, all improvable. |

### What we're NOT looking for

- **Telemetry / analytics that phone home.** Anything that emits data without explicit user opt-in will be closed.
- **Hosted-only features.** OSS Core stays self-hostable. If a feature can't run on a Mac mini under a kitchen counter, it doesn't belong here.
- **Provider lock-in.** A code path that only works on one model breaks the BYO-key promise.
- **Closed-source dependencies** beyond the existing AI providers themselves.
- **Telemetry libraries** even when they're "off by default."

---

## Coding standards

### Python

- **Format**: `ruff format` (configured in `pyproject.toml`).
- **Lint**: `ruff check` — must be clean. We allow `# noqa: <rule>` for documented exceptions.
- **Type hints**: required on public functions. `mypy --strict` should pass for `src/opengriffin/`.
- **Imports**: standard library first, third-party second, local third. `ruff` enforces.
- **No unused code**: dead branches, unused imports, commented-out blocks all get flagged.
- **Docstrings**: every public function and class. Module-level docstring on every file.

### Naming

- Files: `snake_case.py`
- Classes: `CamelCase`
- Functions / variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- MCP tool names: `feature_action` (e.g. `memory_add`, `worker_spawn`)
- MCP server constants: `<FEATURE>_SERVER` (e.g. `MEMORY_SERVER`)

### Module shape

A new feature module should:

1. Open with a docstring explaining what, why, and where state lives.
2. Define dataclasses or constants near the top.
3. Provide a small functional API (load, save, query, mutate).
4. Wrap that API in `@tool` decorated MCP tools at the bottom.
5. Expose `<FEATURE>_SERVER = create_sdk_mcp_server(...)`.

See `src/opengriffin/echo_memory.py` for a canonical example.

### Tests

- `pytest` with `pytest-asyncio`. Tests live under `tests/`.
- Each module in `src/opengriffin/<x>.py` should have `tests/test_<x>.py`.
- Use the `tmp_path` fixture for filesystem state.
- Never write to `~/.opengriffin/` or any user dir from a test.
- Mock provider HTTP calls with `httpx.MockTransport` or `responses`.

```python
# Good
def test_memory_add_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "MEMORY.md")
    ok, msg = memory.add_entry("memory", "test content")
    assert ok
    assert "test content" in (tmp_path / "MEMORY.md").read_text()
```

### Commit messages

```
<area>: <imperative summary, ≤72 chars>

Body explaining WHY (the diff already shows what). Wrap at 72 cols.
Reference issues with #N. Mention breaking changes loudly.
```

Examples:
- `providers: add Mistral adapter with Codestral support`
- `echo_memory: drop trailing whitespace before storing receipts`
- `fix: deadman timer was not resetting on voice messages`

We squash-merge most PRs; your branch's intermediate commits don't need to be perfect, but the final PR title + body should be clean.

### Branches

- `main` — protected, always green, deploy-ready.
- `feat/<name>` — new features.
- `fix/<name>` — bug fixes.
- `docs/<name>` — documentation only.
- `chore/<name>` — refactors, deps, tooling.

---

## Pull request workflow

1. **Discuss in an issue first** for anything beyond a typo or trivial fix. Saves both of us time.
2. **Fork → branch → push → PR.** Target `main`.
3. **PR description** should answer:
   - What does this change?
   - Why is it needed?
   - How was it tested?
   - Does it touch the user-facing surface? (CLI flags, env vars, MCP tools, files in `~/.opengriffin/`)
4. **CI must be green.** Tests + ruff + mypy.
5. **At least one maintainer review.** Bigger PRs may get two.
6. **Squash-merge** by default. Keep commits clean for `main`'s log.

### What gets a fast review

- Single concern per PR (don't bundle a feature with a refactor)
- Existing tests still pass + new tests for new code
- Docs updated in the same PR
- Under ~500 LOC of substantive change
- Commit message and PR description match the diff

### What stalls

- "I'll add tests later" PRs
- Drive-by refactors mixed with feature changes
- New runtime deps without justification (every dep is debt)
- Anything that introduces telemetry, accounts, or hosted-service dependencies

---

## Adding a new provider

1. Create `src/opengriffin/providers/<name>.py`.
2. Inherit shape from the closest existing provider:
   - `claude.py` — full Agent SDK (skills, MCP, hooks)
   - `anthropic_api.py` — direct API call
   - `openai_compatible.py` — for any OpenAI-API-compatible service (most are)
3. Register the provider in `src/opengriffin/providers/__init__.py`.
4. Add a test in `tests/providers/test_<name>.py` that mocks the HTTP call.
5. Update README provider matrix and `.env.example`.
6. Optionally: add an entry to `docs/providers.md`.

A new provider PR is usually ~150 lines including tests.

---

## Adding a new gateway

Gateways are platform adapters in `src/opengriffin/gateways/`. They normalize platform events into a single `Message` shape and call the bot's handler.

1. Create `src/opengriffin/gateways/<platform>.py` implementing the `Gateway` protocol from `gateways/__init__.py`.
2. Add the platform to `Message.platform` Literal.
3. Add startup config to `bot.py` (env-var-gated so the gateway stays optional).
4. Test with the platform's official sandbox/test environment if available.
5. Document the bot setup steps in `docs/gateways/<platform>.md`.

Existing gateways (`telegram.py`, `discord.py`, `slack.py`, `email.py`, `imessage.py`, `signal.py`, `matrix.py`) are the reference shapes. Telegram is the canonical implementation.

---

## Adding a bundled skill

Bundled skills are Apache-2.0 markdown files in `bundled_skills/<name>/SKILL.md`. They install into `~/.claude/skills/` on first run.

A skill must:

1. Have YAML frontmatter with `name`, `description`, `license: Apache-2.0`, `author`.
2. Be entirely original content (do not adapt third-party material without explicit permission and license review).
3. Solve one job well. If it's vague or sprawling, split it.
4. Include concrete examples — what the skill does, not just abstract guidance.

Existing bundled skills (writing-plans, systematic-debugging, tdd-workflow, etc.) are the reference templates.

---

## Security and responsible disclosure

If you find a security issue **do not file a public issue**. Instead:

- Email: `security@opengriffin.com`
- We'll respond within 72 hours with a triage decision.
- Critical vulnerabilities (RCE, secret extraction, privilege escalation) get expedited review and a coordinated disclosure timeline.

For non-critical hardening ideas (better defaults, rate limits, additional pre-exec scanner patterns), open a regular issue.

OpenGriffin runs arbitrary tool calls on the user's machine. Any change that **expands the agent's blast radius** without an explicit user opt-in is a hard no.

---

## License

By contributing, you agree your contributions are licensed under the [Apache License 2.0](LICENSE), the same as the rest of the project.

You also confirm via `git commit -s` that you wrote the code or have permission to submit it (the [Developer Certificate of Origin](https://developercertificate.org/)).

---

## Code of conduct

Be direct, be useful, be kind. Disagreements are welcome; personal attacks are not. Maintainers reserve the right to close threads, lock issues, or remove contributors who repeatedly degrade the signal-to-noise ratio of the project.

When critiquing code: critique the code, not the person who wrote it.
When receiving critique: assume good intent; clarify, don't escalate.

---

## Questions?

- Open a [discussion](https://github.com/greentarallc/opengriffin/discussions) for design questions.
- Open an [issue](https://github.com/greentarallc/opengriffin/issues) for bugs or feature requests.
- For anything else: hello@opengriffin.com.

Welcome aboard.
