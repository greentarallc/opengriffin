# 🦁 OpenGriffin

**Multi-model AI agents on Telegram. 16+ chat models. Image & video generation. Always on.**

OpenGriffin gives you always-on AI agents accessible through Telegram — powered by 16+ AI models via OpenRouter, with image and video generation via fal.ai. Persistent memory, scheduled tasks, word-based billing, and Stripe integration built in.

## What It Does

- **16+ AI models in one chat** — Claude, GPT, Gemini, DeepSeek, Llama, Grok, Mistral, Qwen, Perplexity. Switch mid-conversation with `/model`. Auto mode picks the best model per message.
- **Image generation** — FLUX Pro/Dev/Schnell, Recraft V3, Ideogram V3, Stable Diffusion 3.5 via fal.ai.
- **Video generation** — Kling 2.1, Hailuo, Wan 2.1, LTX Video via fal.ai.
- **Persistent memory** — Names, preferences, context remembered forever across sessions. Never resets.
- **Always-on scheduler** — Morning briefings, evening reviews, task reminders, overdue alerts via cron.
- **Multi-agent** — Switch between Chief of Staff, Inbox Ops, Lead Hawk, Content Engine, or custom agents.
- **Word-based billing** — $19/$39/$79 tiers with multiplier system. Cheaper models = more words per dollar.
- **Stripe integration** — Subscriptions, top-ups ($5/$10/$20), customer portal, 7-day data retention after cancel.

## Architecture

```
You (Telegram — phone or desktop)
  │  TLS encrypted
  ▼
┌────────────────────────────────────────────┐
│  OpenGriffin Core (Node.js)                │
│                                            │
│  ├── Telegram Gateway (grammy)             │
│  ├── Agent Router (5 agents + custom)      │
│  ├── LLM Router (OpenRouter — 16+ models)  │
│  ├── Media Generator (fal.ai — 10 models)  │
│  ├── Tool System (11 built-in tools)       │
│  ├── Memory (SQLite — persistent)          │
│  ├── Usage Tracker (word-based billing)    │
│  ├── Billing (Stripe)                      │
│  ├── Analytics (dashboard + reports)       │
│  ├── Scheduler (node-cron)                 │
│  └── Cleanup (7-day retention cron)        │
└────────────────────────────────────────────┘

2,565 lines · 13 source files · 6 npm dependencies · 2 API keys
```

## Quick Start

### 1. Create a Telegram bot

Open Telegram → `@BotFather` → `/newbot` → copy the token.

### 2. Get API keys

