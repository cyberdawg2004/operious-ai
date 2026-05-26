import type { CSSProperties, SVGProps } from "react";

type LogoTone = "auto" | "light" | "dark";
type LogoVariant = "lockup" | "mark";

interface LogoProps
  extends Omit<SVGProps<SVGSVGElement>, "children" | "color" | "height" | "width"> {
  ariaLabel?: string;
  height?: number | string;
  showBadge?: boolean;
  showPlate?: boolean;
  showTagline?: boolean;
  tone?: LogoTone;
  variant?: LogoVariant;
  width?: number | string;
}

const palette = {
  goldHi: "#C9A84C",
  goldMid: "#A8882C",
  blueHi: "#2A6BCC",
  blueLo: "#0D2860",
  border: "#1A2744",
  surface: "#0B1120",
};

function hexPoints(cx: number, cy: number, r: number): string {
  return Array.from({ length: 6 }, (_, index) => {
    const angle = (60 * index * Math.PI) / 180;
    return `${cx + r * Math.sin(angle)},${cy - r * Math.cos(angle)}`;
  }).join(" ");
}

function toneVariables(tone: LogoTone): Record<string, string> {
  if (tone === "dark") {
    return {
      "--logo-word": "#D8E4F4",
      "--logo-muted": "#7A90B4",
      "--logo-stroke": "#35527F",
      "--logo-badge": palette.blueHi,
      "--logo-badge-border": palette.border,
      "--logo-plate": palette.surface,
    };
  }

  if (tone === "light") {
    return {
      "--logo-word": "#0A0F1C",
      "--logo-muted": "#4A5468",
      "--logo-stroke": "#2A3A5A",
      "--logo-badge": "#1A4A9A",
      "--logo-badge-border": "#B8CAE4",
      "--logo-plate": "#F8F5EE",
    };
  }

  return {
    "--logo-word": "currentColor",
    "--logo-muted": "color-mix(in oklab, currentColor 58%, transparent)",
    "--logo-stroke": "color-mix(in oklab, currentColor 44%, #2A6BCC)",
    "--logo-badge": palette.blueHi,
    "--logo-badge-border": "color-mix(in oklab, currentColor 24%, transparent)",
    "--logo-plate": "transparent",
  };
}

function KernelMark({ showPlate = false }: { showPlate?: boolean }) {
  const outer = hexPoints(32, 32, 24);
  const middle = hexPoints(32, 32, 17);
  const inner = hexPoints(32, 32, 11);

  return (
    <g>
      {showPlate && <rect x="3" y="3" width="58" height="58" rx="5" fill="var(--logo-plate)" />}
      <circle cx="32" cy="32" r="23" fill={palette.blueLo} opacity="0.12" />
      <polygon points={outer} fill="none" stroke="var(--logo-stroke)" strokeWidth="2.4" />
      <polygon points={middle} fill="none" stroke="var(--logo-stroke)" strokeWidth="1.5" opacity="0.76" />
      <polygon points={inner} fill="none" stroke="var(--logo-stroke)" strokeWidth="1" opacity="0.6" />
      <path d="M32 8 V18" stroke="url(#operious-logo-governance)" strokeLinecap="square" strokeWidth="1.4" opacity="0.8" />
      <path d="M32 46 V56" stroke="url(#operious-logo-governance)" strokeLinecap="square" strokeWidth="1.4" opacity="0.6" />
      <path
        d="M13 18 L20 14 L27 18"
        fill="none"
        stroke="url(#operious-logo-governance)"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="4"
      />
      <path
        d="M37 18 L44 14 L51 18"
        fill="none"
        stroke="url(#operious-logo-governance)"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="4"
      />
      <path
        d="M39 47 L46 51 L53 47"
        fill="none"
        stroke="url(#operious-logo-governance)"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="4"
      />
      <rect x="27.5" y="26" width="9" height="1.8" rx="0.8" fill="url(#operious-logo-governance)" />
      <rect x="28.6" y="31.2" width="6.8" height="1.8" rx="0.8" fill="url(#operious-logo-governance)" opacity="0.82" />
      <rect x="29.7" y="36.4" width="4.6" height="1.8" rx="0.8" fill="url(#operious-logo-governance)" opacity="0.64" />
      <circle cx="32" cy="32" r="2.2" fill="var(--logo-word)" opacity="0.9" />
    </g>
  );
}

export function Logo({
  ariaLabel = "Operious AI",
  className,
  height,
  showBadge = true,
  showPlate = false,
  showTagline = false,
  style,
  tone = "auto",
  variant = "lockup",
  width,
  ...props
}: LogoProps) {
  const isMark = variant === "mark";
  const resolvedWidth = width ?? (isMark ? 40 : showTagline ? 236 : 172);
  const resolvedHeight = height ?? (isMark ? 40 : showTagline ? 56 : 40);
  const viewBox = isMark ? "0 0 64 64" : "0 0 252 64";
  const yWord = showTagline ? 30 : 40;
  const cssVars = {
    ...toneVariables(tone),
    ...style,
  } as CSSProperties & Record<string, string>;

  return (
    <svg
      aria-label={ariaLabel}
      className={className}
      fill="none"
      focusable="false"
      height={resolvedHeight}
      role="img"
      style={cssVars}
      viewBox={viewBox}
      width={resolvedWidth}
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <defs>
        <linearGradient id="operious-logo-governance" x1="32" x2="32" y1="8" y2="56" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor={palette.goldHi} />
          <stop offset="0.52" stopColor={palette.goldMid} />
          <stop offset="1" stopColor={palette.blueHi} />
        </linearGradient>
      </defs>
      <KernelMark showPlate={showPlate} />
      {!isMark && (
        <g>
          <text
            dominantBaseline="middle"
            fill="var(--logo-word)"
            fontFamily="var(--font-geist-sans), Geist, Inter, system-ui, sans-serif"
            fontSize="21.5"
            fontWeight="760"
            letterSpacing="2.8"
            x="78"
            y={yWord}
          >
            OPERIOUS
          </text>
          {!showTagline && (
            <path d="M79 48.5 H184" stroke="var(--logo-stroke)" strokeWidth="1" opacity="0.42" />
          )}
          {showBadge && (
            <g transform={`translate(198 ${showTagline ? 18 : 28})`}>
              <rect width="32" height="18" rx="1.5" fill="transparent" stroke="var(--logo-badge-border)" />
              <path d="M0 0 H32" stroke="url(#operious-logo-governance)" strokeWidth="1" />
              <text
                dominantBaseline="middle"
                fill="var(--logo-badge)"
                fontFamily="var(--font-ibm-plex-mono), var(--font-geist-mono), monospace"
                fontSize="9"
                fontWeight="700"
                letterSpacing="1.5"
                textAnchor="middle"
                x="16"
                y="9.5"
              >
                AI
              </text>
            </g>
          )}
          {showTagline && (
            <text
              fill="var(--logo-muted)"
              fontFamily="var(--font-ibm-plex-mono), var(--font-geist-mono), monospace"
              fontSize="7.5"
              fontWeight="500"
              letterSpacing="2.2"
              x="79"
              y="50"
            >
              DETERMINISTIC ENTERPRISE OPERATIONS
            </text>
          )}
        </g>
      )}
    </svg>
  );
}
