"use client";

import { motion, useReducedMotion } from "framer-motion";

export function GovernanceTraceConsole({ className = "" }: { className?: string }) {
  const shouldReduceMotion = useReducedMotion();

  const steps = [
    { label: "Tenant Verified", state: "pass" },
    { label: "Policy Matched", state: "pass" },
    { label: "Authority Checked", state: "pass" },
    { label: "Approved", state: "pass" },
    { label: "Audit Sealed", state: "pass" },
    { label: "Replay Available", state: "pass" },
  ];

  return (
    <div className={`rounded-[24px] border border-[#24324a] bg-[rgba(4,8,16,0.88)] p-4 sm:p-6 shadow-[0_20px_80px_rgba(0,0,0,0.35)] backdrop-blur ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#24324a] pb-4">
        <div>
          <p className="text-[10px] uppercase tracking-[0.24em] text-[#C9A84C]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>
            GOVERNANCE TRACE
          </p>
          <p className="mt-2 text-[15px] text-[#D8E4F4]">Deterministic execution lineage</p>
        </div>
        <div className="rounded-full border border-[#2f4b76] bg-[#08111d] px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-[#7A90B4]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>
          live evidence
        </div>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-[18px] border border-[#24324a] bg-[#08111d] p-4">
          <div className="mb-4 flex items-center justify-between text-[12px] text-[#7A90B4]">
            <span>Session 014 · RMA / Refund</span>
            <span className="rounded-full border border-[#2f4b76] px-2 py-1 text-[10px] uppercase tracking-[0.24em] text-[#C9A84C]">fail-closed</span>
          </div>
          <div className="relative h-[180px] overflow-hidden rounded-[14px] border border-[#1b2b43] bg-[radial-gradient(circle_at_top_left,rgba(201,168,76,0.16),transparent_45%),linear-gradient(135deg,rgba(12,20,34,1),rgba(5,8,15,1))]">
            <div className="absolute inset-0 opacity-[0.18]" style={{ backgroundImage: "linear-gradient(rgba(255,255,255,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px)", backgroundSize: "24px 24px" }} />
            <svg viewBox="0 0 320 180" className="absolute inset-0 h-full w-full">
              <motion.path
                d="M20 90 C70 40, 110 30, 150 60 S240 120, 280 90"
                stroke="#2A5CAA"
                strokeWidth="2"
                fill="none"
                initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 1.2, delay: 0.2, ease: "easeOut" }}
              />
              <motion.path
                d="M20 90 C60 120, 110 140, 160 115 S240 70, 280 90"
                stroke="#A8882C"
                strokeWidth="2"
                fill="none"
                initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 1.1, delay: 0.4, ease: "easeOut" }}
              />
              {[
                { x: 45, y: 88 },
                { x: 110, y: 58 },
                { x: 170, y: 112 },
                { x: 235, y: 84 },
                { x: 290, y: 92 },
              ].map((point, index) => (
                <motion.circle
                  key={`${point.x}-${point.y}`}
                  cx={point.x}
                  cy={point.y}
                  r="5"
                  fill="#C9A84C"
                  initial={shouldReduceMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.6 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.4, delay: 0.2 + index * 0.1 }}
                />
              ))}
            </svg>
          </div>
        </div>

        <div className="space-y-3">
          {steps.map((step, index) => (
            <motion.div
              key={step.label}
              initial={shouldReduceMotion ? { opacity: 1, x: 0 } : { opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.35, delay: 0.15 + index * 0.08 }}
              className="flex items-center justify-between rounded-[14px] border border-[#24324a] bg-[#0b1321] px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <span className="h-2.5 w-2.5 rounded-full bg-[#C9A84C]" />
                <span className="text-[14px] text-[#D8E4F4]">{step.label}</span>
              </div>
              <span className="text-[12px] uppercase tracking-[0.24em] text-[#7A90B4]">ok</span>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function CommandCenterPreview({ className = "" }: { className?: string }) {
  const shouldReduceMotion = useReducedMotion();

  return (
    <div className={`rounded-[28px] border border-[#24324a] bg-[rgba(7,11,20,0.92)] p-3 shadow-[0_24px_100px_rgba(0,0,0,0.4)] backdrop-blur ${className}`}>
      <div className="rounded-[20px] border border-[#24324a] bg-[#05080F] p-3">
        <div className="mb-3 flex items-center justify-between rounded-[14px] border border-[#24324a] bg-[#08111d] px-3 py-2 text-[11px] uppercase tracking-[0.24em] text-[#7A90B4]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>
          <span>tenant · acme</span>
          <span>environment · production</span>
          <span>authority · fail-closed</span>
        </div>

        <div className="grid gap-3 lg:grid-cols-[0.8fr_1.2fr_0.8fr]">
          <div className="rounded-[14px] border border-[#24324a] bg-[#0b1321] p-3">
            <p className="text-[10px] uppercase tracking-[0.24em] text-[#C9A84C]">navigation</p>
            <div className="mt-3 space-y-2 text-[13px] text-[#7A90B4]">
              {['Sessions', 'Governance', 'Coordination', 'Boundary', 'Supervisor', 'Arbitration', 'Audit'].map((item, index) => (
                <div key={item} className={`rounded-full px-3 py-2 ${index === 0 ? 'bg-[#11213d] text-[#D8E4F4]' : 'bg-transparent'}`}>
                  {item}
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[14px] border border-[#24324a] bg-[#0b1321] p-3">
            <div className="mb-3 flex items-center justify-between text-[12px] text-[#7A90B4]">
              <span>Workflow canvas</span>
              <span className="rounded-full border border-[#2f4b76] px-2 py-1 text-[10px] uppercase tracking-[0.24em] text-[#C9A84C]">replay ready</span>
            </div>
            <div className="relative h-[220px] overflow-hidden rounded-[14px] border border-[#24324a] bg-[radial-gradient(circle_at_top_left,rgba(42,92,170,0.18),transparent_45%),linear-gradient(135deg,rgba(10,16,29,1),rgba(4,7,15,1))]">
              <div className="absolute inset-0 opacity-[0.2]" style={{ backgroundImage: "linear-gradient(rgba(255,255,255,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px)", backgroundSize: "18px 18px" }} />
              <svg viewBox="0 0 260 220" className="absolute inset-0 h-full w-full">
                <motion.path d="M40 170 C85 120, 105 100, 140 105 S210 125, 220 70" stroke="#3768b7" strokeWidth="2" fill="none" initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, delay: 0.1 }} />
                <motion.circle cx="40" cy="170" r="5" fill="#C9A84C" initial={shouldReduceMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, delay: 0.2 }} />
                <motion.circle cx="140" cy="105" r="6" fill="#3D7DD4" initial={shouldReduceMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, delay: 0.3 }} />
                <motion.circle cx="220" cy="70" r="5" fill="#C9A84C" initial={shouldReduceMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, delay: 0.4 }} />
              </svg>
              <div className="absolute left-4 top-4 rounded-full border border-[#2f4b76] bg-[#08111d] px-3 py-1 text-[10px] uppercase tracking-[0.24em] text-[#D8E4F4]">coordination</div>
            </div>
          </div>

          <div className="rounded-[14px] border border-[#24324a] bg-[#0b1321] p-3">
            <p className="text-[10px] uppercase tracking-[0.24em] text-[#C9A84C]">evidence</p>
            <div className="mt-3 space-y-2 text-[12px] text-[#7A90B4]">
              <div className="rounded-[10px] border border-[#24324a] bg-[#08111d] p-2">
                <div className="text-[10px] uppercase tracking-[0.24em] text-[#C9A84C]">tenant</div>
                <div className="mt-1 text-[13px] text-[#D8E4F4]">Verified</div>
              </div>
              <div className="rounded-[10px] border border-[#24324a] bg-[#08111d] p-2">
                <div className="text-[10px] uppercase tracking-[0.24em] text-[#C9A84C]">policy</div>
                <div className="mt-1 text-[13px] text-[#D8E4F4]">Matched</div>
              </div>
              <div className="rounded-[10px] border border-[#24324a] bg-[#08111d] p-2">
                <div className="text-[10px] uppercase tracking-[0.24em] text-[#C9A84C]">timeline</div>
                <div className="mt-1 text-[13px] text-[#D8E4F4]">Replay 1.2s</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ArchitectureDiagram({ className = "" }: { className?: string }) {
  const shouldReduceMotion = useReducedMotion();

  const nodes = [
    { label: "Boundary", x: 20, y: 70 },
    { label: "Coordination", x: 120, y: 35 },
    { label: "Governance", x: 220, y: 70 },
    { label: "Session", x: 120, y: 115 },
    { label: "Execution", x: 220, y: 145 },
    { label: "Supervisor", x: 320, y: 115 },
    { label: "Arbitration", x: 410, y: 70 },
    { label: "Audit", x: 500, y: 115 },
  ];

  return (
    <div className={`rounded-[24px] border border-[#24324a] bg-[rgba(6,10,18,0.94)] p-4 shadow-[0_20px_80px_rgba(0,0,0,0.35)] ${className}`}>
      <div className="rounded-[18px] border border-[#24324a] bg-[#08111d] p-4">
        <svg viewBox="0 0 560 220" className="h-full w-full">
          <rect x="0" y="0" width="560" height="220" rx="20" fill="transparent" />
          <motion.path d="M60 70 H120" stroke="#2A5CAA" strokeWidth="2" initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, delay: 0.1 }} />
          <motion.path d="M160 35 H220" stroke="#2A5CAA" strokeWidth="2" initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, delay: 0.2 }} />
          <motion.path d="M260 70 H320" stroke="#2A5CAA" strokeWidth="2" initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, delay: 0.3 }} />
          <motion.path d="M360 115 H420" stroke="#2A5CAA" strokeWidth="2" initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, delay: 0.4 }} />
          <motion.path d="M460 70 H500" stroke="#2A5CAA" strokeWidth="2" initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, delay: 0.5 }} />
          <motion.path d="M140 115 L140 85" stroke="#A8882C" strokeWidth="2" initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, delay: 0.6 }} />
          <motion.path d="M220 145 L220 90" stroke="#A8882C" strokeWidth="2" initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, delay: 0.7 }} />
          {nodes.map((node, index) => (
            <motion.g key={node.label} initial={shouldReduceMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, delay: 0.15 + index * 0.07 }}>
              <rect x={node.x - 28} y={node.y - 18} width="56" height="36" rx="10" fill="#0e1727" stroke="#2f4b76" />
              <circle cx={node.x} cy={node.y} r="4" fill="#C9A84C" />
              <text x={node.x} y={node.y + 24} textAnchor="middle" fill="#7A90B4" fontSize="10" fontFamily="var(--font-ibm-plex-mono)">{node.label}</text>
            </motion.g>
          ))}
        </svg>
      </div>
    </div>
  );
}

