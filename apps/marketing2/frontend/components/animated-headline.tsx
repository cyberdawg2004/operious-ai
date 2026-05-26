"use client";

import { motion, useReducedMotion } from "framer-motion";

export function AnimatedHeadline({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  const reducedMotion = useReducedMotion();
  const words = children.split(" ");

  if (reducedMotion) {
    return <h1 className={className}>{children}</h1>;
  }

  return (
    <h1 className={className} aria-label={children}>
      {words.map((word, index) => (
        <motion.span
          aria-hidden="true"
          className="inline-block overflow-hidden align-bottom"
          initial={{ opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            delay: 0.08 + index * 0.035,
            duration: 0.58,
            ease: [0.22, 1, 0.36, 1],
          }}
          key={`${word}-${index}`}
        >
          {word}
          {index < words.length - 1 ? "\u00a0" : ""}
        </motion.span>
      ))}
    </h1>
  );
}
