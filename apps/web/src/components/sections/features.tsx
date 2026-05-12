"use client";

import * as React from "react";
import { motion, useReducedMotion } from "framer-motion";
import { features } from "@/lib/data";
import { Reveal, RevealItem } from "@/components/motion/scroll-reveal";

const CATEGORY_COLORS: Record<string, string> = {
  Memory: "var(--color-brand-soft)",
  Compounding: "var(--color-brand-soft)",
  Skills: "var(--color-brand-soft)",
  Autonomous: "var(--color-alive-soft)",
  Triggers: "var(--color-alive-soft)",
  Security: "#f59e0b",
  "Multi-platform": "var(--color-brand-soft)",
  "Voice + Vision": "var(--color-alive-soft)",
  Ops: "var(--color-text-dim)",
};

function FeatureCard({
  category,
  title,
  body,
  index,
}: {
  category: string;
  title: string;
  body: React.ReactNode;
  index: number;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className="og-card rounded-xl p-5 relative overflow-hidden"
      whileHover={reduce ? undefined : { y: -2 }}
      transition={{ type: "spring", stiffness: 320, damping: 22 }}
      variants={{
        hidden: { opacity: 0, y: 20 },
        visible: {
          opacity: 1,
          y: 0,
          transition: {
            duration: 0.45,
            ease: [0.22, 1, 0.36, 1],
            delay: reduce ? 0 : (index % 6) * 0.035,
          },
        },
      }}
    >
      <div
        className="text-xs uppercase tracking-wider font-semibold"
        style={{ color: CATEGORY_COLORS[category] ?? "var(--color-brand-soft)" }}
      >
        {category}
      </div>
      <h3 className="mt-1 font-semibold text-[var(--color-text)]">{title}</h3>
      <p className="text-sm text-[var(--color-text-dim)] mt-2 leading-relaxed">
        {body}
      </p>
    </motion.div>
  );
}

export function Features() {
  return (
    <section
      id="features"
      className="px-6 py-24 sm:py-32 border-t border-[var(--color-border-soft)]"
    >
      <Reveal className="max-w-6xl mx-auto">
        <RevealItem as="p" className="text-[var(--color-brand-soft)] text-sm tracking-wide uppercase font-semibold">
          30 features · 33 MCP servers · 11 nightly auto-jobs
        </RevealItem>
        <RevealItem as="h2" className="mt-3 text-3xl sm:text-5xl font-bold tracking-tight">
          A complete personal-agent runtime.
        </RevealItem>
        <RevealItem as="p" className="mt-4 text-[var(--color-text-dim)] max-w-2xl">
          Every feature is local-first. None require an account or a subscription.
          Bring your own AI provider key for any of 21 supported backends.
        </RevealItem>

        <motion.div
          className="mt-12 grid md:grid-cols-2 lg:grid-cols-3 gap-4"
          variants={{ visible: { transition: { staggerChildren: 0.025 } } }}
        >
          {features.map((f, i) => (
            <FeatureCard
              key={f.title}
              category={f.category}
              title={f.title}
              body={f.body}
              index={i}
            />
          ))}
        </motion.div>
      </Reveal>
    </section>
  );
}