export function IntegrationMap({ className = "" }: { className?: string }) {
  const shouldReduceMotion = useReducedMotion();
  const channels = ["Email", "WhatsApp", "Voice", "Web Chat", "Helpdesk"];
  const systems = ["CRM", "Ticketing", "Warehouse", "Compliance Export", "Audit Record", "Approval Systems"];

  return (
    <div className={`rounded-[24px] border border-[#24324a] bg-[rgba(6,10,18,0.94)] p-4 shadow-[0_20px_80px_rgba(0,0,0,0.35)] ${className}`}>
      <div className="rounded-[18px] border border-[#24324a] bg-[#08111d] p-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-[0.24em] text-[#C9A84C]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>INTEGRATION MAP</p>
            <p className="mt-2 text-[15px] text-[#D8E4F4]">Operious sits between human channels and enterprise systems</p>
          </div>
          <div className="rounded-full border border-[#2f4b76] bg-[#0b1321] px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-[#7A90B4]">connected</div>
        </div>
        <div className="relative overflow-hidden rounded-[16px] border border-[#24324a] bg-[radial-gradient(circle_at_top_left,rgba(42,92,170,0.12),transparent_45%),linear-gradient(135deg,rgba(8,14,24,1),rgba(5,8,15,1))] p-4">
          <svg viewBox="0 0 420 220" className="absolute inset-0 h-full w-full">
            <motion.path d="M100 60 C155 60, 165 100, 220 110" stroke="#2A5CAA" strokeWidth="2" fill="none" initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, delay: 0.1 }} />
            <motion.path d="M220 110 C270 110, 290 96, 330 80" stroke="#A8882C" strokeWidth="2" fill="none" initial={shouldReduceMotion ? { pathLength: 1 } : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, delay: 0.3 }} />
            <motion.circle cx="100" cy="60" r="4" fill="#C9A84C" initial={shouldReduceMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.7 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, delay: 0.2 }} />
            <motion.circle cx="220" cy="110" r="4" fill="#3D7DD4" initial={shouldReduceMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.7 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, delay: 0.4 }} />
            <motion.circle cx="330" cy="80" r="4" fill="#C9A84C" initial={shouldReduceMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.7 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, delay: 0.5 }} />
          </svg>
          <div className="relative grid h-full gap-4 md:grid-cols-[0.85fr_1fr_0.85fr]">
            <div className="space-y-2">
              {channels.map((channel) => (
                <div key={channel} className="rounded-full border border-[#24324a] bg-[#09111c] px-3 py-2 text-[12px] text-[#D8E4F4]">
                  {channel}
                </div>
              ))}
            </div>
            <div className="flex items-center justify-center">
              <div className="rounded-full border border-[#3d7dd4] bg-[#0c1730] px-6 py-4 text-center text-[14px] font-medium uppercase tracking-[0.24em] text-[#D8E4F4]" style={{ fontFamily: "var(--font-ibm-plex-mono)" }}>
                Operious
              </div>
            </div>
            <div className="space-y-2">
              {systems.map((system) => (
                <div key={system} className="rounded-full border border-[#24324a] bg-[#09111c] px-3 py-2 text-[12px] text-[#D8E4F4]">
                  {system}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
