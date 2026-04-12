// ══════════════════════════════════════════
// OpenGriffin — Analytics
// Detailed usage reports, trends, cost
// estimates, and model recommendations.
// ══════════════════════════════════════════

import { getModel, listModels } from './llm-router.js';
import { getPlan, formatWords } from './plans.js';

export class Analytics {
  constructor(memory) {
    this.memory = memory;
  }

  /**
   * Full usage dashboard — text-based for Telegram
   */
  getDashboard(userId, planId) {
    const plan = getPlan(planId);
    const monthly = this._getMonthlyStats(userId);
    const daily = this._getDailyBreakdown(userId, 7);
    const modelBreakdown = this._getModelBreakdown(userId);
    const topupBalance = this._getTopupBalance(userId);
    const projection = this._projectUsage(userId, planId);

    let out = `📊 **Usage Dashboard — ${plan.name} Plan**\n\n`;

    // Usage bar
    const pct = Math.min(100, Math.round((monthly.billableWords / plan.wordLimit) * 100));
    const bar = _progressBar(pct);
    out += `${bar} ${pct}%\n`;
    out += `**${formatWords(monthly.billableWords)}** / ${formatWords(plan.wordLimit)} words used\n`;
    const remaining = Math.max(0, plan.wordLimit - monthly.billableWords);
    out += `Remaining: **${formatWords(remaining)}**`;
    if (topupBalance > 0) out += ` + ${formatWords(topupBalance)} top-up`;
    out += `\n\n`;

    // Cost efficiency
    if (monthly.calls > 0) {
      const avgMult = monthly.billableWords / (monthly.rawWords || 1);
      out += `**Efficiency:**\n`;
      out += `  Messages: ${monthly.calls}\n`;
      out += `  Avg multiplier: ${avgMult.toFixed(2)}x\n`;
      out += `  Raw words: ${formatWords(monthly.rawWords)}\n`;
      out += `  Billed words: ${formatWords(monthly.billableWords)}\n\n`;
    }

    // Model breakdown
    if (modelBreakdown.length > 0) {
      out += `**By model:**\n`;
      for (const m of modelBreakdown) {
        const model = getModel(m.model_key);
        const pctModel = Math.round((m.billed / monthly.billableWords) * 100);
        out += `  ${model?.icon || '·'} ${m.model_key}: ${formatWords(m.billed)} words (${pctModel}%, ${m.calls} msgs)\n`;
      }
      out += `\n`;
    }

    // 7-day trend
    if (daily.length > 0) {
      out += `**Last 7 days:**\n`;
      for (const d of daily) {
        const dayBar = _miniBar(d.billed, Math.max(...daily.map(x => x.billed)));
        out += `  ${d.date.slice(5)} ${dayBar} ${formatWords(d.billed)}\n`;
      }
      out += `\n`;
    }

    // Projection
    if (projection) {
      out += `**Projection:**\n`;
      out += `  At current pace: ~${formatWords(projection.projected)} words by month end\n`;
      if (projection.projected > plan.wordLimit) {
        const over = projection.projected - plan.wordLimit;
        out += `  ⚠️ ~${formatWords(over)} words over limit\n`;
        out += `  💡 Consider upgrading or using cheaper models\n`;
      } else {
        out += `  ✅ On track to stay within limit\n`;
      }
    }

    // Cost-saving tips
    const tips = this._getSavingTips(modelBreakdown, planId);
    if (tips.length > 0) {
      out += `\n**💡 Save words:**\n`;
      tips.forEach(t => out += `  → ${t}\n`);
    }

    return out;
  }

  /**
   * Quick usage summary (for /usage command)
   */
  getQuickSummary(userId, planId) {
    const plan = getPlan(planId);
    const monthly = this._getMonthlyStats(userId);
    const pct = Math.min(100, Math.round((monthly.billableWords / plan.wordLimit) * 100));
    const remaining = Math.max(0, plan.wordLimit - monthly.billableWords);
    const topup = this._getTopupBalance(userId);

    let out = `📊 **${plan.name}** — ${formatWords(monthly.billableWords)} / ${formatWords(plan.wordLimit)} (${pct}%)\n`;
    out += `Remaining: **${formatWords(remaining)}**`;
    if (topup > 0) out += ` + ${formatWords(topup)} top-up`;
    out += `\n${monthly.calls} messages this month`;
    out += `\n\n_Use /dashboard for full analytics_`;
    return out;
  }

  // ── Internal queries ────────────────────

  _getMonthlyStats(userId) {
    const row = this.memory._queryOne(
      `SELECT
         COALESCE(SUM(raw_words), 0) as rawWords,
         COALESCE(SUM(billable_words), 0) as billableWords,
         COUNT(*) as calls
       FROM usage
       WHERE user_id = ? AND created_at >= datetime('now', 'start of month')`,
      [userId]
    );
    return row || { rawWords: 0, billableWords: 0, calls: 0 };
  }

  _getDailyBreakdown(userId, days) {
    return this.memory._query(
      `SELECT
         date(created_at) as date,
         SUM(billable_words) as billed,
         COUNT(*) as calls
       FROM usage
       WHERE user_id = ? AND created_at >= datetime('now', '-${days} days')
       GROUP BY date(created_at)
       ORDER BY date ASC`,
      [userId]
    );
  }

  _getModelBreakdown(userId) {
    return this.memory._query(
      `SELECT model_key, SUM(raw_words) as raw, SUM(billable_words) as billed, COUNT(*) as calls
       FROM usage WHERE user_id = ? AND created_at >= datetime('now', 'start of month')
       GROUP BY model_key ORDER BY billed DESC`,
      [userId]
    );
  }

  _getTopupBalance(userId) {
    const row = this.memory._queryOne(
      'SELECT topup_words FROM billing WHERE user_id = ?', [userId]
    );
    return row?.topup_words ?? 0;
  }

  _projectUsage(userId, planId) {
    const now = new Date();
    const dayOfMonth = now.getDate();
    const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    if (dayOfMonth < 2) return null;

    const monthly = this._getMonthlyStats(userId);
    const dailyRate = monthly.billableWords / dayOfMonth;
    const projected = Math.round(dailyRate * daysInMonth);

    return { projected, dailyRate: Math.round(dailyRate) };
  }

  _getSavingTips(modelBreakdown, planId) {
    const tips = [];
    for (const m of modelBreakdown) {
      const model = getModel(m.model_key);
      if (!model) continue;
      if (model.mult >= 3.0 && m.calls > 5) {
        tips.push(`Switch from ${model.name} (${model.mult}x) to Claude Sonnet (1x) for routine tasks`);
      }
      if (model.mult >= 1.0 && m.model_key !== 'deepseek' && m.calls > 10) {
        tips.push(`Use DeepSeek (0.1x) for simple questions — 10x more words`);
      }
    }
    if (tips.length === 0 && modelBreakdown.length > 0) {
      tips.push('Use /model auto to let OpenGriffin pick the cheapest model per message');
    }
    return tips.slice(0, 3);
  }
}

// ── Helpers ─────────────────────────────

function _progressBar(pct) {
  const filled = Math.round(pct / 5);
  const empty = 20 - filled;
  return '▓'.repeat(filled) + '░'.repeat(empty);
}

function _miniBar(value, max) {
  if (max === 0) return '·····';
  const filled = Math.round((value / max) * 8);
  return '█'.repeat(filled) + '·'.repeat(8 - filled);
}