- **OpenRouter** — [openrouter.ai](https://openrouter.ai) → API key (required)
- **fal.ai** — [fal.ai](https://fal.ai) → API key (optional, for image/video)
- **Stripe** — [stripe.com](https://stripe.com) → secret key (optional, for billing)

### 3. Install and run

```bash
git clone https://github.com/greentarallc/opengriffin.git
cd opengriffin
npm install

cp .env.example .env
# Edit .env — add TELEGRAM_BOT_TOKEN and OPENROUTER_API_KEY

npm start
```

### 4. Open Telegram and send `/start`

## Models

### Chat (via OpenRouter)

| Model | Key | Multiplier | Best for |
|-------|-----|-----------|----------|
| 🟣 Claude Sonnet 4 | `claude-sonnet` | 1.0x | General, creative writing |
| 🟣 Claude Opus 4 | `claude-opus` | 3.0x | Complex reasoning |
| 🟣 Claude Haiku 4.5 | `claude-haiku` | 0.3x | Fast, cheap tasks |
| 🟢 GPT-4o | `gpt-4o` | 1.0x | Code, general |
| 🟢 GPT-4o Mini | `gpt-4o-mini` | 0.2x | Simple tasks |
| 🟢 GPT-5 | `gpt-5` | 4.0x | Premium reasoning |
| 🔵 Gemini 2.5 Pro | `gemini-pro` | 1.2x | Research, analysis |
| 🔵 Gemini 2.5 Flash | `gemini-flash` | 0.15x | Fast, cheap |
| 🟠 DeepSeek V3 | `deepseek` | 0.1x | Budget — 10x more words |
| 🟠 DeepSeek R1 | `deepseek-r1` | 0.5x | Reasoning |
| 🦙 Llama 4 Maverick | `llama-4` | 0.3x | Open source |
| 🦙 Llama 3.3 70B | `llama-3.3` | 0.15x | Open source, cheap |
| 🔶 Mistral Large | `mistral-large` | 0.8x | European AI |
| ⚡ Grok 3 Mini | `grok` | 0.5x | Real-time knowledge |
| 🔸 Qwen 2.5 72B | `qwen` | 0.12x | Budget, multilingual |
| 🌐 Perplexity Sonar | `perplexity` | 0.4x | Search-augmented |

### Image (via fal.ai)

| Model | Key | Cost |
|-------|-----|------|
| 🎨 FLUX Pro Ultra | `flux-pro` | $0.05/image |
| 🎨 FLUX Dev | `flux-dev` | $0.025/image |
| 🎨 FLUX Schnell | `flux-schnell` | $0.003/image |
| 🎨 Recraft V3 | `recraft` | $0.04/image |
| 🎨 Ideogram V3 | `ideogram` | $0.04/image |
| 🎨 Stable Diffusion 3.5 | `stable-diff` | $0.04/image |

### Video (via fal.ai)

| Model | Key | Cost |
|-------|-----|------|
| 🎬 Kling 2.1 | `kling` | $0.07/sec |
| 🎬 Hailuo | `hailuo` | $0.10/sec |
| 🎬 Wan 2.1 | `wan` | $0.10/sec |
| 🎬 LTX Video | `ltx` | $0.002/sec |

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome + setup |
| `/models` | List all AI models with multipliers |
| `/model <key>` | Switch model (e.g., `/model gemini-flash`) |
| `/model auto` | Auto-select best model per message |
| `/agents` | List agent personas |
| `/switch <agent>` | Switch persona |
| `/usage` | Quick usage summary |
| `/dashboard` | Full analytics (7-day trend, projections, tips) |
| `/topup <5\|10\|20>` | Buy more words |
| `/subscribe <plan>` | Change plan |
| `/billing` | Manage subscription (Stripe portal) |
| `/tasks` | Pending tasks |
| `/memory` | What the agent remembers |
| `/forget <key>` | Delete a memory |
| `/reset` | Clear conversation history |

## Agents

| Agent | Emoji | Purpose |
|-------|-------|---------|
| Chief of Staff | 📋 | Morning briefings, task tracking, weekly reviews |
| Inbox Ops | 📧 | Email triage, draft replies, follow-up tracking |
| Lead Hawk | 🦅 | Sales pipeline, lead tracking, outreach drafting |
| Content Engine | 📝 | Repurpose content into tweets, posts, newsletters |
| Custom | 🔧 | Blank agent — define any role |

## Pricing Tiers

| Plan | Price | Words/month |
|------|-------|-------------|
| Trial | $0 | 10K (24 hours) |
| Starter | $19/mo | 100K |
| Pro | $39/mo | 500K |
| Agency | $79/mo | 2M |

Top-ups: $5 → 25K, $10 → 55K, $20 → 120K words.

## Built-in Tools

The agent can use these automatically during conversations:

- **remember / recall / recall_all** — Persistent memory
- **create_task / list_tasks / complete_task** — Task management
- **get_current_time** — Time-aware responses
- **get_stats** — Usage overview
- **switch_agent** — Switch mid-conversation
- **generate_image** — Create images (FLUX, Recraft, Ideogram, SD)
- **generate_video** — Create videos (Kling, Hailuo, Wan, LTX)

## Deploy to Production

```bash
# On your server (Ubuntu 22+)
sudo apt update && sudo apt install -y nodejs npm
git clone https://github.com/greentarallc/opengriffin.git
cd opengriffin && npm install
cp .env.example .env && nano .env

# Run with pm2
npm install -g pm2
pm2 start src/index.js --name opengriffin
pm2 startup && pm2 save
```

### Provision a customer instance

```bash
node src/provision.js \
  --user <telegram_user_id> \
  --plan starter \
  --bot-token <token> \
  --openrouter-key <key> \
  --fal-key <key>
```

## File Structure

```
opengriffin/
├── index.html          Landing page
├── package.json        6 deps: grammy, stripe, sql.js, node-cron, dotenv, uuid
├── .env.example        Configuration template
├── README.md
└── src/
    ├── index.js        (436 lines)  Telegram bot, commands, routing
    ├── llm-router.js   (173 lines)  OpenRouter: 16 models, auto-select
    ├── media.js        (147 lines)  fal.ai: 6 image + 4 video models
    ├── billing.js      (308 lines)  Stripe: subscriptions, top-ups, portal
    ├── analytics.js    (199 lines)  Usage dashboard, trends, projections
    ├── memory.js       (264 lines)  SQLite persistent memory
    ├── tools.js        (233 lines)  11 built-in tools incl. image/video
    ├── agents.js       (166 lines)  5 agent personas
    ├── plans.js        (170 lines)  Word-based tiers, usage tracking
    ├── scheduler.js    (177 lines)  Cron: briefs, reminders, cleanup
    ├── provision.js    (133 lines)  Customer instance provisioning
    ├── cleanup.js      (44 lines)   7-day data retention enforcement
    └── test-flow.js    (115 lines)  Module tests
```

**Total: 2,565 lines · 13 source files · 6 dependencies · 2 API keys**

## License

All rights reserved © 2026 GreenTara LLC.
