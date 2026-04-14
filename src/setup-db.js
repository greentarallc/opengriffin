// ══════════════════════════════════════════
// OpenGriffin — Database Setup
// Run once before starting the bot:
//   npm run setup-db
// ══════════════════════════════════════════

import 'dotenv/config';
import { Memory } from './memory.js';
import { Billing } from './billing.js';
import { UsageTracker } from './plans.js';
import { mkdirSync } from 'fs';
import { dirname } from 'path';

const DB_PATH = process.env.DB_PATH || './data/opengriffin.db';

// Ensure data directory exists
try {
  mkdirSync(dirname(DB_PATH), { recursive: true });
} catch {}

console.log('');
console.log('🦁 OpenGriffin — Database Setup');
console.log('');
console.log(`   📂 Database path: ${DB_PATH}`);

const memory = new Memory();
await memory.init(DB_PATH);
console.log('   ✅ Core tables initialized (conversations, agent_memory, tasks, audit_log, usage)');

// Initialize billing table
const billing = new Billing(memory);
console.log('   ✅ Billing table initialized');

// Initialize usage table
const usage = new UsageTracker(memory);
console.log('   ✅ Usage table initialized');

// Save and close
memory.close();

console.log('');
console.log('   🟢 Database ready.');
console.log('');
console.log('   Next steps:');
console.log('   1. Copy .env.example to .env and fill in your API keys');
console.log('   2. Run: npm start');
console.log('');
