// ══════════════════════════════════════════
// OpenGriffin — Main Entry Point
// Multi-model AI agents on Telegram.
// Claude · GPT · Gemini · DeepSeek
// ══════════════════════════════════════════

import 'dotenv/config';
import { Bot } from 'grammy';
import { Memory } from './memory.js';
import { LLMRouter, listModels, getModel, AUTO_MODEL } from './llm-router.js';
import { MediaGenerator, listImageModels, listVideoModels } from './media.js';
import { BUILTIN_TOOLS, createToolHandler } from './tools.js';
import { getAgent, listAgents, buildSystemPrompt } from './agents.js';
import { Scheduler } from './scheduler.js';
import { UsageTracker, getPlan, listPlans, formatWords } from './plans.js';
import { Billing, TOPUP_CREDITS } from './billing.js';
import { Analytics } from './analytics.js';

// ── Validate config ───────────────────────
if (!process.env.TELEGRAM_BOT_TOKEN) {
  console.error('❌ Missing TELEGRAM_BOT_TOKEN');
  process.exit(1);
}
if (!process.env.OPENROUTER_API_KEY) {
  console.error('❌ Missing OPENROUTER_API_KEY. Get one at openrouter.ai');
  process.exit(1);
}

// ── Initialize modules ────────────────────
const memory = new Memory();
await memory.init(process.env.DB_PATH || './data/opengriffin.db');

const llm = new LLMRouter(process.env.OPENROUTER_API_KEY);
const media = process.env.FAL_API_KEY ? new MediaGenerator(process.env.FAL_API_KEY) : null;
const billing = new Billing(memory);
const analytics = new Analytics(memory);

const usage = new UsageTracker(memory);
const bot = new Bot(process.env.TELEGRAM_BOT_TOKEN);

// ── User state helpers ────────────────────
function getUserAgent(userId) {
  const stored = memory.recall(userId, '_system', 'active_agent');
  return stored || process.env.DEFAULT_AGENT || 'chief-of-staff';
}
function setUserAgent(userId, agentId) {
  memory.remember(userId, '_system', 'active_agent', agentId, 'general', 'system');
}
function getUserModel(userId) {
  const stored = memory.recall(userId, '_system', 'active_model');
  return stored || 'auto';
}
function setUserModel(userId, modelKey) {
  memory.remember(userId, '_system', 'active_model', modelKey, 'general', 'system');
}
function getUserPlan(userId) {
  if (billing.enabled) return billing.getUserPlan(userId);
  const stored = memory.recall(userId, '_system', 'plan');
  return stored || 'trial';
}

// ── Helper: safe reply with markdown fallback ──
async function safeReply(ctx, text) {
  if (text.length <= 4096) {
    await ctx.reply(text, { parse_mode: 'Markdown' }).catch(() => ctx.reply(text));
  } else {
    const chunks = splitMessage(text, 4000);
    for (const chunk of chunks) {
      await ctx.reply(chunk, { parse_mode: 'Markdown' }).catch(() => ctx.reply(chunk));
    }
  }
}
function splitMessage(text, maxLen) {
  const chunks = [];
  let remaining = text;
  while (remaining.length > 0) {
    if (remaining.length <= maxLen) { chunks.push(remaining); break; }
    let splitAt = remaining.lastIndexOf('\n', maxLen);
    if (splitAt < maxLen * 0.5) splitAt = remaining.lastIndexOf(' ', maxLen);
    if (splitAt < maxLen * 0.5) splitAt = maxLen;
    chunks.push(remaining.slice(0, splitAt));
    remaining = remaining.slice(splitAt).trimStart();
  }
  return chunks;
}

// ══════════════════════════════════════════
// COMMANDS
// ══════════════════════════════════════════

bot.command('start', async (ctx) => {
  const userId = String(ctx.from.id);
  const agent = getAgent(getUserAgent(userId));
  const modelKey = getUserModel(userId);
  const available = listModels();

  await safeReply(ctx,
    `🦁 **Welcome to OpenGriffin**\n\n` +
    `All the world's best AI models in one Telegram bot. Always-on agents with persistent memory, scheduled tasks, and multi-model switching.\n\n` +
    `**Active agent:** ${agent.emoji} ${agent.name}\n` +
    `**Active model:** ${modelKey === 'auto' ? '🔀 Auto (picks the best model)' : `${getModel(modelKey).icon} ${getModel(modelKey).name}`}\n` +
    `**Available models:** ${available.length}\n\n` +
    `**Commands:**\n` +
    `  /models — List all AI models\n` +
    `  /model <name> — Switch model\n` +
    `  /agents — List agent personas\n` +
    `  /switch <agent> — Switch persona\n` +
    `  /usage — Word usage & billing\n` +
    `  /dashboard — Full analytics\n` +
    `  /topup <5|10|20> — Buy more words\n` +
    `  /billing — Manage subscription\n` +
    `  /tasks — Pending tasks\n` +
    `  /memory — What I remember\n` +
    `  /forget <key> — Delete a memory\n` +
    `  /reset — Clear history\n\n` +
    `Just message me — I'll figure out the rest. 🦁`
  );
});

