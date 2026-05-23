"use client";

import { motion } from "framer-motion";

// Official Operious AI KernelSeal - Exact match to brand image
// Features: Concentric hexagons, gold corner accents, center dot

const C = {
  bg: "#05080F",
  surface: "#0B1120",
  border: "#1A2744",
  goldHi: "#C9A84C",
  goldMid: "#A8882C",
  goldLo: "#6B5418",
  blueHi: "#2A6BCC",
  blueMid: "#1A4A9A",
  blueLo: "#0D2860",
  textHi: "#D8E4F4",
  hexStroke: "#2A3A5A", // Subtle blue-gray for hexagons
};

function hexPoints(cx: number, cy: number, r: number): [number, number][] {
  return Array.from({ length: 6 }, (_, i) => {
    const angle = (Math.PI / 3) * i - Math.PI / 2;
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)] as [number, number];
  });
}

function pointsToPath(pts: [number, number][]): string {
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ') + ' Z';
}

interface KernelSealProps {
  size?: number;
  phase?: 0 | 1 | 2 | 3;
  className?: string;
  showBackground?: boolean;
  animated?: boolean;
}

export function KernelSeal({
  size = 80,
  phase = 3,
  className,
  showBackground = false,
  animated = true,
}: KernelSealProps) {
  const cx = size / 2;
  const cy = size / 2;
  
  // Hexagon radii (from outer to inner)
  const rOuter = size * 0.42;
  const rMid = size * 0.30;
  const rInner = size * 0.18;
  
  const sw = Math.max(1, size * 0.012); // Stroke width

  const ptsOuter = hexPoints(cx, cy, rOuter);
  const ptsMid = hexPoints(cx, cy, rMid);
  const ptsInner = hexPoints(cx, cy, rInner);

  const uid = `ks-${size}-${Math.random().toString(36).slice(2, 7)}`;
  const gradId = `${uid}-grad`;
  const glowId = `${uid}-glow`;

  // Corner accent positions (top-left and top-right outer corners)
  const cornerLength = size * 0.08;
  
  // Animation variants
  const hexVariants = {
    hidden: { pathLength: 0, opacity: 0 },
    visible: (delay: number) => ({
      pathLength: 1,
      opacity: 1,
      transition: {
        pathLength: { duration: 1.2, delay, ease: [0.22, 1, 0.36, 1] },
        opacity: { duration: 0.3, delay },
      },
    }),
  };

  const dotVariants = {
    hidden: { scale: 0, opacity: 0 },
    visible: {
      scale: 1,
      opacity: 1,
      transition: { duration: 0.5, delay: 1.2, ease: [0.22, 1, 0.36, 1] },
    },
  };

  const accentVariants = {
    hidden: { opacity: 0, pathLength: 0 },
    visible: (delay: number) => ({
      opacity: 1,
      pathLength: 1,
      transition: { duration: 0.6, delay, ease: "easeOut" },
    }),
  };

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <defs>
        {/* Gold gradient */}
        <linearGradient id={gradId} x1="50%" y1="0%" x2="50%" y2="100%">
          <stop offset="0%" stopColor={C.goldHi} />
          <stop offset="100%" stopColor={C.goldMid} />
        </linearGradient>

        {/* Glow filter */}
        <filter id={glowId} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation={size * 0.02} result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Background */}
      {showBackground && (
        <rect
          x={0}
          y={0}
          width={size}
          height={size}
          rx={size * 0.12}
          fill={C.bg}
        />
      )}

      {/* Outer hexagon */}
      <motion.path
        d={pointsToPath(ptsOuter)}
        stroke={C.hexStroke}
        strokeWidth={sw * 1.5}
        fill="none"
        initial={animated ? "hidden" : "visible"}
        animate="visible"
        variants={hexVariants}
        custom={0}
      />

      {/* Middle hexagon */}
      <motion.path
        d={pointsToPath(ptsMid)}
        stroke={C.hexStroke}
        strokeWidth={sw}
        fill="none"
        opacity={0.7}
        initial={animated ? "hidden" : "visible"}
        animate="visible"
        variants={hexVariants}
        custom={0.3}
      />

      {/* Inner hexagon */}
      <motion.path
        d={pointsToPath(ptsInner)}
        stroke={C.hexStroke}
        strokeWidth={sw * 0.8}
        fill="none"
        opacity={0.5}
        initial={animated ? "hidden" : "visible"}
        animate="visible"
        variants={hexVariants}
        custom={0.5}
      />

      {/* Gold corner accents - top left */}
      <motion.path
        d={`M${ptsOuter[5][0] - cornerLength * 0.7},${ptsOuter[5][1] + cornerLength * 0.4} L${ptsOuter[5][0]},${ptsOuter[5][1]} L${ptsOuter[5][0] + cornerLength * 0.7},${ptsOuter[5][1] + cornerLength * 0.4}`}
        stroke={C.goldHi}
        strokeWidth={sw * 2}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
        filter={`url(#${glowId})`}
        initial={animated ? "hidden" : "visible"}
        animate="visible"
        variants={accentVariants}
        custom={0.8}
      />

      {/* Gold corner accents - top right */}
      <motion.path
        d={`M${ptsOuter[0][0] - cornerLength * 0.7},${ptsOuter[0][1] + cornerLength * 0.4} L${ptsOuter[0][0]},${ptsOuter[0][1]} L${ptsOuter[0][0] + cornerLength * 0.7},${ptsOuter[0][1] + cornerLength * 0.4}`}
        stroke={C.goldHi}
        strokeWidth={sw * 2}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
        filter={`url(#${glowId})`}
        initial={animated ? "hidden" : "visible"}
        animate="visible"
        variants={accentVariants}
        custom={0.9}
      />

      {/* Gold corner accents - bottom */}
      <motion.path
        d={`M${ptsOuter[2][0] + cornerLength * 0.7},${ptsOuter[2][1] - cornerLength * 0.4} L${ptsOuter[2][0]},${ptsOuter[2][1]} L${ptsOuter[2][0] - cornerLength * 0.7},${ptsOuter[2][1] - cornerLength * 0.4}`}
        stroke={C.goldHi}
        strokeWidth={sw * 2}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
        filter={`url(#${glowId})`}
        initial={animated ? "hidden" : "visible"}
        animate="visible"
        variants={accentVariants}
        custom={1.0}
      />

      {/* Center dot */}
      <motion.circle
        cx={cx}
        cy={cy}
        r={size * 0.025}
        fill={C.textHi}
        initial={animated ? "hidden" : "visible"}
        animate="visible"
        variants={dotVariants}
      />
    </svg>
  );
}

