# Security Policy

OpenGriffin is a long-running agent that can read files, run shell
commands, call external APIs, and spend your money. Security is a
first-class concern. This document tells you how to report a vulnerability
and what to expect when you do.

## Reporting a vulnerability

**Do not file public GitHub issues for security bugs.** Open a private
report instead — use GitHub's "Report a vulnerability" button on the
[Security tab](https://github.com/greentarallc/opengriffin/security/advisories/new),
or email `security@opengriffin.com`.

Please include:

- The OpenGriffin version (`git rev-parse --short HEAD` or `opengriffin doctor`).
- The shortest path to reproduce — ideally a minimal `MEMORY.md` /
  `USER.md` snippet plus the message that triggers it.
- The provider you were using and whether the bug is provider-specific.
- An impact estimate — what an attacker could do if they exploited it.

We'll acknowledge receipt within 72 hours and target an initial assessment
within 7 days. Coordinated disclosure timeline is typically 30–90 days
depending on severity; we'll work the timeline with you on the report.

## In scope

- Bot core: `src/opengriffin/`.
- Provider adapters: `src/opengriffin/providers/`.
- Gateways: `src/opengriffin/gateways/`.
- Bundled skills under `bundled_skills/`.
- The dashboard server: `src/opengriffin/dashboard/`.

## Out of scope

- Vulnerabilities in upstream models (Claude, GPT, Gemini, etc.) — please
  report those to the model vendor.
- Vulnerabilities in user-authored skills under `~/.claude/skills/` that
  did not ship in `bundled_skills/`.
- Issues that require root on the host machine or physical access — at
  that point the attacker already controls the agent.
- Prompt-injection from a *trusted* user (the bot user themselves) when
  destructive tools are explicitly opted into.

## What we will and won't pay

OpenGriffin is OSS with no commercial backer. **There is no paid bounty
program.** We acknowledge serious reports publicly (with your consent) in
the release notes for the fix.

## Defense layers

The bot already ships:

- **Pre-execution scanner** (`security_scan.py`) — pattern-match for
  prompt injection, shell exfil, hardcoded secrets, fork bombs, homograph
  attacks. Hardline blocklist for `rm -rf /`, `mkfs`, `dd to /dev/disk*`,
  etc.
- **Capability tokens** (`capabilities.py`) — signed, scoped, expiring
  permissions. Tools fail closed if a token isn't presented.
- **Critic agent** (`critic.py`) — every consequential action reviewed by
  a second agent that doesn't see the user prompt.
- **Approval inline buttons** (`approvals.py`) — risky tool calls ask
  before running. 60-second auto-deny.
- **Hardware attestation** (`attest.py`) — Secure Enclave (macOS) / TPM
  (Linux) signing on every consequential action.
- **Merkle audit log** (`zk_proofs.py`) — tamper-evident, selectively
  revealable.
- **Verifiable refusal + erasure receipts** (`proofs.py`) — proves the
  agent did NOT do X / proves a fact was forgotten.
- **Dead-man's switch** (`deadman.py`) — if you don't check in for N
  days, outbound actions lock.
- **Quorum** (`quorum.py`) — high-stakes actions need 2-of-3 agent
  personas to agree.
- **File checkpoints** (`checkpoints.py`) — every Write/Edit snapshots
  the file first; `/rollback` restores in one command.

If a vulnerability bypasses any of these layers, that's the kind of
report we most want to see.

## Running with reduced authority

If you want to run the bot in advisory-only mode (no tool execution):

```bash
OPENGRIFFIN_PERMISSION_MODE=plan opengriffin run
```

This still allows the agent to *propose* actions and route them through
approvals, but the underlying tools won't fire.