// ── Model commands ────────────────────────

bot.command('models', async (ctx) => {
  const available = listModels();
  const currentKey = getUserModel(String(ctx.from.id));
  const lines = available.map(m => {
    const active = m.key === currentKey ? ' ← active' : '';
    const mult = m.multiplier === 1 ? '' : ` (${m.multiplier}x)`;
    return `  ${m.icon} **${m.name}**${mult}${active}\n     \`/model ${m.key}\``;
  });
  const autoActive = currentKey === 'auto' ? ' ← active' : '';
  await safeReply(ctx,
    `🔀 **Available Models**\n\n` +
    `  🔀 **Auto** — picks the best model per prompt${autoActive}\n     \`/model auto\`\n\n` +
    lines.join('\n\n') +
    `\n\n_Multiplier = how many words are billed per actual word. Lower = cheaper._`
  );
});

bot.command('model', async (ctx) => {
  const key = ctx.match?.trim().toLowerCase();
  if (!key) { await ctx.reply('Usage: `/model claude-sonnet` or `/model auto`', { parse_mode: 'Markdown' }); return; }

  if (key === 'auto') {
    setUserModel(String(ctx.from.id), 'auto');
    await ctx.reply('🔀 Switched to **Auto** — I\'ll pick the best model for each message.', { parse_mode: 'Markdown' });
    return;
  }

  const available = listModels();
  const match = available.find(m => m.key === key);
  if (!match) {
    const names = available.map(m => `\`${m.key}\``).join(', ');
    await safeReply(ctx, `❌ Unknown model. Available: ${names}, \`auto\``);
    return;
  }

  setUserModel(String(ctx.from.id), key);
  await ctx.reply(`${match.icon} Switched to **${match.name}** (${match.multiplier}x multiplier)`, { parse_mode: 'Markdown' });
});

// ── Agent commands ────────────────────────

bot.command('agents', async (ctx) => {
  const agents = listAgents();
  const currentId = getUserAgent(String(ctx.from.id));
  const lines = agents.map(a => {
    const active = a.id === currentId ? ' ← active' : '';
    return `  ${a.emoji} **${a.name}**${active}\n     ${a.description}\n     \`/switch ${a.id}\``;
  });
  await safeReply(ctx, `🤖 **Agent Personas**\n\n${lines.join('\n\n')}`);
});

bot.command('switch', async (ctx) => {
  const agentId = ctx.match?.trim().replace(/_/g, '-');
  if (!agentId) { await ctx.reply('Usage: `/switch chief-of-staff`', { parse_mode: 'Markdown' }); return; }
  const agent = getAgent(agentId);
  setUserAgent(String(ctx.from.id), agentId);
  await ctx.reply(`${agent.emoji} Switched to **${agent.name}**`, { parse_mode: 'Markdown' });
});

// ── Usage & billing ───────────────────────

bot.command('usage', async (ctx) => {
  const userId = String(ctx.from.id);
  const planId = getUserPlan(userId);
  const report = analytics.getQuickSummary(userId, planId);
  await safeReply(ctx, report);
});

bot.command('dashboard', async (ctx) => {
  const userId = String(ctx.from.id);
  const planId = getUserPlan(userId);
  const report = analytics.getDashboard(userId, planId);
  await safeReply(ctx, report);
});

bot.command('plans', async (ctx) => {
  const plans = listPlans().filter(p => p.id !== 'trial');
  const current = getUserPlan(String(ctx.from.id));
  const lines = plans.map(p => {
    const active = p.id === current ? ' ← your plan' : '';
    return `  **${p.name}** — $${p.price}/mo${active}\n     ${formatWords(p.wordLimit)} words/month`;
  });
  let msg = `💳 **Plans**\n\n${lines.join('\n\n')}`;
  if (billing.enabled) msg += `\n\nUse /subscribe <plan> to upgrade.`;
  await safeReply(ctx, msg);
});

bot.command('topup', async (ctx) => {
  const userId = String(ctx.from.id);
  const amount = parseInt(ctx.match?.trim());

  if (!billing.enabled) {
    await ctx.reply('💳 Billing not configured yet. Contact hello@opengriffin.com for top-ups.');
    return;
  }

  if (![5, 10, 20].includes(amount)) {
    const options = Object.entries(TOPUP_CREDITS).map(([amt, words]) =>
      `  **$${amt}** → ${formatWords(words)} words`
    ).join('\n');
    await safeReply(ctx, `💰 **Top Up Words**\n\n${options}\n\nUsage: \`/topup 5\`, \`/topup 10\`, or \`/topup 20\``);
    return;
  }

  try {
    const { url, words } = await billing.createTopupSession(userId, amount);
    await safeReply(ctx, `💰 **Top Up — $${amount} → ${formatWords(words)} words**\n\n[Click here to purchase](${url})\n\nWords will be added to your balance immediately after payment.`);
  } catch (err) { await ctx.reply(`❌ ${err.message}`); }
});

