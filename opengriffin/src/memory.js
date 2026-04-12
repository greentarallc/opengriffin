// ══════════════════════════════════════════
// OpenGriffin — Memory Module (sql.js)
// Persistent memory that never resets.
// Pure JS SQLite — no native deps needed.
// ══════════════════════════════════════════

import initSqlJs from 'sql.js';
import fs from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';

export class Memory {
  constructor() {
    this.db = null;
    this.dbPath = null;
    this._saveTimer = null;
  }

  async init(dbPath) {
    this.dbPath = dbPath;
    const dir = path.dirname(dbPath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

    const SQL = await initSqlJs();

    if (fs.existsSync(dbPath)) {
      const buffer = fs.readFileSync(dbPath);
      this.db = new SQL.Database(buffer);
    } else {
      this.db = new SQL.Database();
    }

    this._migrate();
    return this;
  }

  _migrate() {
    this.db.run(`
      CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        tokens_used INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
      )
    `);
    this.db.run(`
      CREATE TABLE IF NOT EXISTS agent_memory (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'general',
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        source TEXT DEFAULT 'conversation',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(user_id, agent_id, key)
      )
    `);
    this.db.run(`
      CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        priority INTEGER DEFAULT 3,
        due_at TEXT,
        completed_at TEXT,
        result TEXT,
        cron_expression TEXT,
        created_at TEXT DEFAULT (datetime('now'))
      )
    `);
    this.db.run(`
      CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        agent_id TEXT,
        action TEXT NOT NULL,
        details TEXT,
        created_at TEXT DEFAULT (datetime('now'))
      )
    `);
    this.db.run(`CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, created_at)`);
    this.db.run(`CREATE INDEX IF NOT EXISTS idx_mem_user ON agent_memory(user_id, agent_id)`);
    this.db.run(`CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, status)`);
    this._save();
  }

  _save() {
    // Debounced save — writes at most every 500ms
    if (this._saveTimer) return;
    this._saveTimer = setTimeout(() => {
      this._saveTimer = null;
      if (this.dbPath && this.db) {
        const data = this.db.export();
        fs.writeFileSync(this.dbPath, Buffer.from(data));
      }
    }, 500);
  }

  _saveNow() {
    if (this._saveTimer) { clearTimeout(this._saveTimer); this._saveTimer = null; }
    if (this.dbPath && this.db) {
      const data = this.db.export();
      fs.writeFileSync(this.dbPath, Buffer.from(data));
    }
  }

  _uid() { return randomUUID().replace(/-/g, '').slice(0, 16); }

  _query(sql, params = []) {
    const stmt = this.db.prepare(sql);
    if (params.length) stmt.bind(params);
    const rows = [];
    while (stmt.step()) rows.push(stmt.getAsObject());
    stmt.free();
    return rows;
  }

  _queryOne(sql, params = []) {
    const rows = this._query(sql, params);
    return rows[0] || null;
  }

  _count(sql, params = []) {
    const row = this._queryOne(sql, params);
    return row ? Object.values(row)[0] : 0;
  }

  // ── Conversations ─────────────────────

  saveMessage(userId, agentId, role, content, tokensUsed = 0) {
    this.db.run(
      `INSERT INTO conversations (id, user_id, agent_id, role, content, tokens_used) VALUES (?, ?, ?, ?, ?, ?)`,
      [this._uid(), userId, agentId, role, content, tokensUsed]
    );
    this._save();
  }

  getRecentMessages(userId, agentId, limit = 20) {
    return this._query(
      `SELECT role, content, created_at FROM conversations WHERE user_id = ? AND agent_id = ? ORDER BY created_at DESC LIMIT ?`,
      [userId, agentId, limit]
    ).reverse();
  }

  getConversationHistory(userId, agentId, limit = 20) {
    return this.getRecentMessages(userId, agentId, limit).map(m => ({ role: m.role, content: m.content }));
  }

  clearConversations(userId) {
    this.db.run(`DELETE FROM conversations WHERE user_id = ?`, [userId]);
    this._save();
  }

  // ── Agent Memory ──────────────────────

  remember(userId, agentId, key, value, category = 'general', source = 'conversation') {
    this.db.run(
      `INSERT INTO agent_memory (id, user_id, agent_id, category, key, value, source)
       VALUES (?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(user_id, agent_id, key) DO UPDATE SET
         value = excluded.value, source = excluded.source, updated_at = datetime('now')`,
      [this._uid(), userId, agentId, category, key, value, source]
    );
    this._save();
  }

  recall(userId, agentId, key) {
    const row = this._queryOne(
      `SELECT value FROM agent_memory WHERE user_id = ? AND agent_id = ? AND key = ?`,
      [userId, agentId, key]
    );
    return row?.value ?? null;
  }

  recallAll(userId, agentId, category = null) {
    if (category) {
      return this._query(
        `SELECT key, value, category, updated_at FROM agent_memory WHERE user_id = ? AND agent_id = ? AND category = ? ORDER BY updated_at DESC`,
        [userId, agentId, category]
      );
    }
    return this._query(
      `SELECT key, value, category, updated_at FROM agent_memory WHERE user_id = ? AND agent_id = ? ORDER BY category, updated_at DESC`,
      [userId, agentId]
    );
  }

  forget(userId, agentId, key) {
    this.db.run(`DELETE FROM agent_memory WHERE user_id = ? AND agent_id = ? AND key = ?`, [userId, agentId, key]);
    this._save();
  }

  // ── Tasks ─────────────────────────────

  createTask(userId, agentId, title, description = '', options = {}) {
    const id = randomUUID();
    this.db.run(
      `INSERT INTO tasks (id, user_id, agent_id, title, description, priority, due_at, cron_expression) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [id, userId, agentId, title, description, options.priority ?? 3, options.dueAt ?? null, options.cron ?? null]
    );
    this._save();
    return id;
  }

  completeTask(taskId, result = '') {
    this.db.run(
      `UPDATE tasks SET status = 'done', result = ?, completed_at = datetime('now') WHERE id = ?`,
      [result, taskId]
    );
    this._save();
  }

  getPendingTasks(userId, agentId = null) {
    if (agentId) {
      return this._query(
        `SELECT * FROM tasks WHERE user_id = ? AND agent_id = ? AND status IN ('pending', 'in_progress') ORDER BY priority ASC, created_at ASC`,
        [userId, agentId]
      );
    }
    return this._query(
      `SELECT * FROM tasks WHERE user_id = ? AND status IN ('pending', 'in_progress') ORDER BY priority ASC, created_at ASC`,
      [userId]
    );
  }

  // ── Audit ─────────────────────────────

  log(userId, agentId, action, details = '') {
    this.db.run(
      `INSERT INTO audit_log (user_id, agent_id, action, details) VALUES (?, ?, ?, ?)`,
      [userId, agentId, action, details]
    );
  }

  // ── Stats ─────────────────────────────

  getStats(userId) {
    return {
      messages: this._count(`SELECT COUNT(*) FROM conversations WHERE user_id = ?`, [userId]),
      memories: this._count(`SELECT COUNT(*) FROM agent_memory WHERE user_id = ?`, [userId]),
      tasksDone: this._count(`SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'done'`, [userId]),
      tasksPending: this._count(`SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status IN ('pending', 'in_progress')`, [userId]),
    };
  }

  // ── Distinct Users (for scheduler) ────

  getDistinctUsers() {
    return this._query(`SELECT DISTINCT user_id FROM conversations`).map(r => r.user_id);
  }

  close() {
    this._saveNow();
    if (this.db) this.db.close();
  }
}
