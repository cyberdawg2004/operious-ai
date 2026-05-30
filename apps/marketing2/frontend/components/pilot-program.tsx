import Link from "next/link";
import { ArrowRight } from "lucide-react";

const pilotSteps = [
  "Operational policy mapping - week 1",
  "Channel integration and configuration - week 2",
  "Governance deployment and threshold calibration - week 3",
  "Full production launch with live audit trail - week 4",
  "Operational review with your leadership team - weekly",
  "Complete audit export for your compliance team - on demand",
];

export function PilotProgram() {
  return (
    <section className="bg-canvas px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
      <div className="mx-auto max-w-[1280px]">
        <p
          className="text-[10px] uppercase tracking-[0.18em] text-gold"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          Pilot program
        </p>
        <h2
          className="mt-5 max-w-[900px] text-[38px] font-bold leading-tight text-ink-primary sm:text-[54px]"
          style={{ fontFamily: "var(--font-cormorant-sc)" }}
        >
          60-day production pilot. Full governance. Complete audit trail from Day 1.
        </h2>

        <div className="mt-10 grid gap-5 lg:grid-cols-2">
          <article className="rounded-md border border-border-subtle bg-white p-6">
            <p
              className="text-[10px] uppercase tracking-[0.18em] text-gold"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              What the pilot delivers
            </p>
            <p className="mt-5 text-[16px] leading-relaxed text-ink-body">
              The Operious pilot is a full production deployment against your real
              operational volume, your real policies, and your real customers.
            </p>
            <p className="mt-4 text-[16px] leading-relaxed text-ink-body">
              A proof-of-concept sandbox is available for architecture review.
              The pilot is for operations teams that are ready to automate a
              defined workflow with governance enforcement and a live audit trail.
            </p>
          </article>

          <article className="rounded-md border border-border-subtle bg-white p-6">
            <p
              className="text-[10px] uppercase tracking-[0.18em] text-gold"
              style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              Pilot structure
            </p>
            <ol className="mt-5 grid gap-3">
              {pilotSteps.map((step, index) => (
                <li key={step} className="flex gap-4 text-[15px] text-ink-body">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[#05080F] font-mono text-[11px] text-[#C9A84C]">
                    {index + 1}
                  </span>
                  <span className="pt-1">{step}</span>
                </li>
              ))}
            </ol>
          </article>
        </div>

        <div className="mt-6 rounded-md border border-[#C9A84C]/30 bg-[#C9A84C]/10 p-5 text-center">
          <p className="text-[15px] leading-relaxed text-ink-primary">
            Current status: pilot engagement active with a global consumer electronics
            manufacturer across email, WhatsApp, and voice channels in six languages.
          </p>
          <Link
            href="/company/contact?topic=pilot-program"
            className="mt-5 inline-flex h-12 items-center justify-center rounded-md bg-[#05080F] px-6 text-[14px] font-semibold text-white transition-all duration-300 hover:-translate-y-0.5 hover:bg-ink-body"
          >
            Apply for Pilot Program
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}
