// ══════════════════════════════════════════
// OpenGriffin — Billing (Stripe)
// Subscriptions, top-ups, customer portal.
// ══════════════════════════════════════════

import Stripe from 'stripe';

// Plan → Stripe Price ID mapping (set these after creating products in Stripe)
const PLAN_PRICE_IDS = {
  starter: process.env.STRIPE_PRICE_STARTER || '',
  pro:     process.env.STRIPE_PRICE_PRO     || '',
  agency:  process.env.STRIPE_PRICE_AGENCY  || '',
};

// Top-up amounts → word credits
const TOPUP_CREDITS = {
  5:  25000,   // $5  → 25K words
  10: 55000,   // $10 → 55K words (10% bonus)
  20: 120000,  // $20 → 120K words (20% bonus)
};

export class Billing {
  constructor(memory) {
    this.memory = memory;
    if (!process.env.STRIPE_SECRET_KEY) {
      console.warn('⚠️  STRIPE_SECRET_KEY not set — billing disabled');
      this.stripe = null;
    } else {
      this.stripe = new Stripe(process.env.STRIPE_SECRET_KEY);
    }
    this._ensureTable();
  }

  get enabled() { return !!this.stripe; }

  _ensureTable() {
    this.memory.db.run(`
      CREATE TABLE IF NOT EXISTS billing (
        user_id TEXT PRIMARY KEY,
        stripe_customer_id TEXT,
        plan_id TEXT DEFAULT 'trial',
        subscription_id TEXT,
        topup_words INTEGER DEFAULT 0,
        trial_started_at TEXT,
        cancelled_at TEXT,
        delete_after TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
      )
    `);
    this.memory._save();
  }

  // ── Customer management ─────────────────

  async getOrCreateCustomer(userId, email, name) {
    const row = this.memory._queryOne(
      'SELECT stripe_customer_id FROM billing WHERE user_id = ?', [userId]
    );

    if (row?.stripe_customer_id) {
      return row.stripe_customer_id;
    }

    const customer = await this.stripe.customers.create({
      email,
      name,
      metadata: { telegram_user_id: userId },
    });

    this.memory.db.run(
      `INSERT OR REPLACE INTO billing (user_id, stripe_customer_id, plan_id)
       VALUES (?, ?, COALESCE((SELECT plan_id FROM billing WHERE user_id = ?), 'trial'))`,
      [userId, customer.id, userId]
    );
    this.memory._save();

    return customer.id;
  }

  // ── Subscription management ─────────────

  async createCheckoutSession(userId, planId, successUrl, cancelUrl) {
    if (!this.enabled) throw new Error('Billing not configured');

    const priceId = PLAN_PRICE_IDS[planId];
    if (!priceId) throw new Error(`No Stripe price for plan: ${planId}`);

    const customerId = await this._getCustomerId(userId);

    const session = await this.stripe.checkout.sessions.create({
      customer: customerId || undefined,
      mode: 'subscription',
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: successUrl || 'https://opengriffin.com/success',
      cancel_url: cancelUrl || 'https://opengriffin.com/cancel',
      metadata: { telegram_user_id: userId, plan_id: planId },
    });

    return session.url;
  }