bot.command('subscribe', async (ctx) => {
  const userId = String(ctx.from.id);
  const planId = ctx.match?.trim().toLowerCase();

  if (!billing.enabled) {
    await ctx.reply('💳 Billing not configured yet. Contact hello@opengriffin.com to subscribe.');
    return;
  }

  if (!planId || !['starter', 'pro', 'agency'].includes(planId)) {
    await safeReply(ctx, '💳 Usage: `/subscribe starter`, `/subscribe pro`, or `/subscribe agency`');
    return;
  }

  try {
    const url = await billing.createCheckoutSession(userId, planId);
    const plan = getPlan(planId);
    await safeReply(ctx, `💳 **Subscribe to ${plan.name} — $${plan.price}/mo**\n\n[Click here to subscribe](${url})`);
  } catch (err) { await ctx.reply(`❌ ${err.message}`); }
});

bot.command('billing', async (ctx) => {
  const userId = String(ctx.from.id);

  if (!billing.enabled) {
    await ctx.reply('💳 Billing not configured yet. Contact hello@opengriffin.com.');
    return;
  }

  try {
    const url = await billing.createPortalSession(userId);
    await safeReply(ctx, `💳 **Billing Portal**\n\n[Manage subscription, update payment, cancel](${url})\n\nYou can change plans, update payment methods, view invoices, or cancel from here.`);
  } catch (err) { await ctx.reply(`❌ ${err.message}`); }
});

// ── Task, memory, stats commands ──────────

bot.command('tasks', async (ctx) => {
  const tasks = memory.getPendingTasks(String(ctx.from.id));
  if (tasks.length === 0) { await ctx.reply('✅ No pending tasks!'); return; }
  const lines = tasks.map(t => {
    const pri = ['🔴', '🟠', '🟡', '🔵', '⚪'][t.priority - 1] || '⚪';
    return `${pri} ${t.title}\n   \`${t.id.slice(0, 8)}\``;
  });
  await safeReply(ctx, `📋 **Pending Tasks (${tasks.length})**\n\n${lines.join('\n\n')}`);
});

bot.command('stats', async (ctx) => {
  const s = memory.getStats(String(ctx.from.id));
  await safeReply(ctx, `📊 **Stats**\n\n💬 ${s.messages} messages\n🧠 ${s.memories} memories\n✅ ${s.tasksDone} done\n📋 ${s.tasksPending} pending`);
});

bot.command('memory', async (ctx) => {
  const userId = String(ctx.from.id);
  const mems = memory.recallAll(userId, getUserAgent(userId));
  if (mems.length === 0) { await ctx.reply('🧠 No memories yet. Just chat and I\'ll start remembering!'); return; }
  const lines = mems.map(m => `• **${m.key}**: ${m.value}`);
  await safeReply(ctx, `🧠 **What I remember**\n\n${lines.join('\n')}`);
});

bot.command('forget', async (ctx) => {
  const key = ctx.match?.trim();
  if (!key) { await ctx.reply('Usage: `/forget key_name`', { parse_mode: 'Markdown' }); return; }
  memory.forget(String(ctx.from.id), getUserAgent(String(ctx.from.id)), key);
  await ctx.reply(`🗑️ Forgotten: ${key}`);
});

bot.command('reset', async (ctx) => {
  memory.remember(String(ctx.from.id), '_system', '_pending_reset', 'true');
  await ctx.reply('⚠️ This clears conversation history (memories & tasks kept). Send "yes" to confirm.');
});

// ══════════════════════════════════════════
// MAIN MESSAGE HANDLER
// ══════════════════════════════════════════

