// ══════════════════════════════════════════
// OpenGriffin — Plans & Usage Tracking
// Word-based tiers inspired by Magai.
// ══════════════════════════════════════════

export const PLANS = {
  trial: {
    name: 'Free Trial',
    price: 0,
    wordLimit: 10000,       // 10K words for 24hr trial
    durationHours: 24,
    description: '24-hour full access',
  },
  starter: {
    name: 'Starter',
    price: 19,
    wordLimit: 100000,      // 100K words/month
    durationHours: null,    // monthly
    description: '100K words/month',
  },
  pro: {
    name: 'Pro',
    price: 39,
    wordLimit: 500000,      // 500K words/month
    durationHours: null,
    description: '500K words/month',
  },
  agency: {
    name: 'Agency',
    price: 79,
    wordLimit: 2000000,     // 2M words/month
    durationHours: null,
    description: '2M words/month',
  },
};

export function getPlan(planId) {
  return PLANS[planId] || PLANS['starter'];
}

export function listPlans() {
  return Object.entries(PLANS).map(([id, p]) => ({ id, ...p }));
}

/**
 * Format word count for display (e.g., 1,234 or 1.2M)
 */
export function formatWords(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return Math.floor(n).toLocaleString();
  return String(Math.floor(n));
}

/**
 * Usage tracker — works with the Memory module
 */
export class UsageTracker {
  constructor(memory) {
    this.memory = memory;
    this._ensureTable();
  }

  _ensureTable() {
    this.memory.db.run(`
      CREATE TABLE IF NOT EXISTS usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        model_key TEXT NOT NULL,
        raw_words INTEGER NOT NULL,
        billable_words INTEGER NOT NULL,
        multiplier REAL NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
      )
    `);
    this.memory.db.run(`CREATE INDEX IF NOT EXISTS idx_usage_user ON usage(user_id, created_at)`);
    this.memory._save();
  }

  /**
   * Record word usage
   */
  record(userId, modelKey, rawWords, billableWords, multiplier) {
    this.memory.db.run(
      `INSERT INTO usage (user_id, model_key, raw_words, billable_words, multiplier) VALUES (?, ?, ?, ?, ?)`,
      [userId, modelKey, rawWords, billableWords, multiplier]
    );
    this.memory._save();
  }

  /**
   * Get current month's billable word usage
   */
  getMonthlyUsage(userId) {
    const row = this.memory._queryOne(
      `SELECT COALESCE(SUM(billable_words), 0) as total FROM usage
       WHERE user_id = ? AND created_at >= datetime('now', 'start of month')`,
      [userId]
    );
    return row?.total ?? 0;
  }

  /**
   * Get today's usage (for trial tracking)
   */
  getDailyUsage(userId) {
    const row = this.memory._queryOne(
      `SELECT COALESCE(SUM(billable_words), 0) as total FROM usage
       WHERE user_id = ? AND created_at >= datetime('now', 'start of day')`,
      [userId]
    );
    return row?.total ?? 0;
  }

  /**
   * Get usage breakdown by model for current month
   */
  getUsageByModel(userId) {
    return this.memory._query(
      `SELECT model_key, SUM(raw_words) as raw, SUM(billable_words) as billed, COUNT(*) as calls
       FROM usage WHERE user_id = ? AND created_at >= datetime('now', 'start of month')
       GROUP BY model_key ORDER BY billed DESC`,
      [userId]
    );
  }

  /**
   * Check if user is within their plan limits
   */
  checkLimit(userId, planId) {
    const plan = getPlan(planId);
    const used = this.getMonthlyUsage(userId);
    const remaining = Math.max(0, plan.wordLimit - used);
    const pct = Math.min(100, Math.round((used / plan.wordLimit) * 100));
    return {
      used,
      limit: plan.wordLimit,
      remaining,
      percent: pct,
      exceeded: used >= plan.wordLimit,
    };
  }

  /**
   * Get formatted usage report
   */
  getUsageReport(userId, planId) {
    const { used, limit, remaining, percent, exceeded } = this.checkLimit(userId, planId);
    const plan = getPlan(planId);
    const byModel = this.getUsageByModel(userId);

    let report = `📊 **Usage Report — ${plan.name} Plan**\n\n`;
    report += `Words used: **${formatWords(used)}** / ${formatWords(limit)} (${percent}%)\n`;
    report += `Remaining: **${formatWords(remaining)}**\n`;

    if (byModel.length > 0) {
      report += `\n**By model:**\n`;
      for (const m of byModel) {
        report += `  ${m.model_key}: ${formatWords(m.raw)} raw → ${formatWords(m.billed)} billed (${m.calls} calls)\n`;
      }
    }

    if (exceeded) {
      report += `\n⚠️ You've reached your monthly limit. Upgrade your plan or wait for the next billing cycle.`;
    } else if (percent >= 80) {
      report += `\n⚡ You're at ${percent}% of your limit. Consider upgrading soon.`;
    }

    return report;
  }
}
