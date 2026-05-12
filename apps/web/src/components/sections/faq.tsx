"use client";

import * as React from "react";
import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { faqs } from "@/lib/data";
import { Reveal, RevealItem } from "@/components/motion/scroll-reveal";

function FaqItem({ q, a }: { q: string; a: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const reduce = useReducedMotion();

  return (
    <div className="og-card rounded-xl">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-4 p-5 text-left font-semibold text-[var(--color-text)] cursor-pointer"
      >
        <span>{q}</span>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: reduce ? 0 : 0.25, ease: "easeOut" }}
          className="shrink-0"
        >
          <ChevronDown
            className="w-5 h-5"
            style={{ color: "var(--color-text-dim)" }}
          />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: reduce ? 0 : 0.28, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 text-sm text-[var(--color-text-dim)] leading-relaxed">
              {a}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function Faq() {
  return (
    <section
      id="faq"
      className="px-6 py-24 sm:py-32 border-t border-[var(--color-border-soft)]"
    >
      <Reveal className="max-w-3xl mx-auto">
        <RevealItem as="h2" className="text-3xl sm:text-5xl font-bold tracking-tight">
          FAQ
        </RevealItem>
        <div className="mt-10 space-y-4">
          {faqs.map((f) => (
            <RevealItem key={f.q}>
              <FaqItem q={f.q} a={f.a} />
            </RevealItem>
          ))}
        </div>
      </Reveal>
    </section>
  );
}
