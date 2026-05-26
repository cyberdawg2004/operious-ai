"use client";

import { motion, useInView } from "framer-motion";
import { useRef } from "react";

interface ContainmentLayerProps {
  number: string;
  title: string;
  description: string;
  index: number;
}

export function ContainmentLayer({
  number,
  title,
  description,
  index,
}: ContainmentLayerProps) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, x: -16 }}
      animate={inView ? { opacity: 1, x: 0 } : {}}
      transition={{ duration: 0.5, delay: index * 0.08 }}
      className="
        flex items-start gap-8 py-8
        border-b border-[#1A2744]
        group cursor-default
        hover:bg-white/[0.02]
        transition-colors duration-300
        px-4 -mx-4
      "
    >
      <span
        className="
          font-mono text-xs text-[#2A5CAA] pt-1
          shrink-0 w-8
        "
      >
        {number}
      </span>
      <div className="flex-1 grid gap-6 md:grid-cols-[200px_1fr]">
        <h3
          className="
            text-[#D8E4F4] font-medium text-sm
            group-hover:text-white transition-colors
          "
        >
          {title}
        </h3>
        <p className="text-[#7A90B4] text-sm leading-relaxed">{description}</p>
      </div>
    </motion.div>
  );
}
