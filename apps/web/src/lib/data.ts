export type Feature = {
  category:
    | "Memory"
    | "Compounding"
    | "Skills"
    | "Autonomous"
    | "Triggers"
    | "Security"
    | "Multi-platform"
    | "Voice + Vision"
    | "Ops";
  title: string;
  body: React.ReactNode;
};

import * as React from "react";

const mono = (s: string) =>
  React.createElement("span", { className: "mono" }, s);
const em = (s: string) => React.createElement("em", null, s);

export const features: Feature[] = [
  // Memory
  {
    category: "Memory",
    title: "Echo Memory + Receipts",
    body: "Vivid → recent → fading → ancient. Time-aware decay. Every recalled fact links to its source session via a citation receipt.",
  },
  {
    category: "Memory",
    title: "MEMORY · USER · SOUL",
    body: "Three flat markdown files load fresh into every session. Environment, profile, voice. Edit them by hand or let the agent.",
  },
  {
    category: "Memory",
    title: "CONSTRAINTS.md",
    body: "Hard rules the agent must NEVER violate. Loaded at the top of every system prompt, override-proof.",
  },

  // Compounding
  {
    category: "Compounding",
    title: "Daily journal",
    body: "4:30am every day: agent reviews yesterday, writes a journal entry, consolidates memory, suggests skills.",
  },
  {
    category: "Compounding",
    title: "Dream cycle",
    body: "3am offline reflection on interesting moments. Counterfactual analysis. Distills lessons into MEMORY overnight.",
  },
  {
    category: "Compounding",
    title: "Drift detection",
    body: React.createElement(
      React.Fragment,
      null,
      "Flags when stated preferences contradict recent behavior. ",
      em(
        "“You said you hated meetings; today you scheduled five.”",
      ),
    ),
  },

  // Skills
  {
    category: "Skills",
    title: "Skill Hub",
    body: React.createElement(
      React.Fragment,
      null,
      mono("griffin install github://owner/repo"),
      ". License-checked, signed, reputation-tracked. Replaces tool sprawl.",
    ),
  },
  {
    category: "Skills",
    title: "Self-healing skills",
    body: "When a skill fails 3+ times in a week, the agent debugs it, proposes a patched SKILL.md, and asks before applying.",
  },
  {
    category: "Skills",
    title: "Skill Strategy",
    body: "Recommends new skills based on co-usage, flags never-used ones, surfaces top-used to invest in.",
  },

  // Autonomous
  {
    category: "Autonomous",
    title: "Worker pool",
    body: "Long-running background agents. Spawn a research worker. Queue tasks. They check in to Telegram for days.",
  },
  {
    category: "Autonomous",
    title: "Agent Pods",
    body: "Multiple personas debate in a group chat with shared memory. Convergence detection.",
  },
  {
    category: "Autonomous",
    title: "Genealogy",
    body: "Fork a child agent from a parent. Inherits SOUL, skills, memory snapshot. Diverges over time.",
  },

  // Triggers
  {
    category: "Triggers",
    title: "Ambient mesh",
    body: React.createElement(
      React.Fragment,
      null,
      "Cron + webhook + poll → LLM predicate → skill action. ",
      em(
        "“When Stripe revenue drops 10% week-over-week, draft a postmortem.”",
      ),
    ),
  },
  {
    category: "Triggers",
    title: "Time-locked actions",
    body: React.createElement(
      React.Fragment,
      null,
      "Agent commits to do X at a future time. You can ",
      mono("/veto"),
      " before; otherwise it runs.",
    ),
  },
  {
    category: "Triggers",
    title: "Predictive memory",
    body: React.createElement(
      React.Fragment,
      null,
      "Detects time-of-day query patterns and pre-computes likely-asked things 15 minutes early. ",
      em(
        "“I noticed you check NVDA at 8:30am — here it is.”",
      ),
    ),
  },

  // Security
  {
    category: "Security",
    title: "Critic — adversarial twin",
    body: "Every consequential action reviewed by a second agent that doesn't see your prompt. Catches goal misgeneralization.",
  },
  {
    category: "Security",
    title: "Capability tokens",
    body: "Signed, scoped, expiring permissions for tools. The agent can't do something it doesn't hold a token for.",
  },
  {
    category: "Security",
    title: "Pre-exec scanner",
    body: "Pattern-match for prompt injection, dangerous shell, exfil URLs, hardcoded secrets, homograph attacks. Hardline blocklist for fork bombs / mkfs / dd-to-disk.",
  },
  {
    category: "Security",
    title: "Hardware attestation",
    body: "Secure Enclave (macOS) / TPM (Linux) signing of every consequential action. Tamper-evident audit log.",
  },
  {
    category: "Security",
    title: "ZK-style proofs",
    body: "Hash-chained Merkle audit log. Prove any single action existed without revealing the others.",
  },
  {
    category: "Security",
    title: "Dead-man's switch",
    body: "If you don't check in for N days, outbound actions lock. Recovery code via Telegram. Optional escalation to a trusted contact.",
  },
  {
    category: "Security",
    title: "Quorum (N-of-M)",
    body: "High-stakes actions need 2-of-3 independent agent personas to agree. Reduces single-point prompt-injection failure.",
  },
  {
    category: "Security",
    title: "Approval inline buttons",
    body: "Risky tool calls ask before running. Telegram inline keyboard: Allow once / Session / Always / Deny. 60-second auto-deny.",
  },
  {
    category: "Security",
    title: "Checkpoints + rollback",
    body: React.createElement(
      React.Fragment,
      null,
      "Every Write/Edit snapshots the file first. ",
      mono("/rollback"),
      " restores in one command.",
    ),
  },

  // Multi-platform
  {
    category: "Multi-platform",
    title: "7 free gateways",
    body: "Telegram, Discord, Slack, Email, iMessage, Signal, Matrix. Same brain answers across all of them.",
  },
  {
    category: "Multi-platform",
    title: "Cross-platform identity",
    body: "Link your accounts across Telegram + Discord + Slack + ... Single memory namespace per human.",
  },
  {
    category: "Multi-platform",
    title: "A2A peer mesh",
    body: "Your agent can call another OpenGriffin user's agent. P2P. Pay-per-call via x402 wallet, or free.",
  },
  {
    category: "Multi-platform",
    title: "Reputation ledger",
    body: "Signed JSON-LD profile of your agent's track record. A2A-discoverable for trust.",
  },

  // Voice + Vision
  {
    category: "Voice + Vision",
    title: "Voice round-trip",
    body: "Telegram voice → faster-whisper → Claude → Edge-TTS → reply voice. Local STT/TTS, no cloud.",
  },
  {
    category: "Voice + Vision",
    title: "Browser automation",
    body: "Playwright MCP. Drives a real Chromium for screenshots, scraping, end-to-end clicks.",
  },
  {
    category: "Voice + Vision",
    title: "Image generation",
    body: "FAL.ai wrapper for FLUX. BYO FAL_KEY. (More providers landing soon.)",
  },

  // Ops
  {
    category: "Ops",
    title: "Kanban",
    body: "JSON-backed task board. Workers + pods + ambient triggers all read/write it.",
  },
  {
    category: "Ops",
    title: "Live observability",
    body: "Server-Sent Events stream of every agent thought + tool call. Datadog APM for cognition.",
  },
  {
    category: "Ops",
    title: "Replay debugger",
    body: "Re-run any past session with a different model or SOUL. Counterfactual diffing for regression hunts.",
  },
  {
    category: "Ops",
    title: "Provider routing",
    body: React.createElement(
      React.Fragment,
      null,
      "Auction classifier scores each prompt 0–3 and routes cheap. ",
      mono("“hi”"),
      " → Groq. ",
      mono("“prove this”"),
      " → Claude Opus.",
    ),
  },
  {
    category: "Ops",
    title: "Soul Sync",
    body: React.createElement(
      React.Fragment,
      null,
      "Mines your past chats to build a writing-voice card. Agent drafts ",
      em("as you"),
      ".",
    ),
  },
  {
    category: "Ops",
    title: "Webhooks gateway",
    body: "HMAC-validated POST endpoints. GitHub, Stripe, IFTTT — anything that webhooks reaches your agent.",
  },
];

