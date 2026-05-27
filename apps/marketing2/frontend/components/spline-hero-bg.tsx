"use client";

import { useRef } from "react";
import { motion, useReducedMotion, useScroll, useTransform } from "framer-motion";

/**
 * Spline embedded background with:
 *  - subtle parallax tied to page scroll
 *  - bottom-right mask that hides the "Built with Spline" watermark
 *    (the free Spline export cannot disable the badge programmatically,
 *    so we cover it with a panel that matches the page tone)
 */
export function SplineHeroBg() {
  const reducedMotion = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);

  const { scrollY } = useScroll();
  const parallaxY = useTransform(scrollY, [0, 800], [0, 140]);
  const parallaxScale = useTransform(scrollY, [0, 600], [1, 1.06]);
  const overlayOpacity = useTransform(scrollY, [0, 500], [0.75, 0.92]);

  return (
    <div
      ref={containerRef}
      className="pointer-events-none absolute inset-0 z-0 overflow-hidden"
      aria-hidden="true"
    >
      <motion.div
        className="absolute inset-0"
        style={
          reducedMotion
            ? undefined
            : { y: parallaxY, scale: parallaxScale }
        }
      >
        <iframe
          src="https://my.spline.design/motiontrails-LkkaFYHfse20s2oaEX8yXTPR/"
          frameBorder={0}
          width="100%"
          height="100%"
          className="absolute inset-0 h-full w-full"
          style={{ border: "none" }}
          loading="lazy"
          title="Operious motion trails background"
        />
        {/* Watermark mask — covers the bottom-right Spline badge. */}
        <div
          className="pointer-events-auto absolute bottom-0 right-0 h-[64px] w-[180px] bg-[#05080F]"
          style={{
            boxShadow:
              "inset 24px 24px 32px -16px #05080F, inset 0 0 24px 0 #05080F",
          }}
        />
        {/* Soft gradient feather so the mask blends with the scene. */}
        <div
          className="pointer-events-none absolute bottom-0 right-0 h-[120px] w-[260px]"
          style={{
            background:
              "linear-gradient(315deg, #05080F 0%, #05080F 32%, rgba(5,8,15,0) 75%)",
          }}
        />
      </motion.div>
      <motion.div
        className="absolute inset-0 bg-[#05080F]"
        style={reducedMotion ? { opacity: 0.75 } : { opacity: overlayOpacity }}
      />
    </div>
  );
}
