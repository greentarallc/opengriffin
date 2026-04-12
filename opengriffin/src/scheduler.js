// ══════════════════════════════════════════
// OpenGriffin — Scheduler
// Always-on cron jobs for proactive agents.
// ══════════════════════════════════════════

import cron from 'node-cron';

export class Scheduler {
  constructor(memory, claudeClient, sendTelegram) {
    this.memory = memory;
    this.claude = claudeClient;
    this.sendTelegram = sendTelegram; // function(userId, text) => sends Telegram message
    this.jobs = new Map();
  }

  /**
   * Start the default scheduled jobs
   */
  start() {
    const morningHour = process.env.MORNING_BRIEF_HOUR || 7;
    const eveningHour = process.env.EVENING_REVIEW_HOUR || 20;

    // Morning briefing — every day at configured hour
    this.addJob('morning-brief', `0 ${morningHour} * * *`, async () => {
      await this._runForAllUsers('morning_briefing');
    });

    // Evening review — every day at configured hour
    this.addJob('evening-review', `0 ${eveningHour} * * *`, async () => {
      await this._runForAllUsers('evening_review');
    });

    // Task reminder — every 4 hours during work hours
    this.addJob('task-reminder', '0 */4 * * *', async () => {
      await this._checkOverdueTasks();
    });

    // Data cleanup — daily at 3am, deletes data for cancelled accounts past 7-day retention
    this.addJob('data-cleanup', '0 3 * * *', async () => {
      try {
        const { runCleanup } = await import('./cleanup.js');
        const count = await runCleanup(process.env.DB_PATH);
        if (count > 0) console.log(`🧹 Cleanup: deleted ${count} expired account(s)`);
      } catch (err) { console.error('Cleanup error:', err.message); }
    });

    // Plan-gated: Weekly digest — Sundays at 9am (Pro + Agency only)
    this.addJob('weekly-digest', '0 9 * * 0', async () => {
      await this._runForPlanUsers(['pro', 'agency'], 'weekly_digest');
    });

    console.log(`⏰ Scheduler started: morning=${morningHour}:00, evening=${eveningHour}:00, cleanup=3:00`);
  }

  /**
   * Run a task only for users on specific plans
   */
  async _runForPlanUsers(allowedPlans, taskType) {
    try {
      const users = this.memory._query(
        `SELECT DISTINCT b.user_id FROM billing b WHERE b.plan_id IN (${allowedPlans.map(() => '?').join(',')})`,
        allowedPlans
      );
      for (const { user_id } of users) {
        await this._runScheduledTask(user_id, taskType);
      }
    } catch (err) { console.error(`Plan-gated task ${taskType} error:`, err.message); }
  }

  /**
   * Add a custom cron job
   */
  addJob(name, cronExpression, handler) {
    if (!cron.validate(cronExpression)) {
      console.error(`Invalid cron expression for ${name}: ${cronExpression}`);
      return false;
    }

    if (this.jobs.has(name)) {
      this.jobs.get(name).stop();
    }

    const job = cron.schedule(cronExpression, handler, {
      timezone: process.env.SYSTEM_TIMEZONE || 'America/Chicago',
    });

    this.jobs.set(name, job);
    return true;
  }

  /**
   * Run a scheduled prompt for all users who have an active agent
   */
  async _runForAllUsers(taskType) {
    // Get all unique users from the conversation history
    const users = this.memory.getDistinctUsers();

    for (const user_id of users) {
      try {
        const adminIds = (process.env.ADMIN_TELEGRAM_IDS || '').split(',');
        if (!adminIds.includes(user_id)) continue;

        await this._sendScheduledMessage(user_id, taskType);
      } catch (err) {
        console.error(`Scheduler error for user ${user_id}:`, err.message);
      }
    }
  }

  /**
   * Send a proactive scheduled message to a user
   */
  async _sendScheduledMessage(userId, taskType) {
    const tasks = this.memory.getPendingTasks(userId);
    const memories = this.memory.recallAll(userId, 'chief-of-staff');
    const stats = this.memory.getStats(userId);

    let prompt;
    if (taskType === 'morning_briefing') {
      prompt = `Generate a concise morning briefing for the user. Include:
- Good morning greeting (use their name if you know it)
- ${tasks.length} pending tasks (list top 3 by priority)
- Any tasks due today
- A motivating one-liner
Keep it under 200 words. Use emojis. This is Telegram.`;
    } else if (taskType === 'evening_review') {
      prompt = `Generate a concise evening review. Include:
- Summary of what was accomplished today
- ${tasks.length} remaining pending tasks
- Anything urgent for tomorrow
- A brief "good night" sign-off
Keep it under 150 words. Use emojis.`;
    } else {
      return;
    }

    const { text } = await this.claude.chat(
      `You are a Chief of Staff agent. User context: ${JSON.stringify(memories.slice(0, 10))}`,
      [{ role: 'user', content: prompt }],
    );

    if (text && this.sendTelegram) {
      await this.sendTelegram(userId, text);
      this.memory.log(userId, 'scheduler', taskType, text.substring(0, 100));
    }
  }

  /**
   * Check for overdue tasks and notify users
   */
  async _checkOverdueTasks() {
    const overdue = this.memory._query(`
      SELECT * FROM tasks
      WHERE status = 'pending' AND due_at IS NOT NULL AND due_at < datetime('now')
    `);

    for (const task of overdue) {
      if (this.sendTelegram) {
        await this.sendTelegram(
          task.user_id,
          `⚠️ **Overdue task:** ${task.title}\nPriority: ${task.priority}\nDue: ${task.due_at}\n\nReply "done" to mark complete, or "snooze" to push to tomorrow.`
        );
      }
    }
  }

  /**
   * Stop all jobs
   */
  stop() {
    for (const [name, job] of this.jobs) {
      job.stop();
    }
    this.jobs.clear();
    console.log('⏰ Scheduler stopped');
  }
}
