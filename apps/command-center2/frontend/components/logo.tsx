import type { SVGProps } from "react";

/**
 * Unified Operious branding mark + wordmark.
 * Mirrors the marketing site logo so both surfaces share one identity.
 */
type LogoTone = "auto" | "dark" | "light";
type LogoVariant = "lockup" | "mark";

interface LogoProps
  extends Omit<SVGProps<SVGSVGElement>, "children" | "color" | "height" | "width"> {
  ariaLabel?: string;
  height?: number;
  width?: number;
  tone?: LogoTone;
  variant?: LogoVariant;
}

const accentColors = {
  gold: "#C9A84C",
  goldDeep: "#A8882C",
  blue: "#2A5CAA",
} as const;

function toneTextColor(tone: LogoTone): string {
  if (tone === "dark") return "#E8E2D2";
  if (tone === "light") return "#0A0F1C";
  return "currentColor";
}

function MarkArt({ size = 36 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <polygon
        points="16,2 28,9 28,23 16,30 4,23 4,9"
        stroke={accentColors.goldDeep}
        strokeWidth="1.5"
        fill="none"
      />
      <polygon
        points="16,8 22,11.5 22,18.5 16,22 10,18.5 10,11.5"
        stroke={accentColors.blue}
        strokeWidth="1"
        fill="none"
      />
      <line
        x1="16"
        y1="2"
        x2="16"
        y2="8"
        stroke={accentColors.goldDeep}
        strokeWidth="1.5"
      />
      <line
        x1="28"
        y1="23"
        x2="22"
        y2="18.5"
        stroke={accentColors.goldDeep}
        strokeWidth="1.5"
      />
      <line
        x1="4"
        y1="23"
        x2="10"
        y2="18.5"
        stroke={accentColors.goldDeep}
        strokeWidth="1.5"
      />
      <circle cx="16" cy="15" r="1.5" fill={accentColors.goldDeep} />
    </svg>
  );
}

export function Logo({
  ariaLabel = "Operious AI",
  className,
  height,
  width,
  tone = "auto",
  variant = "lockup",
}: LogoProps) {
  const markSize = height ?? (variant === "mark" ? 32 : 28);
  const textColor = toneTextColor(tone);

  if (variant === "mark") {
    return (
      <span
        role="img"
        aria-label={ariaLabel}
        className={className}
        style={{ display: "inline-flex", width: width ?? markSize, height: markSize }}
      >
        <MarkArt size={markSize} />
      </span>
    );
  }

  return (
    <span
      role="img"
      aria-label={ariaLabel}
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "10px",
        height: markSize + 4,
      }}
    >
      <MarkArt size={markSize} />
      <span
        style={{
          fontFamily:
            "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: "13px",
          fontWeight: 500,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: textColor,
          lineHeight: 1,
        }}
      >
        Operious
        <span style={{ marginLeft: 2, color: accentColors.gold }}>·</span>
      </span>
    </span>
  );
}
