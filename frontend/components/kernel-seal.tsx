"use client";

/* ─── palette ─────────────────────────────────────────── */
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

/* ─── hex geometry ─────────────────────────────────────── */
function hexPts(cx: number, cy: number, r: number): [number, number][] {
  return Array.from({ length: 6 }, (_, i) => {
    const a = (60 * i * Math.PI) / 180; // pointy-top: offset 0
    return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  });
}

function pStr(pts: [number, number][]): string {
  return pts.map((p) => p.join(",")).join(" ");
}

/* ─── Icon Mark ────────────────────────────────────────── */
interface KernelSealProps {
  size?: number;
  phase?: number;
  className?: string;
}

export function KernelSeal({ size = 80, phase = 3, className }: KernelSealProps) {
  const cx = size / 2,
    cy = size / 2;
  const rO = size * 0.375; // outer hex
  const rM = size * 0.265; // mid hex
  const rI = size * 0.175; // inner hex
  const sw = size * 0.026; // stroke base

  const ptO = hexPts(cx, cy, rO);
  const ptM = hexPts(cx, cy, rM);
  const ptI = hexPts(cx, cy, rI);

  // Center chevron/kernel mark — three stacked horizontal bars shrinking
  const bW = size * 0.13;
  const bH = size * 0.022;
  const gap = size * 0.042;

  const gradId = `kg-${size}`;
  const glowId = `gg-${size}`;
  const glowId2 = `gg2-${size}`;
  const maskId = `km-${size}`;
  const noiseId = `kn-${size}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      className={className}
      style={{
        flexShrink: 0,
        opacity: phase >= 1 ? 1 : 0,
        transition: "opacity 0.6s ease",
      }}
    >
      <defs>
        <linearGradient id={gradId} x1="50%" y1="0%" x2="50%" y2="100%">
          <stop offset="0%" stopColor={C.goldHi} />
          <stop offset="55%" stopColor={C.goldMid} />
          <stop offset="100%" stopColor={C.goldLo} />
        </linearGradient>

        <radialGradient id={glowId} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={C.goldHi} stopOpacity={0.35} />
          <stop offset="100%" stopColor={C.goldHi} stopOpacity={0} />
        </radialGradient>

        <radialGradient id={glowId2} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={C.blueHi} stopOpacity={0.2} />
          <stop offset="100%" stopColor={C.blueHi} stopOpacity={0} />
        </radialGradient>

        <filter id={noiseId} x="0%" y="0%" width="100%" height="100%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.8"
            numOctaves="4"
            result="noise"
          />
          <feComposite in="SourceGraphic" in2="noise" operator="in" />
        </filter>

        <mask id={maskId}>
          <rect x="0" y="0" width={size} height={size} fill="white" />
          <polygon points={pStr(ptI)} fill="black" />
        </mask>
      </defs>

      {/* subtle blue glow at back */}
      <circle cx={cx} cy={cy} r={rO * 1.1} fill={`url(#${glowId2})`} opacity={0.5} />

      {/* outer hex – faint blue stroke */}
      <polygon
        points={pStr(ptO)}
        fill="none"
        stroke={C.blueLo}
        strokeWidth={sw}
        style={{
          opacity: phase >= 1 ? 1 : 0,
          transition: "opacity 0.4s ease",
        }}
      />

      {/* mid hex – gold gradient stroke */}
      <polygon
        points={pStr(ptM)}
        fill="none"
        stroke={`url(#${gradId})`}
        strokeWidth={sw * 1.5}
        style={{
          opacity: phase >= 2 ? 1 : 0,
          transition: "opacity 0.4s ease 0.1s",
        }}
      />

      {/* inner hex – thin gold */}
      <polygon
        points={pStr(ptI)}
        fill="none"
        stroke={C.goldMid}
        strokeWidth={sw * 0.75}
        style={{
          opacity: phase >= 2 ? 1 : 0,
          transition: "opacity 0.4s ease 0.2s",
        }}
      />

      {/* center kernel glyph – three bars */}
      <g
        style={{
          opacity: phase >= 3 ? 1 : 0,
          transition: "opacity 0.4s ease 0.3s",
        }}
      >
        {[-1, 0, 1].map((idx) => {
          const yOff = cy + idx * gap;
          const w = bW * (1 - Math.abs(idx) * 0.2);
          return (
            <rect
              key={idx}
              x={cx - w / 2}
              y={yOff - bH / 2}
              width={w}
              height={bH}
              fill={`url(#${gradId})`}
              rx={bH / 2}
            />
          );
        })}
      </g>

      {/* gold glow in center */}
      <circle
        cx={cx}
        cy={cy}
        r={rI * 0.6}
        fill={`url(#${glowId})`}
        style={{
          opacity: phase >= 3 ? 1 : 0,
          transition: "opacity 0.4s ease 0.35s",
        }}
      />

      {/* radial gold accents on hex vertices – outer ring only */}
      {phase >= 3 &&
        ptO.map(([px, py], i) => (
          <circle key={i} cx={px} cy={py} r={sw * 0.8} fill={C.goldHi} opacity={0.7} />
        ))}
    </svg>
  );
}

/* ─── Full Lockup with wordmark ────────────────────────── */
interface KernelLockupProps {
  size?: number;
  phase?: number;
  className?: string;
}

export function KernelLockup({ size = 200, phase = 3, className }: KernelLockupProps) {
  const markSize = size * 0.42;
  const fontSize = size * 0.145;

  return (
    <div
      className={className}
      style={{
        display: "inline-flex",
        flexDirection: "column",
        alignItems: "center",
        gap: size * 0.05,
        opacity: phase >= 1 ? 1 : 0,
        transition: "opacity 0.6s ease",
      }}
    >
      <KernelSeal size={markSize} phase={phase} />
      <span
        style={{
          fontFamily: "'Cormorant SC', Georgia, serif",
          fontSize: fontSize,
          fontWeight: 600,
          color: C.textHi,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          opacity: phase >= 2 ? 1 : 0,
          transition: "opacity 0.4s ease 0.2s",
        }}
      >
        Operious
      </span>
      <span
        style={{
          fontFamily: "'IBM Plex Mono', monospace",
          fontSize: fontSize * 0.35,
          fontWeight: 400,
          color: C.goldMid,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          opacity: phase >= 3 ? 1 : 0,
          transition: "opacity 0.4s ease 0.35s",
        }}
      >
        Operational Infrastructure
      </span>
    </div>
  );
}

export default KernelSeal;
