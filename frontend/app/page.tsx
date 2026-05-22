export default function Home() {
  return (
    <main className="flex-1">
      {/* Hero Section - Dark background to demonstrate navigation transparency */}
      <section className="relative min-h-screen bg-bg-dark flex items-center justify-center pt-[72px]">
        <div className="absolute inset-0 overflow-hidden">
          {/* Subtle grid pattern */}
          <div
            className="absolute inset-0 opacity-[0.03]"
            style={{
              backgroundImage: `linear-gradient(var(--ink-dark) 1px, transparent 1px),
                               linear-gradient(90deg, var(--ink-dark) 1px, transparent 1px)`,
              backgroundSize: "64px 64px",
            }}
          />
        </div>

        <div className="relative z-10 max-w-4xl mx-auto px-6 text-center">
          <p
            className="text-[11px] uppercase tracking-[0.18em] text-gold mb-8"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            Deterministic Multi-Agent Infrastructure
          </p>

          <h1
            className="text-[72px] font-bold leading-[1.05] tracking-[-0.02em] text-ink-dark mb-8"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            The operating system for <em className="not-italic text-gold">governed</em> enterprise execution
          </h1>

          <p className="text-[18px] leading-relaxed text-ink-dark-body max-w-2xl mx-auto mb-12 font-sans">
            Operious provides deterministic multi-agent orchestration for Fortune 500 
            companies in regulated industries. Complete audit trails. Zero hallucination tolerance. 
            Institutional-grade reliability.
          </p>

          <div className="flex items-center justify-center gap-4">
            <a
              href="/demo"
              className="inline-flex items-center justify-center h-12 px-8 text-[14px] font-medium text-bg-dark bg-ink-dark rounded hover:bg-ink-dark/90 transition-colors"
            >
              Request Demo
            </a>
            <a
              href="/platform"
              className="inline-flex items-center justify-center h-12 px-8 text-[14px] font-medium text-ink-dark border border-border-dark rounded hover:bg-surface-dark transition-colors"
            >
              Explore Platform
            </a>
          </div>
        </div>
      </section>

      {/* Light section to show navigation background transition */}
      <section className="min-h-screen bg-canvas flex items-center justify-center">
        <div className="max-w-4xl mx-auto px-6 text-center">
          <p
            className="text-[11px] uppercase tracking-[0.18em] text-gold mb-6"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            Scroll to see navigation transition
          </p>
          <h2
            className="text-[48px] font-semibold leading-[1.1] tracking-[-0.01em] text-ink-primary mb-6"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Enterprise-Grade Governance
          </h2>
          <p className="text-[16px] leading-relaxed text-ink-body max-w-xl mx-auto font-sans">
            The navigation bar transitions from transparent to a frosted glass effect 
            as you scroll, maintaining visual hierarchy while preserving content visibility.
          </p>
        </div>
      </section>
    </main>
  );
}
