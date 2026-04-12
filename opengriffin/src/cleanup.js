// ══════════════════════════════════════════
// OpenGriffin — Data Cleanup
// Deletes user data 7 days after cancellation.
// Run via cron or as standalone script.
// ══════════════════════════════════════════

import { Memory } from './memory.js';
import { Billing } from './billing.js';

export async function runCleanup(dbPath) {
  const path = dbPath || process.env.DB_PATH || './data/opengriffin.db';
  const memory = new Memory();
  await memory.init(path);
  const billing = new Billing(memory);

  const expired = billing.getExpiredAccounts();

  if (expired.length === 0) {
    console.log('🧹 No expired accounts to clean up.');
    memory.close();
    return 0;
  }

  console.log(`🧹 Found ${expired.length} expired account(s) to delete:`);

  for (const { user_id } of expired) {
    console.log(`   Deleting data for user ${user_id}...`);
    billing.deleteUserData(user_id);
    console.log(`   ✅ Deleted.`);
  }

  memory.close();
  console.log(`🧹 Cleanup complete. ${expired.length} account(s) purged.`);
  return expired.length;
}

// Run as standalone script
if (process.argv[1]?.endsWith('cleanup.js')) {
  import('dotenv/config').then(() => {
    runCleanup().then(count => {
      process.exit(count >= 0 ? 0 : 1);
    });
  });
}
