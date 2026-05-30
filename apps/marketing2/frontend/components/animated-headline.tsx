"use client";
import { motion, useReducedMotion } from "framer-motion";

interface AnimatedHeadlineProps {
  children: string;
  className?: string;
  /** Words to render in italic gold gradient */
  accentWords?: string[];
}

export function AnimatedHeadline({
  children,
  className,
  accentWords = [],
}: AnimatedHeadlineProps) {
  const reducedMotion = useReducedMotion();
  const words = children.split(" ");

  if (reducedMotion) {
    return (
      <h1 className={className} style={{ fontFamily: "var(--font-serif)" }}>
        {children}
      </h1>
    );
  }

  return (
    <h1 className={className} aria-label={children} style={{ fontFamily: "var(--font-serif)" }}>
      {words.map((word, index) => {
        const isAccent = accentWords.includes(word);
        return (
          <motion.span
            aria-hidden="true"
            key={`${word}-${index}`}
            className="inline-block overflow-hidden align-bottom"
            initial={{ opacity: 0, y: "100%" }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: 0.3 + index * 0.07,
              duration: 0.75,
              ease: [0.16, 1, 0.3, 1],
            }}
          >
            {isAccent ? (
              <span
                className="italic"
                style={{
                  background:
                    "linear-gradient(130deg, #A8882C 0%, #C9A84C 35%, #E8C76A 65%, #C9A84C 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}
              >
                {word}
              </span>
            ) : (
              word
            )}
            {index < words.length - 1 ? " " : ""}
          </motion.span>
        );
      })}
    </h1>
  );
}
