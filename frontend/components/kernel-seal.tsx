import { cn } from "@/lib/utils";

interface KernelSealProps {
  size?: number;
  className?: string;
}

export function KernelSeal({ size = 32, className }: KernelSealProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("shrink-0", className)}
    >
      {/* Outer octagonal seal border */}
      <path
        d="M24 2L38.5 9.5L46 24L38.5 38.5L24 46L9.5 38.5L2 24L9.5 9.5L24 2Z"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="none"
        className="text-ink-primary"
      />
      {/* Inner kernel symbol - stylized K */}
      <path
        d="M18 14V34M18 24L30 14M18 24L30 34"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-gold"
      />
      {/* Central node */}
      <circle
        cx="24"
        cy="24"
        r="2"
        fill="currentColor"
        className="text-gold"
      />
    </svg>
  );
}
