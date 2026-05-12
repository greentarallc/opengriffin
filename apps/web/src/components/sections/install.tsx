"use client";

import * as React from "react";
import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { Reveal, RevealItem } from "@/components/motion/scroll-reveal";

const INSTALL_CMD =
  "curl -fsSL https://raw.githubusercontent.com/greentarallc/opengriffin/main/scripts/install.sh | bash";

const STEPS = [
  {
    label: "Step 1",
    title: "BotFather token",
    body: (
      <>
        Open Telegram, message @BotFather, run <span className="mono">/newbot</span>.
        Save the token to <span className="mono">.env</span>.
      </>
    ),
  },
  {
    label: "Step 2",
    title: "Pick a provider",
    body: (
      <>
        Drop any of the 21 keys into <span className="mono">.env</span>. Or use
        Claude Max OAuth — no key needed.
      </>
    ),
  },
  {
    label: "Step 3",
    title: "opengriffin run",
    body: "Bot starts. Send it a message. Memory persists. Tomorrow at 4:30am the journal writes itself.",
  },
];

export function Install() {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(INSTALL_CMD);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section
      id="install"
      className="px-6 py-24 sm:py-32 border-t border-[var(--color-border-soft)]"
    >
      <Reveal className="max-w-6xl mx-auto">
        <RevealItem as="h2" className="text-3xl sm:text-5xl font-bold tracking-tight">
          One line.
        </RevealItem>
        <RevealItem as="p" className="mt-4 text-[var(--color-text-dim)] max-w-2xl">
          No account. No waitlist. No backend. Apache 2.0.
        </RevealItem>

        <RevealItem className="mt-10">
          <div className="og-card rounded-xl p-5 sm:p-6 relative">
            <pre className="mono text-xs sm:text-sm overflow-x-auto pr-12">
              <code className="text-[var(--color-brand-soft)]">{INSTALL_CMD}</code>
            </pre>
            <button
              type="button"
              onClick={handleCopy}
              aria-label={copied ? "Copied" : "Copy install command"}
              className="absolute top-4 right-4 h-8 w-8 rounded-md flex items-center justify-center hover:bg-white/5 transition-colors"
            >
              {copied ? (
                <Check className="w-4 h-4" style={{ color: "var(--color-alive)" }} />
              ) : (
                <Copy className="w-4 h-4" style={{ color: "var(--color-text-dim)" }} />
              )}
            </button>
            <p className="text-[var(--color-text-dim)] text-sm mt-3">
              Or with pip:{" "}
              <span className="mono text-[var(--color-brand-soft)]">
                pip install opengriffin && opengriffin run
              </span>
            </p>
          </div>
        </RevealItem>

        <div className="mt-10 grid sm:grid-cols-3 gap-4">
          {STEPS.map((s) => (
            <RevealItem key={s.label}>
              <div className="og-card rounded-xl p-5 h-full">
                <div className="text-[var(--color-brand-soft)] text-xs font-semibold uppercase tracking-wider">
                  {s.label}
                </div>
                <h3 className="mt-1 font-semibold text-[var(--color-text)]">
                  {s.title}
                </h3>
                <p className="text-sm text-[var(--color-text-dim)] mt-2 leading-relaxed">
                  {s.body}
                </p>
              </div>
            </RevealItem>
          ))}
        </div>
      </Reveal>
    </section>
  );
}