  async createPortalSession(userId) {
    if (!this.enabled) throw new Error('Billing not configured');

    const customerId = await this._getCustomerId(userId);
    if (!customerId) throw new Error('No billing account found. Use /subscribe first.');

    const session = await this.stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: 'https://opengriffin.com',
    });

    return session.url;
  }

  // ── Top-ups ─────────────────────────────

  async createTopupSession(userId, amount) {
    if (!this.enabled) throw new Error('Billing not configured');
    if (![5, 10, 20].includes(amount)) throw new Error('Top-up must be $5, $10, or $20');

    const customerId = await this._getCustomerId(userId);
    const words = TOPUP_CREDITS[amount];

    const session = await this.stripe.checkout.sessions.create({
      customer: customerId || undefined,
      mode: 'payment',
      line_items: [{
        price_data: {
          currency: 'usd',
          product_data: {
            name: `OpenGriffin Top-Up — ${(words / 1000).toFixed(0)}K words`,
            description: `${(words).toLocaleString()} additional words`,
          },
          unit_amount: amount * 100,
        },
        quantity: 1,
      }],
      success_url: 'https://opengriffin.com/topup-success',
      cancel_url: 'https://opengriffin.com',
      metadata: { telegram_user_id: userId, topup_words: String(words), amount: String(amount) },
    });

    return { url: session.url, words };
  }

  /**
   * Credit top-up words to user (called from webhook)
   */
  creditTopup(userId, words) {
    this.memory.db.run(
      `UPDATE billing SET topup_words = topup_words + ?, updated_at = datetime('now') WHERE user_id = ?`,
      [words, userId]
    );
    this.memory._save();
  }

  /**
   * Get remaining top-up words
   */
  getTopupBalance(userId) {
    const row = this.memory._queryOne('SELECT topup_words FROM billing WHERE user_id = ?', [userId]);
    return row?.topup_words ?? 0;
  }

  /**
   * Deduct from top-up balance (used when plan limit exceeded but top-up available)
   */
  deductTopup(userId, words) {
    const balance = this.getTopupBalance(userId);
    if (balance <= 0) return false;
    const deduct = Math.min(balance, words);
    this.memory.db.run(
      'UPDATE billing SET topup_words = topup_words - ?, updated_at = datetime(\'now\') WHERE user_id = ?',
      [deduct, userId]
    );
    this.memory._save();
    return true;
  }

  // ── Plan management ─────────────────────

  getUserPlan(userId) {
    const row = this.memory._queryOne('SELECT plan_id FROM billing WHERE user_id = ?', [userId]);
    return row?.plan_id ?? 'trial';
  }

  setUserPlan(userId, planId, subscriptionId = null) {
    this.memory.db.run(
      `INSERT INTO billing (user_id, plan_id, subscription_id, cancelled_at, delete_after, updated_at)
       VALUES (?, ?, ?, NULL, NULL, datetime('now'))
       ON CONFLICT(user_id) DO UPDATE SET
         plan_id = ?, subscription_id = ?, cancelled_at = NULL, delete_after = NULL, updated_at = datetime('now')`,
      [userId, planId, subscriptionId, planId, subscriptionId]
    );
    this.memory._save();
  }

  // ── Cancellation + data retention ───────

  cancelSubscription(userId) {
    this.memory.db.run(
      `UPDATE billing SET
         cancelled_at = datetime('now'),
         delete_after = datetime('now', '+7 days'),
         updated_at = datetime('now')
       WHERE user_id = ?`,
      [userId]
    );
    this.memory._save();
  }

  /**
   * Get accounts scheduled for deletion (past their 7-day retention)
   */
  getExpiredAccounts() {
    return this.memory._query(
      `SELECT user_id FROM billing
       WHERE delete_after IS NOT NULL AND delete_after <= datetime('now')`,
      []
    );
  }

  /**
   * Permanently delete user data
   */
  deleteUserData(userId) {
    this.memory.db.run('DELETE FROM conversations WHERE user_id = ?', [userId]);
    this.memory.db.run('DELETE FROM agent_memory WHERE user_id = ?', [userId]);
    this.memory.db.run('DELETE FROM tasks WHERE user_id = ?', [userId]);
    this.memory.db.run('DELETE FROM audit_log WHERE user_id = ?', [userId]);
    this.memory.db.run('DELETE FROM usage WHERE user_id = ?', [userId]);
    this.memory.db.run('DELETE FROM billing WHERE user_id = ?', [userId]);
    this.memory._save();
  }

  // ── Webhook handling ────────────────────

  async handleWebhook(rawBody, signature) {
    if (!this.enabled) return;

    const event = this.stripe.webhooks.constructEvent(
      rawBody,
      signature,
      process.env.STRIPE_WEBHOOK_SECRET
    );

    switch (event.type) {
      case 'checkout.session.completed': {
        const session = event.data.object;
        const userId = session.metadata?.telegram_user_id;
        if (!userId) break;

        if (session.mode === 'subscription') {
          const planId = session.metadata?.plan_id || 'starter';
          this.setUserPlan(userId, planId, session.subscription);
          return { type: 'subscription', userId, planId };
        }

        if (session.mode === 'payment') {
          const words = parseInt(session.metadata?.topup_words || '0');
          if (words > 0) {
            this.creditTopup(userId, words);
            return { type: 'topup', userId, words };
          }
        }
        break;
      }

      case 'customer.subscription.deleted': {
        const sub = event.data.object;
        const customer = await this.stripe.customers.retrieve(sub.customer);
        const userId = customer.metadata?.telegram_user_id;
        if (userId) {
          this.cancelSubscription(userId);
          return { type: 'cancelled', userId };
        }
        break;
      }

      case 'customer.subscription.updated': {
        const sub = event.data.object;
        const customer = await this.stripe.customers.retrieve(sub.customer);
        const userId = customer.metadata?.telegram_user_id;
        if (userId && sub.status === 'active') {
          // Plan might have changed via Stripe portal
          const priceId = sub.items.data[0]?.price?.id;
          const planId = Object.entries(PLAN_PRICE_IDS).find(([, v]) => v === priceId)?.[0];
          if (planId) this.setUserPlan(userId, planId, sub.id);
          return { type: 'updated', userId, planId };
        }
        break;
      }
    }

    return null;
  }

  // ── Helpers ─────────────────────────────

  async _getCustomerId(userId) {
    const row = this.memory._queryOne('SELECT stripe_customer_id FROM billing WHERE user_id = ?', [userId]);
    return row?.stripe_customer_id || null;
  }
}

export { TOPUP_CREDITS };
