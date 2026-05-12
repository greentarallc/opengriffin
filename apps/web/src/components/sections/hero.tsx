"use client";

import React, { useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Copy, Check, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { GitHubIcon } from "@/components/icons/github";

const INSTALL_CMD =
  "curl -fsSL https://raw.githubusercontent.com/greentarallc/opengriffin/main/scripts/install.sh | bash";

export function Hero() {
  const [copied, setCopied] = useState(false);
  const shouldReduceMotion = useReducedMotion();

  const handleCopy = async () => {
    await navigator.clipboard.writeText(INSTALL_CMD);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const staggerDelay = shouldReduceMotion ? 0 : 0.08;

  const container = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: staggerDelay,
        delayChildren: 0.1,
      },
    },
  };

  const item = {
    hidden: { opacity: 0, y: shouldReduceMotion ? 0 : 20 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        duration: shouldReduceMotion ? 0.01 : 0.5,
        ease: [0.22, 1, 0.36, 1] as const,
      },
    },
  };

  return (
    <section className="relative w-full overflow-hidden flex items-center justify-center px-4 py-24 sm:py-32">
      {/* Animated background glow */}
      <div className="absolute inset-0 pointer-events-none">
        <motion.div
          aria-hidden
          className="absolute top-[10%] left-1/2 -translate-x-1/2 w-[800px] h-[600px] rounded-full opacity-30 blur-3xl"
          style={{
            background:
              "radial-gradient(ellipse, var(--color-brand) 0%, transparent 65%)",
          }}
          animate={
            shouldReduceMotion
              ? {}
              : { scale: [1, 1.15, 1], opacity: [0.2, 0.35, 0.2] }
          }
          transition={{ duration: 9, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          aria-hidden
          className="absolute bottom-[5%] right-[10%] w-[420px] h-[420px] rounded-full opacity-20 blur-3xl"
          style={{
            background:
              "conic-gradient(from 0deg, var(--color-brand), var(--color-alive), var(--color-brand))",
          }}
          animate={shouldReduceMotion ? {} : { rotate: 360 }}
          transition={{ duration: 24, repeat: Infinity, ease: "linear" }}
        />
      </div>

      <motion.div
        className="relative z-10 max-w-4xl mx-auto text-center"
        variants={container}
        initial="hidden"
        animate="visible"
      >
        {/* Status pill */}
        <motion.div variants={item} className="flex justify-center mb-6">
          <Badge
            variant="outline"
            className="px-4 py-1.5 bg-background/60 backdrop-blur-sm border-[var(--color-border-soft)] flex items-center gap-2"
          >
            <span className="relative flex h-2 w-2">
              <span
                className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"
                style={{ backgroundColor: "var(--color-alive)" }}
              />
              <span
                className="relative inline-flex rounded-full h-2 w-2"
                style={{ backgroundColor: "var(--color-alive)" }}
              />
            </span>
            <Sparkles className="w-3 h-3" />
            <span className="text-xs font-medium tracking-wide">
              OSS · Apache 2.0 · self-evolving
            </span>
          </Badge>
        </motion.div>

        {/* Headline */}
        <motion.h1
          variants={item}
          className="text-5xl sm:text-6xl md:text-7xl font-bold tracking-tight leading-[1.05] mb-6"
        >
          <span className="block text-[var(--color-text)]">
            The personal AI agent
          </span>
          <span
            className="block mt-2"
            style={{
              background:
                "linear-gradient(135deg, var(--color-brand-soft) 0%, var(--color-brand) 45%, var(--color-alive-soft) 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            that compounds while you sleep.
          </span>
        </motion.h1>

        {/* Subhead */}
        <motion.p
          variants={item}
          className="text-base sm:text-lg max-w-2xl mx-auto mb-10 leading-relaxed"
          style={{ color: "var(--color-text-dim)" }}
        >
          Persistent memory across sessions. A daily journal at 4:30am. 21 AI
          providers, BYO key. Runs on your machine — no backend, no telemetry.
        </motion.p>

        {/* CTAs */}
        <motion.div
          variants={item}
          className="flex flex-col sm:flex-row gap-3 justify-center mb-12"
        >
          <Button
            size="lg"
            className="text-base px-7 h-12 font-semibold shadow-[0_0_40px_-10px_var(--color-brand-glow)] hover:shadow-[0_0_60px_-10px_var(--color-brand-glow)]"
            style={{ backgroundColor: "var(--color-brand)", color: "#fff" }}
            asChild
          >
            <a href="#install">Install in one line</a>
          </Button>
          <Button
            size="lg"
            variant="outline"
            className="text-base px-7 h-12 font-semibold bg-background/40 backdrop-blur-sm border-[var(--color-border-soft)] hover:border-[var(--color-border-hover)]"
            asChild
          >
            <a
              href="https://github.com/greentarallc/opengriffin"
              target="_blank"
              rel="noreferrer"
            >
              <GitHubIcon className="w-5 h-5 mr-1" />
              View on GitHub
            </a>
          </Button>
        </motion.div>

        {/* Install command */}
        <motion.div variants={item} className="flex justify-center">
          <Card className="inline-flex items-center gap-3 px-4 sm:px-5 py-3 bg-[var(--color-bg-elev)]/85 backdrop-blur-md border-[var(--color-border-soft)] shadow-2xl max-w-full">
            <code
              className="mono text-xs sm:text-sm truncate"
              style={{ color: "var(--color-text)" }}
            >
              {INSTALL_CMD}
            </code>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleCopy}
              aria-label={copied ? "Copied" : "Copy install command"}
              className="h-7 w-7 p-0 shrink-0"
            >
              {copied ? (
                <Check
                  className="w-4 h-4"
                  style={{ color: "var(--color-alive)" }}
                />
              ) : (
                <Copy
                  className="w-4 h-4"
                  style={{ color: "var(--color-text-dim)" }}
                />
              )}
            </Button>
          </Card>
        </motion.div>
      </motion.div>
    </section>
  );
}
