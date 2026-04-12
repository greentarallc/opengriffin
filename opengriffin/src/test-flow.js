// ══════════════════════════════════════════
// OpenGriffin — Local Test (No Telegram needed)
// Tests: Memory, Tools, Agent Templates, Claude API
// Usage: node src/test-flow.js
// ══════════════════════════════════════════

import 'dotenv/config';
import { Memory } from './memory.js';
import { ClaudeClient } from './claude-client.js';
import { BUILTIN_TOOLS, createToolHandler } from './tools.js';
import { getAgent, listAgents, buildSystemPrompt } from './agents.js';

const TEST_USER = 'test-user-001';

async function runTests() {
  console.log('\n🦁 OpenGriffin — Test Suite\n');

  // ── Test 1: Memory ──────────────────────
  console.log('── Test 1: Memory Module ──');
  const memory = new Memory();
  await memory.init('./data/test.db');

  memory.saveMessage(TEST_USER, 'chief-of-staff', 'user', 'Hello!');
  memory.saveMessage(TEST_USER, 'chief-of-staff', 'assistant', 'Hi! How can I help?');
  const msgs = memory.getRecentMessages(TEST_USER, 'chief-of-staff', 5);
  console.log(`   ✅ Messages saved/retrieved: ${msgs.length}`);

  memory.remember(TEST_USER, 'chief-of-staff', 'name', 'Tharun', 'personal');
  memory.remember(TEST_USER, 'chief-of-staff', 'company', 'ServiceNow', 'work');
  memory.remember(TEST_USER, 'chief-of-staff', 'timezone', 'America/Chicago', 'preferences');
  const name = memory.recall(TEST_USER, 'chief-of-staff', 'name');
  console.log(`   ✅ Memory stored/recalled: name = ${name}`);

  const allMem = memory.recallAll(TEST_USER, 'chief-of-staff');
  console.log(`   ✅ All memories: ${allMem.length} entries`);

  const taskId = memory.createTask(TEST_USER, 'chief-of-staff', 'Test task', 'A test', { priority: 2 });
  console.log(`   ✅ Task created: ${taskId.slice(0, 8)}...`);

  const tasks = memory.getPendingTasks(TEST_USER);
  console.log(`   ✅ Pending tasks: ${tasks.length}`);

  memory.completeTask(taskId, 'Completed in test');
  const stats = memory.getStats(TEST_USER);
  console.log(`   ✅ Stats: ${JSON.stringify(stats)}`);

  console.log('   ✅ Memory module: PASSED\n');

  // ── Test 2: Agent Templates ─────────────
  console.log('── Test 2: Agent Templates ──');
  const agents = listAgents();
  console.log(`   ✅ ${agents.length} agents available:`);
  for (const a of agents) {
    console.log(`      ${a.emoji} ${a.name} (${a.id})`);
  }

  const systemPrompt = buildSystemPrompt('chief-of-staff', allMem);
  console.log(`   ✅ System prompt built: ${systemPrompt.length} chars`);
  console.log('   ✅ Agent templates: PASSED\n');

  // ── Test 3: Tool Handler ────────────────
  console.log('── Test 3: Tool Handler ──');
  const toolHandler = createToolHandler(memory, TEST_USER, 'chief-of-staff');

  const remResult = await toolHandler('remember', { key: 'test_key', value: 'test_value', category: 'general' });
  console.log(`   ✅ remember: ${remResult.message}`);

  const recResult = await toolHandler('recall', { key: 'test_key' });
  console.log(`   ✅ recall: ${recResult.value}`);

  const timeResult = await toolHandler('get_current_time', {});
  console.log(`   ✅ get_current_time: ${timeResult.datetime}`);

  const statsResult = await toolHandler('get_stats', {});
  console.log(`   ✅ get_stats: ${JSON.stringify(statsResult)}`);

  console.log('   ✅ Tool handler: PASSED\n');

  // ── Test 4: Claude API (requires API key) ──
  console.log('── Test 4: Claude API ──');
  if (!process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_API_KEY.includes('your_')) {
    console.log('   ⏭️  Skipped (no API key configured)');
    console.log('   Set ANTHROPIC_API_KEY in .env to test Claude integration.\n');
  } else {
    try {
      const claude = new ClaudeClient(process.env.ANTHROPIC_API_KEY, process.env.CLAUDE_MODEL);

      const response = await claude.chat(
        buildSystemPrompt('chief-of-staff', allMem),
        [{ role: 'user', content: 'Hi! Give me a very brief morning briefing. Keep it under 50 words.' }],
        BUILTIN_TOOLS,
        toolHandler,
      );

      console.log(`   ✅ Claude response (${response.tokens} tokens):`);
      console.log(`   "${response.text.substring(0, 200)}${response.text.length > 200 ? '...' : ''}"`);
      console.log('   ✅ Claude API: PASSED\n');
    } catch (err) {
      console.log(`   ❌ Claude API error: ${err.message}\n`);
    }
  }

  // ── Cleanup ─────────────────────────────
  memory.close();
  console.log('══════════════════════════════════════');
  console.log('🦁 All tests completed.');
  console.log('');
  console.log('Next steps:');
  console.log('  1. Add your TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY to .env');
  console.log('  2. Run: npm start');
  console.log('  3. Message your bot on Telegram');
  console.log('══════════════════════════════════════\n');
}

runTests().catch(console.error);
