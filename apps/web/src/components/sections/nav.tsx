"use client";

import * as React from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { GitHubIcon } from "@/components/icons/github";

function GriffinMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M12 2L4 6v6c0 5 3.5 9 8 10 4.5-1 8-5 8-10V6l-8-4zm0 7l3 2v3l-3 2-3-2v-3l3-2z" />
    </svg>
  );
}

export function Nav() {
  const { scrollY } = useScroll();
  const opacity = useTransform(scrollY, [0, 80], [0.35, 0.7]);

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--color-border-soft)]">
      <motion.div
        aria-hidden
        className="absolute inset-0 backdrop-blur"
        style={{ backgroundColor: "rgba(0,0,0,1)", opacity }}
      />
      <div className="relative max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
        <a
          href="/"
          className="flex items-center gap-2 font-semibold text-[var(--color-text)]"
        >
          <GriffinMark className="w-6 h-6 text-[var(--color-brand-soft)]" />
          <span>OpenGriffin</span>
          <span className="text-[10px] uppercase tracking-wider text-[var(--color-brand-soft)] border border-[var(--color-brand)]/40 rounded px-1.5 py-0.5 ml-1">
            OSS
          </span>
        </a>
        <nav className="hidden sm:flex items-center gap-6 text-sm text-[var(--color-text-dim)]">
          <a href="#features" className="hover:text-[var(--color-text)] transition-colors">
            Features
          </a>
          <a href="#install" className="hover:text-[var(--color-text)] transition-colors">
            Install
          </a>
          <a href="#why" className="hover:text-[var(--color-text)] transition-colors">
            Why
          </a>
          <a href="#faq" className="hover:text-[var(--color-text)] transition-colors">
            FAQ
          </a>
          <a
            href="https://github.com/greentarallc/opengriffin"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white text-black text-sm font-medium hover:bg-zinc-200 transition-colors"
          >
            <GitHubIcon size={14} />
            GitHub
          </a>
        </nav>
      </div>
    </header>
  );
}
