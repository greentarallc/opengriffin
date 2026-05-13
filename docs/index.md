# OpenGriffin docs

The shipping README is the source of truth for getting started. These pages
cover the deeper topics.

## Topics

- [Architecture](architecture.md) — how the modules fit together
- [Providers](providers.md) — every supported AI backend, env vars, default models
- [Gateways](gateways/) — per-platform setup guides
- [Skills](skills.md) — authoring + installing community skills
- [Memory](memory.md) — MEMORY/USER/SOUL/CONSTRAINTS, Echo Memory, the daily journal
- [Security](security.md) — capability tokens, critic, attestation, dead-man's switch
- [Cron + Triggers](cron.md) — scheduled work and ambient signal mesh
- [Migration](migration.md) — importers for state from prior agent runtimes
- [Configuration](configuration.md) — every env var and config file

## Quick links

- Install: `curl -fsSL https://raw.githubusercontent.com/greentarallc/opengriffin/main/scripts/install.sh | bash`
- Config example: [`.env.example`](../.env.example)
- Bundled skills: [`bundled_skills/`](../bundled_skills/)
- Example configs: [`examples/`](../examples/)
- Migration tool: `griffin migrate --list` to see all importers
