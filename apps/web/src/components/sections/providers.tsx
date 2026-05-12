"use client";

import { providers } from "@/lib/data";
import { Reveal, RevealItem } from "@/components/motion/scroll-reveal";
import { motion, useReducedMotion } from "framer-motion";

export function Providers() {
  const reduce = useReducedMotion();
  return (
    <section className="px-6 py-24 sm:py-32 border-t border-[var(--color-border-soft)]">
      <Reveal className="max-w-6xl mx-auto">
        <RevealItem as="h2" className="text-3xl sm:text-5xl font-bold tracking-tight">
          Bring any AI key.{" "}
          <span
            style={{
              background:
                "linear-gradient(120deg, var(--color-brand-soft), var(--color-alive-soft))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            21 providers supported.
          </span>
        </RevealItem>
        <RevealItem as="p" className="mt-4 text-[var(--color-text-dim)] max-w-2xl">
          No central account, no shared pool. Your keys, your bills, your data.
        </RevealItem>

        <motion.div
          className="mt-10 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3"
          variants={{ visible: { transition: { staggerChildren: 0.02 } } }}
        >
          {providers.map((p, i) => (
            <motion.div
              key={p}
              className="og-card rounded-lg px-4 py-3 text-center text-sm text-[var(--color-text)]"
              whileHover={reduce ? undefined : { y: -2, scale: 1.02 }}
              transition={{ type: "spring", stiffness: 320, damping: 22 }}
              variants={{
                hidden: { opacity: 0, y: 10 },
                visible: {
                  opacity: 1,
                  y: 0,
                  transition: {
                    duration: 0.35,
                    delay: reduce ? 0 : (i % 12) * 0.02,
                  },
                },
              }}
            >
              {p}
            </motion.div>
          ))}
        </motion.div>
      </Reveal>
    </section>
  );
}