export const providers = [
  "Claude Max OAuth",
  "Anthropic API",
  "OpenAI",
  "Gemini",
  "DeepSeek",
  "Mistral",
  "xAI / Grok",
  "Cohere",
  "Bedrock",
  "Groq",
  "Cerebras",
  "Together",
  "Fireworks",
  "Perplexity",
  "NVIDIA NIM",
  "HuggingFace",
  "Lambda Labs",
  "Novita",
  "OpenRouter",
  "Azure OpenAI",
  "Ollama (local)",
];

export const faqs: { q: string; a: React.ReactNode }[] = [
  {
    q: "Is OpenGriffin really free?",
    a: "Yes — Apache 2.0, free forever, self-hosted. You bring your own AI provider key and pay that provider directly. There is no OpenGriffin subscription, ever, on the OSS path.",
  },
  {
    q: "What's the difference vs Hermes Agent?",
    a: "OpenGriffin is a strict superset on memory (Echo Memory + receipts + dream cycle), self-improvement (daily journal + skill graph + drift detection), security (capability tokens + critic + Merkle audit + dead-man's switch), autonomy (worker pool + agent pods + genealogy + time-locked actions), and infrastructure (no backend, 21 providers, 7 platforms). Hermes has 14 messaging gateways and Atropos RL training; we don't (yet).",
  },
  {
    q: "What's the difference vs OpenClaw?",
    a: "OpenClaw is a thin CLI wrapper. OpenGriffin is a long-running agent with persistent memory, scheduled work, sub-agent spawning, multi-platform delivery, and a self-improvement loop. We ship a one-line migration tool to import OpenClaw state.",
  },
  {
    q: "What's the difference vs a hosted multi-model dashboard?",
    a: "Hosted dashboards are chat UIs across many models — useful, but not agents. OpenGriffin is autonomy + memory + skills you run on your own machine: no monthly subscription, your data stays on your disk unless you explicitly send it somewhere, and the agent acts between your messages.",
  },
  {
    q: "Do I have to use Telegram?",
    a: "No. Telegram is the easiest first surface, but the same brain runs on Discord, Slack, Email, iMessage, Signal, and Matrix. Cross-platform identity links them.",
  },
  {
    q: "Where does my data live?",
    a: React.createElement(
      React.Fragment,
      null,
      "100% local: ",
      mono("~/.opengriffin/"),
      " for memory + sessions + kanban + journal, ",
      mono("~/.claude/skills/"),
      " for skills. Nothing is uploaded. Outbound HTTP only happens to providers you configured (Telegram, Anthropic API, etc.) and to peers you explicitly call (A2A).",
    ),
  },
  {
    q: "Will there be a hosted version?",
    a: "Eventually, when demand justifies the engineering. The OSS Core will always be free. The hosted product would offer optional managed hosting + a web GUI; the OSS will always do everything you can do hosted.",
  },
  {
    q: "How is this safe? It can run shell commands.",
    a: React.createElement(
      React.Fragment,
      null,
      "Layered defense: pre-execution scanner (blocks ",
      mono("rm -rf /"),
      ", fork bombs, exfil), capability tokens (signed scoped permissions), critic agent (independent review), approval inline buttons for dangerous patterns, hardware-attested signing, dead-man's switch, file checkpoints with one-command rollback. You can also run with ",
      mono("permission_mode=plan"),
      " to prevent any tool execution.",
    ),
  },
];
