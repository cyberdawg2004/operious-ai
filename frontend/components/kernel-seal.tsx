"use client";

// Official Operious AI KernelSeal - Brand Identity System v1.0
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
  textMid: "#7A90B4",
  textLo: "#3A4E6A",
};

function hexPts(cx: number, cy: number, r: number): [number, number][] {
  return Array.from({ length: 6 }, (_, i) => {
    const a = (60 * i * Math.PI) / 180;
    return [cx + r * Math.sin(a), cy - r * Math.cos(a)] as [number, number];
  });
}

function pStr(pts: [number, number][]): string {
  return pts.map((p) => p.join(",")).join(" ");
}

interface KernelSealProps {
  size?: number;
  phase?: 0 | 1 | 2 | 3;
  className?: string;
  showBackground?: boolean;
}

export function KernelSeal({
  size = 80,
  phase = 3,
  className,
  showBackground = true,
}: KernelSealProps) {
  const cx = size / 2;
  const cy = size / 2;
  const rO = size * 0.375;
  const rM = size * 0.265;
  const rI = size * 0.175;
  const sw = size * 0.026;

  const ptO = hexPts(cx, cy, rO);
  const ptM = hexPts(cx, cy, rM);
  const ptI = hexPts(cx, cy, rI);

  const bW = size * 0.13;
  const bH = size * 0.022;
  const gap = size * 0.042;

  const uid = `ks-${size}-${Math.random().toString(36).slice(2, 7)}`;
  const gradId = `${uid}-grad`;
  const glowId = `${uid}-glow`;
  const glowId2 = `${uid}-glow2`;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      className={className}
      aria-hidden="true"
      style={{
        flexShrink: 0,
        opacity: phase >= 1 ? 1 : 0,
        transition: "opacity 0.6s ease",
      }}
    >
      <defs>
        {/* Gold to Blue vertical gradient */}
        <linearGradient id={gradId} x1="50%" y1="0%" x2="50%" y2="100%">
          <stop offset="0%" stopColor={C.goldHi} />
          <stop offset="55%" stopColor={C.goldMid} />
          <stop offset="100%" stopColor={C.blueHi} />
        </linearGradient>

        {/* Glow filter for vertices and top bar */}
        <filter id={glowId} x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation={size * 0.045} result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        {/* Ambient glow filter */}
        <filter id={glowId2} x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation={size * 0.1} result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Background plate */}
      {showBackground && (
        <rect
          x={0}
          y={0}
          width={size}
          height={size}
          rx={size * 0.18}
          fill={C.surface}
        />
      )}

      {/* Ambient inner glow */}
      <circle
        cx={cx}
        cy={cy}
        r={rO * 0.9}
        fill={C.blueLo}
        opacity={0.35}
        filter={`url(#${glowId2})`}
      />

      {/* Outer hex */}
      <polygon
        points={pStr(ptO)}
        stroke={`url(#${gradId})`}
        strokeWidth={sw * 1.4}
        fill="none"
        style={{
          opacity: phase >= 1 ? 1 : 0,
          transition: "opacity 0.5s ease 0.1s",
        }}
      />

      {/* Mid hex */}
      <polygon
        points={pStr(ptM)}
        stroke={`url(#${gradId})`}
        strokeWidth={sw * 0.85}
        fill="none"
        style={{
          opacity: phase >= 2 ? 0.55 : 0,
          transition: "opacity 0.5s ease 0.35s",
        }}
      />

      {/* Inner hex */}
      <polygon
        points={pStr(ptI)}
        stroke={`url(#${gradId})`}
        strokeWidth={sw * 0.5}
        fill="none"
        style={{
          opacity: phase >= 2 ? 0.3 : 0,
          transition: "opacity 0.5s ease 0.55s",
        }}
      />

      {/* Six vertex dots on outer hex */}
      {ptO.map(([x, y], i) => (
        <circle
          key={i}
          cx={x}
          cy={y}
          r={sw * 0.8}
          fill={i === 0 ? C.goldHi : C.blueHi}
          filter={`url(#${glowId})`}
          style={{
            opacity: phase >= 2 ? (i === 0 ? 1 : 0.6) : 0,
            transition: `opacity 0.3s ease ${0.5 + i * 0.06}s`,
          }}
        />
      ))}

      {/* Center kernel bars (governance stack) */}
      {[0, 1, 2].map((j) => {
        const w = bW * (1 - j * 0.22);
        const y = cy - gap + j * gap - bH / 2;
        return (
          <rect
            key={j}
            x={cx - w / 2}
            y={y}
            width={w}
            height={bH}
            rx={bH * 0.4}
            fill={`url(#${gradId})`}
            filter={j === 0 ? `url(#${glowId})` : undefined}
            style={{
              opacity: phase >= 3 ? 1 - j * 0.25 : 0,
              transition: `opacity 0.4s ease ${0.9 + j * 0.1}s`,
            }}
          />
        );
      })}
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
  showBackground = true,
}: LockupProps) {
  const isDark = theme === "dark";
  const nameColor = isDark ? C.textHi : "#0B1526";
  const tagColor = isDark ? C.textLo : "#7A90B4";
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
          <span
            style={{
              fontFamily: "var(--font-cormorant-sc), 'Cormorant SC', serif",
              fontWeight: 700,
              fontSize: iconSize * 0.52,
              letterSpacing: "0.04em",
              color: nameColor,
              lineHeight: 1,
              opacity: phase >= 2 ? 1 : 0,
              transform: phase >= 2 ? "translateX(0)" : "translateX(-8px)",
              transition: "opacity 0.6s ease 0.6s, transform 0.6s ease 0.6s",
            }}
          >
            Operious
          </span>

          {/* AI badge */}
          <span
            style={{
              fontFamily:
                "var(--font-ibm-plex-mono), 'IBM Plex Mono', monospace",
              fontWeight: 500,
              fontSize: iconSize * 0.175,
              letterSpacing: "0.18em",
              color: badgeText,
              border: `1px solid ${badgeBorder}`,
              padding: `${iconSize * 0.025}px ${iconSize * 0.065}px`,
              borderRadius: 3,
              lineHeight: 1,
              marginBottom: iconSize * 0.04,
              opacity: phase >= 3 ? 1 : 0,
              transition: "opacity 0.5s ease 1.1s",
            }}
          >
            AI
          </span>
        </div>

        {/* Tagline */}
        <span
          style={{
            fontFamily: "var(--font-ibm-plex-mono), 'IBM Plex Mono', monospace",
            fontWeight: 300,
            fontSize: iconSize * 0.115,
            letterSpacing: "0.22em",
            color: tagColor,
            textTransform: "uppercase",
            opacity: phase >= 3 ? 1 : 0,
            transition: "opacity 0.5s ease 1.3s",
          }}
        >
          Deterministic Enterprise Operations
        </span>
      </div>
    </div>
  );
}

export default KernelSeal;
