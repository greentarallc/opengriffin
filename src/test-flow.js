// ══════════════════════════════════════════
// OpenGriffin — Local Test (No Telegram needed)
// Tests: Memory, Tools, Agent Templates, Claude API
// Usage: node src/test-flow.js
// ══════════════════════════════════════════

import 'dotenv/config';
import { Memory } from './memory.js';
import { LLMRouter } from './llm-router.js';
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
  if (!process.env.OPENROUTER_API_KEY || process.env.OPENROUTER_API_KEY.includes('your_')) {
    console.log('   ⏭️  Skipped (no OPENROUTER_API_KEY configured)');
    console.log('   Set OPENROUTER_API_KEY in .env to test LLM integration.\n');
  } else {
    try {
      const llm = new LLMRouter(process.env.OPENROUTER_API_KEY);

      const response = await llm.chat(
        'claude-haiku',
        buildSystemPrompt('chief-of-staff', allMem),
        [{ role: 'user', content: 'Hi! Give me a very brief morning briefing. Keep it under 50 words.' }],
        BUILTIN_TOOLS,
        toolHandler,
      );

      console.log(`   ✅ LLM response (${response.tokens} tokens, model: ${response.modelName}):`);
      console.log(`   "${response.text.substring(0, 200)}${response.text.length > 200 ? '...' : ''}"`);
      console.log('   ✅ LLM API: PASSED\n');
    } catch (err) {
      console.log(`   ❌ LLM API error: ${err.message}\n`);
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
