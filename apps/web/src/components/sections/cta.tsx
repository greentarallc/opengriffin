"use client";

import { Reveal, RevealItem } from "@/components/motion/scroll-reveal";
import { GitHubIcon } from "@/components/icons/github";
import { motion, useReducedMotion } from "framer-motion";

export function Cta() {
  const reduce = useReducedMotion();
  return (
    <section className="relative px-6 py-32 sm:py-40 border-t border-[var(--color-border-soft)] overflow-hidden">
      <motion.div
        aria-hidden
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] h-[600px] rounded-full opacity-25 blur-3xl pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse, var(--color-brand) 0%, transparent 70%)",
        }}
        animate={reduce ? {} : { scale: [1, 1.1, 1] }}
        transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
      />

      <Reveal className="relative max-w-4xl mx-auto text-center">
        <RevealItem as="h2" className="text-4xl sm:text-6xl font-bold tracking-tight">
          Stop renting your agent.{" "}
          <span
            style={{
              background:
                "linear-gradient(120deg, var(--color-brand-soft), var(--color-alive-soft))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            Run it.
          </span>
        </RevealItem>
        <RevealItem as="p" className="mt-6 text-lg sm:text-xl text-[var(--color-text-dim)]">
          30 features. 21 providers. 7 platforms. Free forever.
        </RevealItem>
        <RevealItem className="mt-10 flex flex-wrap items-center justify-center gap-3">
          <a
            href="https://github.com/greentarallc/opengriffin"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 px-6 py-3 rounded-md font-semibold text-white shadow-[0_0_50px_-10px_var(--color-brand-glow)] hover:shadow-[0_0_70px_-10px_var(--color-brand-glow)] transition-shadow"
            style={{ backgroundColor: "var(--color-brand)" }}
          >
            <GitHubIcon size={18} />
            Star on GitHub
          </a>
          <a
            href="#install"
            className="px-6 py-3 rounded-md border border-[var(--color-border-soft)] hover:border-[var(--color-border-hover)] font-semibold text-[var(--color-text)] transition-colors"
          >
            Install
          </a>
        </RevealItem>
      </Reveal>
    </section>
  );
}
