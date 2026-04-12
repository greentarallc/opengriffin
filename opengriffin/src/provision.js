#!/usr/bin/env node
// ══════════════════════════════════════════
// OpenGriffin — Provisioning Script
// Automates new customer instance setup.
// Usage: node provision.js --user <telegram_id> --plan <plan> --bot-token <token>
// ══════════════════════════════════════════

import { parseArgs } from 'node:util';
import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { execSync } from 'node:child_process';

const { values } = parseArgs({
  options: {
    user:      { type: 'string', short: 'u' },
    plan:      { type: 'string', short: 'p', default: 'starter' },
    'bot-token': { type: 'string', short: 'b' },
    'openrouter-key': { type: 'string', short: 'o' },
    'fal-key': { type: 'string', short: 'f' },
    'deploy-dir': { type: 'string', short: 'd', default: '/opt/opengriffin/instances' },
    help:      { type: 'boolean', short: 'h' },
  },
});

if (values.help || !values.user || !values['bot-token']) {
  console.log(`
🦁 OpenGriffin Provisioning Script

Usage:
  node provision.js \\
    --user <telegram_user_id> \\
    --plan <starter|pro|agency> \\
    --bot-token <telegram_bot_token> \\
    --openrouter-key <key> \\
    --fal-key <key> \\
    --deploy-dir <path>

This script:
  1. Creates an isolated instance directory
  2. Generates .env with customer credentials
  3. Initializes the database with plan info
  4. Creates a systemd service file
  5. Enables and starts the service

Requirements:
  - Node.js 18+
  - systemd (Linux)
  - OpenGriffin source at /opt/opengriffin/app
  `);
  process.exit(0);
}

const userId = values.user;
const plan = values.plan;
const botToken = values['bot-token'];
const openrouterKey = values['openrouter-key'] || '';
const falKey = values['fal-key'] || '';
const baseDir = values['deploy-dir'];
const instanceDir = `${baseDir}/${userId}`;
const serviceName = `opengriffin-${userId}`;

console.log('');
console.log('🦁 OpenGriffin — Provisioning');
console.log('═══════════════════════════════');
console.log(`  User:     ${userId}`);
console.log(`  Plan:     ${plan}`);
console.log(`  Dir:      ${instanceDir}`);
console.log(`  Service:  ${serviceName}`);
console.log('');

// 1. Create instance directory
if (existsSync(instanceDir)) {
  console.log('⚠️  Instance directory already exists. Updating config...');
} else {
  mkdirSync(instanceDir, { recursive: true });
  mkdirSync(`${instanceDir}/data`, { recursive: true });
  console.log('✅ Created instance directory');
}

// 2. Generate .env
const envContent = `# OpenGriffin instance for user ${userId}
# Generated: ${new Date().toISOString()}

TELEGRAM_BOT_TOKEN=${botToken}
OPENROUTER_API_KEY=${openrouterKey}
FAL_API_KEY=${falKey}

DB_PATH=${instanceDir}/data/opengriffin.db
DEFAULT_AGENT=chief-of-staff
SYSTEM_TIMEZONE=America/Chicago
ENABLE_SCHEDULER=true
MORNING_BRIEF_HOUR=7
EVENING_REVIEW_HOUR=20
ADMIN_TELEGRAM_IDS=${userId}
`;

writeFileSync(`${instanceDir}/.env`, envContent);
console.log('✅ Generated .env');

// 3. Create systemd service
const serviceContent = `[Unit]
Description=OpenGriffin AI Agent (User ${userId})
After=network.target

[Service]
Type=simple
User=opengriffin
WorkingDirectory=/opt/opengriffin/app
EnvironmentFile=${instanceDir}/.env
ExecStart=/usr/bin/node src/index.js
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${serviceName}

[Install]
WantedBy=multi-user.target
`;

const serviceFile = `/etc/systemd/system/${serviceName}.service`;
writeFileSync(`${instanceDir}/${serviceName}.service`, serviceContent);
console.log(`✅ Generated systemd service → ${instanceDir}/${serviceName}.service`);

// 4. Print next steps
console.log('');
console.log('📋 Next steps:');
console.log(`  1. sudo cp ${instanceDir}/${serviceName}.service ${serviceFile}`);
console.log(`  2. sudo systemctl daemon-reload`);
console.log(`  3. sudo systemctl enable ${serviceName}`);
console.log(`  4. sudo systemctl start ${serviceName}`);
console.log(`  5. sudo journalctl -u ${serviceName} -f`);
console.log('');
console.log('🟢 Instance ready to deploy.');
