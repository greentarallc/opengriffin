"use client";

import { motion, useReducedMotion, type Variants } from "framer-motion";
import * as React from "react";

const baseContainer: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.06, delayChildren: 0.05 },
  },
};

const baseItem: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] },
  },
};

const reducedContainer: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.01 } },
};
const reducedItem: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.01 } },
};

type RevealProps = {
  className?: string;
  children?: React.ReactNode;
  as?: "div" | "section" | "ul" | "ol";
  amount?: number;
  once?: boolean;
  id?: string;
};

export function Reveal({
  as = "div",
  amount = 0.2,
  once = true,
  className,
  children,
  id,
}: RevealProps) {
  const reduce = useReducedMotion();
  const MotionTag = motion[as];
  return (
    <MotionTag
      id={id}
      className={className}
      variants={reduce ? reducedContainer : baseContainer}
      initial="hidden"
      whileInView="visible"
      viewport={{ once, amount }}
    >
      {children}
    </MotionTag>
  );
}

type ItemProps = {
  className?: string;
  children?: React.ReactNode;
  as?: "div" | "li" | "section" | "h2" | "h3" | "p";
};

export function RevealItem({
  as = "div",
  className,
  children,
}: ItemProps) {
  const reduce = useReducedMotion();
  const MotionTag = motion[as];
  return (
    <MotionTag
      className={className}
      variants={reduce ? reducedItem : baseItem}
    >
      {children}
    </MotionTag>
  );
}
