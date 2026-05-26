"use client";

import { useRef, type ReactNode } from "react";
import {
  motion,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionStyle,
  type MotionValue,
} from "framer-motion";

/**
 * Soft vertical parallax block. Translates its children opposite to scroll
 * while they're in the viewport. Pure CSS transforms — no layout thrash.
 */
export function ParallaxBlock({
  children,
  intensity = 0.18,
  className,
}: {
  children: ReactNode;
  /** 0 = static, 1 = strong. Sensible default for hero/section accents. */
  intensity?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();

  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });

  const range = 80 * intensity;
  const y = useTransform(scrollYProgress, [0, 1], [range, -range]);

  return (
    <div ref={ref} className={className}>
      <motion.div style={reducedMotion ? undefined : ({ y } as MotionStyle)}>
        {children}
      </motion.div>
    </div>
  );
}

function HighlightedWord({
  word,
  start,
  end,
  isLast,
  progress,
  baseColor,
  litColor,
  accentColor,
  reducedMotion,
}: {
  word: string;
  start: number;
  end: number;
  isLast: boolean;
  progress: MotionValue<number>;
  baseColor: string;
  litColor: string;
  accentColor: string;
  reducedMotion: boolean | null;
}) {
  const wordOpacity = useTransform(
    progress,
    [Math.max(0, start - 0.05), start, end],
    [0.35, 1, 1]
  );
  const wordColor = useTransform(
    progress,
    [start, (start + end) / 2, end, 1],
    [baseColor, litColor, litColor, isLast ? accentColor : litColor]
  );

  return (
    <motion.span
      className="inline-block"
      style={
        reducedMotion
          ? { color: litColor }
          : ({ opacity: wordOpacity, color: wordColor } as MotionStyle)
      }
    >
      {word}
      {!isLast ? "\u00a0" : ""}
    </motion.span>
  );
}

/**
 * Phrase whose color tracks scroll position. Lights each word as the
 * section advances through the viewport.
 */
export function ScrollHighlight({
  text,
  className,
  baseColor = "#7A90B4",
  litColor = "#F2F0EA",
  accentColor = "#C9A84C",
}: {
  text: string;
  className?: string;
  baseColor?: string;
  litColor?: string;
  accentColor?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();
  const words = text.split(" ");

  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start 0.85", "end 0.35"],
  });

  return (
    <div ref={ref} className={className}>
      {words.map((word, index) => {
        const start = index / words.length;
        const end = (index + 1) / words.length;
        return (
          <HighlightedWord
            key={`${word}-${index}`}
            word={word}
            start={start}
            end={end}
            isLast={index === words.length - 1}
            progress={scrollYProgress}
            baseColor={baseColor}
            litColor={litColor}
            accentColor={accentColor}
            reducedMotion={reducedMotion}
          />
        );
      })}
    </div>
  );
}
