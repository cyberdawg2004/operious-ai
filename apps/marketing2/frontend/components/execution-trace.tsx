const traceSteps = [
  {
    step: "01",
    label: "Inbound contact received",
    detail: "WhatsApp · Arabic language detected (0.97)",
    status: "complete",
    ms: "12ms",
  },
  {
    step: "02",
    label: "Policy admission evaluated",
    detail: "anker_confidence_thresholds v1 · 3 policies",
    status: "complete",
    ms: "8ms",
  },
  {
    step: "03",
    label: "AI classification",
    detail: "warranty_claim · 0.93 confidence",
    status: "complete",
    ms: "1,240ms",
  },
  {
    step: "04",
    label: "Governance decision",
    detail: "ALLOW · policy satisfied · decision persisted",
    status: "allow",
    ms: "6ms",
  },
  {
    step: "05",
    label: "Audit record sealed",
    detail: "HMAC-SHA256 · UUID5 · append-only · permanent",
    status: "complete",
    ms: "4ms",
  },
] as const;

type TraceStatus = (typeof traceSteps)[number]["status"] | "deny" | "escalate";

const statusStyles: Record<
  TraceStatus,
  { dot: string; badge?: string; label?: string }
> = {
  complete: {
    dot: "bg-status-success/75",
  },
  allow: {
    dot: "bg-[#34D17A] shadow-[0_0_14px_rgba(52,209,122,0.6)]",
    badge: "border-[#34D17A]/35 bg-[#34D17A]/10 text-[#77E3A8]",
    label: "ALLOW",
  },
  deny: {
    dot: "bg-status-error",
    badge: "border-status-error/35 bg-status-error/10 text-[#F6A1A1]",
    label: "DENY",
  },
  escalate: {
    dot: "bg-status-warning",
    badge: "border-status-warning/35 bg-status-warning/10 text-[#F4C66B]",
    label: "ESCALATE",
  },
};

function StatusIndicator({ status }: { status: TraceStatus }) {
  const style = statusStyles[status];

  return (
    <span className="flex items-center gap-2">
      <span className={`h-2.5 w-2.5 rounded-full ${style.dot}`} />
      {style.badge && style.label && (
        <span
          className={`rounded border px-2 py-0.5 font-mono text-[10px] font-semibold tracking-[0.14em] ${style.badge}`}
        >
          {style.label}
        </span>
      )}
    </span>
  );
}

export function ExecutionTrace() {
  return (
    <div className="relative z-10 mt-10 max-w-[920px] rounded-md border border-[#1A2744] bg-[#05080F]/92 p-4 shadow-[0_28px_80px_rgba(0,0,0,0.28)] sm:p-5">
      <p
        className="text-[10px] uppercase tracking-[0.18em] text-[#C9A84C]"
        style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
      >
        LIVE GOVERNANCE TRACE — Consumer Electronics Pilot
      </p>

      <div className="mt-4 overflow-hidden rounded-md border border-[#1A2744] bg-[#0B1120]">
        {traceSteps.map((item) => (
          <div
            key={item.step}
            className="grid gap-3 border-b border-[#1A2744] px-4 py-4 last:border-b-0 sm:grid-cols-[44px_1fr_auto_auto] sm:items-center"
          >
            <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[#7A90B4]">
              {item.step}
            </span>
            <span className="grid gap-1">
              <span className="text-[15px] font-semibold text-[#D8E4F4]">
                {item.label}
              </span>
              <span className="font-mono text-[11px] leading-relaxed text-[#7A90B4]">
                {item.detail}
              </span>
            </span>
            <StatusIndicator status={item.status} />
            <span className="font-mono text-[11px] tabular-nums text-[#C9A84C]">
              {item.ms}
            </span>
          </div>
        ))}
      </div>

      <p className="mt-4 max-w-[760px] text-[13px] leading-relaxed text-[#A9B8CE]">
        Every contact processed by Operious produces a trace identical to this.
        Permanent. Cryptographically signed. Forensically reconstructible.
      </p>
    </div>
  );
}
