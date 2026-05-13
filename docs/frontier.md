# Frontier modules

These eight modules ship in addition to the twelve killer features. They
target the frontier of personal-agent design — prediction, inverse safety,
cross-agent skill liquidity, interfaces beyond chat — and are wired through
the same MCP-server pattern as everything else.

Source paths reference `src/opengriffin/` unless noted.

## 1. Personal World Model — `world_model.py`

A Bayesian forecaster over (weekday, hour) slots. The agent's other memory
modules (`echo_memory`, `MEMORY.md`) store *what happened*; this stores
*what is likely to happen next*. Laplace-smoothed categorical distributions
plus median inter-arrival per slot. Rebuilt nightly at 05:15 from
`~/.opengriffin/world_model/events.jsonl`. The `observe()` API inline-flags
events the model gave less than 5% probability — those become entries in
the surprise log and feed mesa-cognition.

## 2. Living Twin — `twin.py`

A sandboxed counterfactual sub-agent. Spawns on a hardened `ClaudeSDKClient`
session (`permission_mode=plan`, `skills=none`, `setting_sources=[]`), reads
MEMORY/USER/SOUL snapshot + the current world-model forecast, emits a
structured outcome JSON (premise, trajectory, key_risks, calibration,
verdict). Cached by `(premise, horizon, snapshot_hash)` so re-asking the
same hypothetical against stable memory re-uses the prior simulation. A
global `asyncio.Lock` prevents runaway concurrent simulations.

## 3. Verifiable Refusal Proofs + Provable Forgetting — `proofs.py`

Three witness kinds, HMAC-signed over canonical JSON, anchored as leaves
in the existing `zk_proofs.py` Merkle audit log:

- **refusal** — emitted on any capability deny.
- **erasure** — emitted on memory removal. Caller hashes the plaintext;
  the receipt commits to the *hash*, not the content.
- **non-disclosure** — at session end, commits to a hash of the actual
  prompt-context-prefix used. A verifier rebuilds the prefix against the
  same memory snapshot and checks the hash matches.

Hardware-rooted Ed25519 sigs are listed as future work; `attest.py` needs a
`verify()` and Ed25519's randomized signing makes "re-sign and compare"
invalid.

## 4. Generative Live UI — `gen_ui.py`

A 10-primitive UI vocabulary (panel, kv_list, checklist, choice, slider,
card_grid, table, code_block, chart, actions) transcoded to Telegram
inline-keyboard JSON via a pure renderer. Every render assigns a `ui_id`;
every interaction increments the engagement score for that
(purpose, primitive) pair. `preferred_primitive(purpose)` returns the
highest-engagement primitive learned so far — so the agent stops rendering
layouts the user ignores.

## 5. Mesa-Cognition Supervisor — `mesa.py`

Five drift detectors over recent agent behavior:

- `self_preservation` — refusal-rate trend + self-protective phrase density
- `engagement_maximization` — reply-length trend + engagement phrase density
- `over_cautious_refusal` — refusal rate × world-model surprise count
- `memory_self_edit` — agent-flavored phrasing density in USER.md
- `scope_expansion` — skill-install rate / task diversity

Each detector returns a score in [0, 1]. Top axis fires nightly at 05:30
into `~/.opengriffin/mesa/reports.jsonl`. Advisory only — drift.py watches
the user; mesa watches the agent.

## 6. Capability-Scoped Skill Leasing — `skill_lease.py`

Signed, scoped, revocable lease tokens that let your agent borrow another
peer's skill for a bounded budget (TTL + max invocations). Acceptance
verifies `artifact_hash` so a lessee never installs blindly. Invocation
counter is enforced, revocation is instant and emits a refusal witness.
Real OS-level sandboxing (`nsjail` / `sandbox-exec`) is future work; the
MVP relies on env-var `allowed_hosts` plus capability-token scoping.

## 7. Personal Causal Data Layer — `causal.py`

A directed causal graph where edges live in `{proposed, confirmed,
rejected}` with confidence ∈ [0, 1] *forever*. `discover_from_world_model`
walks the PWM event log, computes lift per A→B pair, proposes edges above
`MIN_JOINT=3` co-occurrences and `PROPOSAL_LIFT_THRESHOLD=2.0`. Confirmed
edges feed `counterfactual_neighbours()`, which seeds Living Twin
simulations with grounded "if A then B" premises. The user is the
instrument variable — their confirm/reject decisions make N=1 causal
inference tractable.

## 8. Adversarial Improvement Market — `adversarial.py`

A bug-bounty primitive for agent capabilities. Submitters post failure
cases (deduplicated by content hash); the agent replays in sandboxed mode
and computes `behavioral_distance` (Jaccard + length-delta + refusal-flip)
against the original. Novel replays (distance > 0.35) award credits to the
submitter, daily-capped at 5 per submitter to disincentivise fuzzing.
`redact.looks_like_injection` rejects obvious prompt-injection submissions.
x402 payout is the natural next step; the current credit ledger is local.

## Cron schedule

```
05:15  world_model.train               (nightly)
05:30  mesa.run_report                  (nightly)
05:45  causal.discover_from_world_model (daily)
```

## Testing

`tests/test_frontier_modules.py` covers each module's public surface with
hermetic tests (HOME monkeypatched per test). Run with `uv run pytest -q`.

## Adding another frontier module

Follow the existing pattern:

1. New file under `src/opengriffin/`. Module-level constants for paths
   (use `paths.OG_HOME` etc.).
2. Public API functions, then `@tool`-decorated MCP wrappers.
3. Export `<NAME>_SERVER = create_sdk_mcp_server(...)`.
4. Add a `try/except` block in `bot.py:build_mcp_servers()` that imports
   and registers the server.
5. If you need a nightly job, add a `scheduler.add_job` call in
   `bot.py:_post_init`.
6. Add a test file under `tests/`.
