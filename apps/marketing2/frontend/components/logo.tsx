export function OperioussLogo({
  size = 32,
  showWordmark = true,
}: {
  size?: number;
  showWordmark?: boolean;
}) {
  return (
    <div className="flex items-center gap-3">
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

      {showWordmark && (
        <span className="font-mono text-sm font-medium tracking-[0.15em] uppercase text-[#D8E4F4]">
          Operious
          <span className="ml-0.5 text-[#A8882C]">·</span>
        </span>
      )}
    </div>
  );
}
