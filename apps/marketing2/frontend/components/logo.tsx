/**
 * Unified Operious wordmark + geometric hexagon mark.
 * Single source of truth for branding across marketing and command center.
 */
type LogoTone = "auto" | "dark" | "light";

interface LogoProps {
  size?: number;
  showWordmark?: boolean;
  tone?: LogoTone;
  className?: string;
}

const wordmarkToneClass: Record<LogoTone, string> = {
  auto: "text-current",
  dark: "text-[#E8E2D2]",
  light: "text-[#0A0F1C]",
};

const accentToneClass: Record<LogoTone, string> = {
  auto: "text-[#C9A84C]",
  dark: "text-[#C9A84C]",
  light: "text-[#A8882C]",
};

export function OperiousMark({
  size = 32,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      className={className}
    >
      <polygon
        points="16,2 28,9 28,23 16,30 4,23 4,9"
        stroke="#A8882C"
        strokeWidth="1.5"
        fill="none"
      />
      <polygon
        points="16,8 22,11.5 22,18.5 16,22 10,18.5 10,11.5"
        stroke="#2A5CAA"
        strokeWidth="1"
        fill="none"
      />
      <line x1="16" y1="2" x2="16" y2="8" stroke="#A8882C" strokeWidth="1.5" />
      <line x1="28" y1="23" x2="22" y2="18.5" stroke="#A8882C" strokeWidth="1.5" />
      <line x1="4" y1="23" x2="10" y2="18.5" stroke="#A8882C" strokeWidth="1.5" />
      <circle cx="16" cy="15" r="1.5" fill="#A8882C" />
    </svg>
  );
}

export function OperioussLogo({
  size = 32,
  showWordmark = true,
  tone = "auto",
  className,
}: LogoProps) {
  return (
    <div className={`flex items-center gap-3 ${className ?? ""}`}>
      <OperiousMark size={size} />
      {showWordmark && (
        <span
          className={`font-mono text-sm font-medium uppercase tracking-[0.18em] ${wordmarkToneClass[tone]}`}
        >
          Operious
          <span className={`ml-0.5 ${accentToneClass[tone]}`}>·</span>
        </span>
      )}
    </div>
  );
}
