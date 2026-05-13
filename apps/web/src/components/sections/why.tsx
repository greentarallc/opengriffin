"use client";

import { Reveal, RevealItem } from "@/components/motion/scroll-reveal";

const stops = [
  "Most agent runtimes remember, but don't self-evolve — no daily journal, no skill graph, no drift detection",
  "Multi-model chat dashboards are great UIs, not agents — they don't run cron, spawn sub-agents, or act between your messages",
  "Hosted assistants put your prompts and outputs on someone else's servers and ride someone else's uptime",
  "Few ship a critic, capability tokens, Merkle audit, or a dead-man's switch",
];

const answers = [
  "Persistent memory across sessions, days, years",
  "Daily 4:30am self-improvement loop writes its own journal",
  "Skills the agent authors, edits, and retires at runtime",
  "Long-running worker pool — agents that run for days",
  "100% local, BYO key, no signup, no backend, no telemetry",
];

export function Why() {
  return (
    <section
      id="why"
      className="px-6 py-24 sm:py-32 border-t border-[var(--color-border-soft)]"
    >
      <Reveal className="max-w-6xl mx-auto">
        <RevealItem
          as="h2"
          className="text-3xl sm:text-5xl font-bold tracking-tight max-w-3xl"
        >
          Existing agent tools forget.{" "}
          <span
            style={{
              background:
                "linear-gradient(120deg, var(--color-brand-soft), var(--color-alive-soft))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            OpenGriffin compounds.
          </span>
        </RevealItem>

        <div className="grid sm:grid-cols-2 gap-10 sm:gap-12 mt-12">
          <RevealItem>
            <h3 className="font-semibold text-[var(--color-text)] text-lg mb-3">
              Where existing tools stop
            </h3>
            <ul className="space-y-2.5 text-[var(--color-text-dim)] text-[15px] leading-relaxed">
              {stops.map((s) => (
                <li key={s} className="flex gap-3">
                  <span className="text-[var(--color-text-faint)] shrink-0">—</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </RevealItem>

          <RevealItem>
            <h3 className="font-semibold text-[var(--color-brand-soft)] text-lg mb-3">
              The OpenGriffin answer
            </h3>
            <ul className="space-y-2.5 text-[var(--color-text)] text-[15px] leading-relaxed">
              {answers.map((s) => (
                <li key={s} className="flex gap-3">
                  <span className="text-[var(--color-alive)] shrink-0">✓</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </RevealItem>
        </div>
      </Reveal>
    </section>
  );
}
