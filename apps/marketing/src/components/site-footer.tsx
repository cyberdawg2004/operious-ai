export const SiteFooter = () => (
  <footer className="border-t border-line bg-bg-subtle">
    <div className="mx-auto grid max-w-7xl gap-8 px-6 py-12 md:grid-cols-4">
      <div className="space-y-2">
        <p className="font-mono text-2xs uppercase tracking-widest text-fg-subtle">
          operious.ai
        </p>
        <p className="text-sm text-fg-muted max-w-sm">
          Deterministic operational runtime infrastructure for the modern enterprise.
        </p>
      </div>
      <div>
        <p className="font-mono text-2xs uppercase tracking-wider text-fg-subtle mb-3">
          Architecture
        </p>
        <ul className="space-y-2 text-sm text-fg-muted">
          <li>Runtime substrates</li>
          <li>Governance & explainability</li>
          <li>Replay-safe lineage</li>
        </ul>
      </div>
      <div>
        <p className="font-mono text-2xs uppercase tracking-wider text-fg-subtle mb-3">
          Surfaces
        </p>
        <ul className="space-y-2 text-sm text-fg-muted">
          <li>Command Center</li>
          <li>Operations Queue</li>
          <li>Cognition Hub</li>
        </ul>
      </div>
      <div>
        <p className="font-mono text-2xs uppercase tracking-wider text-fg-subtle mb-3">
          Contact
        </p>
        <ul className="space-y-2 text-sm text-fg-muted">
          <li>pilot@operious.ai</li>
          <li>security@operious.ai</li>
        </ul>
      </div>
    </div>
    <div className="border-t border-line">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 font-mono text-2xs uppercase tracking-wider text-fg-dim">
        <span>© Operious AI</span>
        <span>Frontend visualizes authority. Backend owns it.</span>
      </div>
    </div>
  </footer>
);
