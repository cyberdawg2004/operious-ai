"use client";

import { motion, useReducedMotion, type Variants } from "framer-motion";

const stagger: Variants = {
  hidden: {},
  show: {
    transition: {
      staggerChildren: 0.09,
      delayChildren: 0.08,
    },
  },
};

const fadeUp: Variants = {
  hidden: {
    opacity: 0,
    y: 22,
  },
  show: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.58,
      ease: [0.22, 1, 0.36, 1],
    },
  },
};

export function RevealGroup({
  children,
  className,
  mode = "view",
}: {
  children: React.ReactNode;
  className?: string;
  mode?: "load" | "view";
}) {
  const reducedMotion = useReducedMotion();

  if (reducedMotion) {
    return <div className={className}>{children}</div>;
  }

  return (
    <motion.div
      animate={mode === "load" ? "show" : undefined}
      className={className}
      initial="hidden"
      variants={stagger}
      viewport={{ once: true, amount: 0.18 }}
      whileInView={mode === "view" ? "show" : undefined}
    >
      {children}
    </motion.div>
  );
}

export function Reveal({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const reducedMotion = useReducedMotion();

  if (reducedMotion) {
    return <div className={className}>{children}</div>;
  }

  return (
    <motion.div className={className} variants={fadeUp}>
      {children}
    </motion.div>
  );
}
