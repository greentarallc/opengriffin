"use client";

import { Reveal, RevealItem } from "@/components/motion/scroll-reveal";

export function Migration() {
  return (
    <section className="px-6 py-24 sm:py-32 border-t border-[var(--color-border-soft)]">
      <Reveal className="max-w-6xl mx-auto">
        <RevealItem as="h2" className="text-3xl sm:text-5xl font-bold tracking-tight">
          Migrating from another runtime?
        </RevealItem>
        <RevealItem as="p" className="mt-4 text-[var(--color-text-dim)] max-w-2xl">
          Built-in importers move your memories, cron jobs, and recent sessions
          into OpenGriffin's <code className="mono">~/.opengriffin/</code> layout
          in one command.
        </RevealItem>

        <RevealItem className="mt-8">
          <div className="og-card rounded-xl p-5 sm:p-6">
            <pre className="mono text-xs sm:text-sm overflow-x-auto">
              <code className="text-[var(--color-brand-soft)]">
                {`griffin migrate --list             # show available importers
griffin migrate from-<source>      # run an importer`}
              </code>
            </pre>
            <p className="text-[var(--color-text-dim)] text-sm mt-3">
              Imports MEMORY/USER/SOUL.md, cron schedules, channel directory,
              recent message history, and any local scripts. See{" "}
              <a href="https://github.com/greentarallc/opengriffin/blob/main/docs/migration.md" className="underline">
                docs/migration.md
              </a>{" "}
              for the full mapping.
            </p>
          </div>
        </RevealItem>
      </Reveal>
    </section>
  );
}