bot.on('message:text', async (ctx) => {
  const userId = String(ctx.from.id);
  const text = ctx.message.text;

  // Auth check
  const adminIds = (process.env.ADMIN_TELEGRAM_IDS || '').split(',').map(s => s.trim());
  if (adminIds.length > 0 && adminIds[0] !== '' && !adminIds.includes(userId)) {
    await ctx.reply('🔒 Unauthorized. Contact the admin for access.');
    return;
  }

  // Reset confirmation
  const pendingReset = memory.recall(userId, '_system', '_pending_reset');
  if (pendingReset === 'true') {
    memory.forget(userId, '_system', '_pending_reset');
    if (text.toLowerCase() === 'yes') { memory.clearConversations(userId); await ctx.reply('🗑️ History cleared.'); return; }
    else { await ctx.reply('Reset cancelled.'); return; }
  }

  // Check usage limits (with top-up fallback)
  const planId = getUserPlan(userId);
  const limit = usage.checkLimit(userId, planId);
  if (limit.exceeded) {
    const hasTopup = billing.enabled && billing.deductTopup(userId, 500);
    if (!hasTopup) {
      await safeReply(ctx,
        `⚠️ **Word limit reached** (${formatWords(limit.used)} / ${formatWords(limit.limit)})\n\n` +
        `Options:\n` +
        `  /topup 5 — add 25K words ($5)\n` +
        `  /topup 10 — add 55K words ($10)\n` +
        `  /topup 20 — add 120K words ($20)\n` +
        `  /plans — upgrade your plan`
      );
      return;
    }
  }

  // Get agent and model
  const agentId = getUserAgent(userId);
  const modelKey = getUserModel(userId);
  const agent = getAgent(agentId);

  await ctx.replyWithChatAction('typing');

  try {
    const history = memory.getConversationHistory(userId, agentId, 20);
    const userMemories = memory.recallAll(userId, agentId);
    const systemPrompt = buildSystemPrompt(agentId, userMemories);
    const messages = [...history, { role: 'user', content: text }];
    const toolHandler = createToolHandler(memory, userId, agentId, media);

    // Only pass tools for Anthropic and OpenAI (they support function calling)
    const modelInfo = modelKey === 'auto' ? null : getModel(modelKey);
    const supportsTools = !modelInfo || modelInfo.provider === 'anthropic' || modelInfo.provider === 'openai';

    const response = await llm.chat(
      modelKey,
      systemPrompt,
      messages,
      supportsTools ? BUILTIN_TOOLS : [],
      supportsTools ? toolHandler : null,
    );

    // Track usage
    usage.record(userId, response.model, response.words, response.billableWords, response.multiplier);
    memory.saveMessage(userId, agentId, 'user', text);
    memory.saveMessage(userId, agentId, 'assistant', response.text, response.tokens);

    // Build response with model badge
    const badge = `${response.modelIcon} _${response.modelName}_ · ${formatWords(response.billableWords)} words`;
    const fullResponse = `${response.text}\n\n${badge}`;

    await safeReply(ctx, fullResponse);

    // Warn at 80% usage
    const updated = usage.checkLimit(userId, planId);
    if (updated.percent >= 80 && updated.percent < 100) {
      await ctx.reply(`⚡ ${updated.percent}% of monthly word limit used. /usage for details.`);
    }

  } catch (err) {
    console.error(`Error for ${userId}:`, err);
    if (err.status === 429) await ctx.reply('⏳ Rate limited. Wait a moment.');
    else if (err.status === 401) await ctx.reply('🔑 API key error. Check your configuration.');
    else if (err.message?.includes('not configured')) await ctx.reply(`❌ ${err.message}`);
    else await ctx.reply('❌ Something went wrong. Try again or switch models with /models');
  }
});

// ── Scheduler ─────────────────────────────
const sendTg = async (userId, text) => {
  try { await bot.api.sendMessage(userId, text, { parse_mode: 'Markdown' }); }
  catch { try { await bot.api.sendMessage(userId, text); } catch {} }
};
// Pass a simple claude client for scheduler (uses default model)
const schedulerLLM = { chat: async (sys, msgs) => llm.chat('claude-haiku', sys, msgs) };
const scheduler = new Scheduler(memory, schedulerLLM, sendTg);

// ── Start ─────────────────────────────────

const models = listModels();

console.log('');
console.log('🦁 ══════════════════════════════════════');
console.log('   OpenGriffin — Multi-Model AI Agents');
console.log('   ══════════════════════════════════════');
console.log('');
console.log(`   🤖 Chat models:  ${models.length} via OpenRouter`);
console.log(`   🎨 Image models: ${media ? listImageModels().length : 0} via fal.ai`);
console.log(`   🎬 Video models: ${media ? listVideoModels().length : 0} via fal.ai`);
console.log(`   📂 Database:     ${process.env.DB_PATH || './data/opengriffin.db'}`);
console.log(`   🕐 Timezone:     ${process.env.SYSTEM_TIMEZONE || 'America/Chicago'}`);
console.log('');

bot.start({
  onStart: (botInfo) => {
    console.log(`   ✈️  Telegram:  @${botInfo.username} (connected)`);
    console.log('');
    if (process.env.ENABLE_SCHEDULER !== 'false') scheduler.start();
    console.log('   🟢 OpenGriffin is live.');
    console.log(`   🧠 ${models.length} models · ${listAgents().length} agents · Unlimited memory`);
    console.log('');
  },
});

// ── Graceful shutdown ─────────────────────
const shutdown = () => { scheduler.stop(); memory.close(); bot.stop(); process.exit(0); };
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