/* ─── Full Lockup Component ────────────────────────────── */
interface LockupProps {
  iconSize?: number;
  phase?: 0 | 1 | 2 | 3;
  theme?: "dark" | "light";
  className?: string;
  showBackground?: boolean;
}

export function Lockup({
  iconSize = 72,
  phase = 3,
  theme = "dark",
  className,
  showBackground = false,
}: LockupProps) {
  const isDark = theme === "dark";
  const nameColor = isDark ? C.textHi : "#0B1526";
  const tagColor = isDark ? "#5A6A8A" : "#7A90B4";
  const badgeBorder = isDark ? C.border : "#B8CAE4";
  const badgeText = isDark ? C.blueHi : C.blueMid;

  return (
    <div
      className={className}
      style={{
        display: "flex",
        alignItems: "center",
        gap: iconSize * 0.3,
      }}
    >
      <KernelSeal size={iconSize} phase={phase} showBackground={showBackground} />

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: iconSize * 0.055,
        }}
      >
        {/* Name row */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 10 }}>
          <motion.span
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.6, delay: 0.8, ease: [0.22, 1, 0.36, 1] }}
            style={{
              fontFamily: "var(--font-cormorant-sc), 'Cormorant SC', serif",
              fontWeight: 700,
              fontSize: iconSize * 0.52,
              letterSpacing: "0.04em",
              color: nameColor,
              lineHeight: 1,
            }}
          >
            Operious
          </motion.span>

          {/* AI badge */}
          <motion.span
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5, delay: 1.2 }}
            style={{
              fontFamily: "var(--font-ibm-plex-mono), 'IBM Plex Mono', monospace",
              fontWeight: 500,
              fontSize: iconSize * 0.175,
              letterSpacing: "0.18em",
              color: badgeText,
              border: `1px solid ${badgeBorder}`,
              padding: `${iconSize * 0.025}px ${iconSize * 0.065}px`,
              borderRadius: 3,
              lineHeight: 1,
              marginBottom: iconSize * 0.04,
            }}
          >
            AI
          </motion.span>
        </div>

        {/* Tagline */}
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 1.4 }}
          style={{
            fontFamily: "var(--font-ibm-plex-mono), 'IBM Plex Mono', monospace",
            fontWeight: 300,
            fontSize: iconSize * 0.115,
            letterSpacing: "0.22em",
            color: tagColor,
            textTransform: "uppercase",
          }}
        >
          Deterministic Enterprise Operations
        </motion.span>
      </div>
    </div>
  );
}

export default KernelSeal;
