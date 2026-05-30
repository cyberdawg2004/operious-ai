"use client";

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import {
  motion,
  useScroll,
  useSpring,
  useTransform,
} from "framer-motion";

import { cn } from "@/lib/utils";

export function TracingBeam({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [svgHeight, setSvgHeight] = useState(0);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start start", "end start"],
  });

  useEffect(() => {
    if (!contentRef.current) return;

    const updateHeight = () => {
      setSvgHeight(contentRef.current?.offsetHeight ?? 0);
    };
    updateHeight();

    const resizeObserver = new ResizeObserver(updateHeight);
    resizeObserver.observe(contentRef.current);

    return () => resizeObserver.disconnect();
  }, []);

  const y1 = useSpring(
    useTransform(scrollYProgress, [0, 0.8], [50, svgHeight]),
    { stiffness: 500, damping: 90 }
  );
  const y2 = useSpring(
    useTransform(scrollYProgress, [0, 1], [50, Math.max(50, svgHeight - 200)]),
    { stiffness: 500, damping: 90 }
  );

  return (
    <motion.div
      ref={ref}
      className={cn("relative mx-auto h-full w-full", className)}
    >
      <div className="pointer-events-none absolute -left-4 top-3 hidden md:block lg:-left-10">
        <div className="ml-[27px] flex h-4 w-4 items-center justify-center rounded-full border border-[#1A2744] bg-[#05080F] shadow-sm">
          <div className="h-2 w-2 rounded-full border border-[#C9A84C]/60 bg-[#C9A84C]" />
        </div>
        <svg
          viewBox={`0 0 20 ${svgHeight}`}
          width="20"
          height={svgHeight}
          className="ml-4 block"
          aria-hidden="true"
        >
          <motion.path
            d={`M 1 0V -36 l 18 24 V ${svgHeight * 0.8} l -18 24V ${svgHeight}`}
            fill="none"
            stroke="#7A90B4"
            strokeOpacity="0.18"
          />
          <motion.path
            d={`M 1 0V -36 l 18 24 V ${svgHeight * 0.8} l -18 24V ${svgHeight}`}
            fill="none"
            stroke="url(#operious-gradient)"
            strokeWidth="1.25"
            className="motion-reduce:hidden"
          />
          <defs>
            <motion.linearGradient
              id="operious-gradient"
              gradientUnits="userSpaceOnUse"
              x1="0"
              x2="0"
              y1={y1}
              y2={y2}
            >
              <stop stopColor="#2A5CAA" stopOpacity="0" />
              <stop stopColor="#2A5CAA" />
              <stop offset="0.45" stopColor="#C9A84C" />
              <stop offset="1" stopColor="#C9A84C" stopOpacity="0" />
            </motion.linearGradient>
          </defs>
        </svg>
      </div>
      <div ref={contentRef}>{children}</div>
    </motion.div>
  );
}
