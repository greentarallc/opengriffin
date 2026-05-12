"use client";

import { Reveal, RevealItem } from "@/components/motion/scroll-reveal";

export function Migration() {
  return (
    <section className="px-6 py-24 sm:py-32 border-t border-[var(--color-border-soft)]">
      <Reveal className="max-w-6xl mx-auto">
        <RevealItem as="h2" className="text-3xl sm:text-5xl font-bold tracking-tight">
          Coming from Hermes or OpenClaw?
        </RevealItem>
        <RevealItem as="p" className="mt-4 text-[var(--color-text-dim)] max-w-2xl">
          Built-in migration imports your memories, cron jobs, and recent sessions
          in one command.
        </RevealItem>

        <RevealItem className="mt-8">
          <div className="og-card rounded-xl p-5 sm:p-6">
            <pre className="mono text-xs sm:text-sm overflow-x-auto">
              <code className="text-[var(--color-brand-soft)]">
                {`griffin migrate from-hermes
griffin migrate from-openclaw`}
              </code>
            </pre>
            <p className="text-[var(--color-text-dim)] text-sm mt-3">
              Imports MEMORY/USER/SOUL.md, cron schedules, channel directory,
              recent message history, and any local scripts.
            </p>
          </div>
        </RevealItem>
      </Reveal>
    </section>
  );
}
