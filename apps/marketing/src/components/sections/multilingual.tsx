import { SectionShell } from '@/components/section-shell';

export const MultilingualSection = () => (
  <SectionShell
    id="multilingual"
    eyebrow="Multilingual Operational Intelligence"
    title={
      <>
        Translate at the edge.
        <br />
        <span className="text-fg-muted">Reason in the core.</span>
      </>
    }
    description="Operious treats language as a boundary concern. Customer-language input is canonicalised to English at the edge before it reaches operational cognition; canonical English decisions are localised again on the way out. Governance never lives in two languages."
  >
    <div className="grid gap-px overflow-hidden rounded-md border border-line bg-line md:grid-cols-3">
      <div className="bg-bg-raised p-6 space-y-2">
        <p className="font-mono text-2xs uppercase tracking-widest text-accent">
          Ingress
        </p>
        <p className="font-display text-lg text-fg">
          customer language → canonical English
        </p>
        <p className="text-sm text-fg-muted">
          Boundary normalisation, semantic preservation checks, and lineage attachment.
          Translation NEVER alters governance meaning.
        </p>
      </div>
      <div className="bg-bg-raised p-6 space-y-2">
        <p className="font-mono text-2xs uppercase tracking-widest text-accent">
          Cognition
        </p>
        <p className="font-display text-lg text-fg">canonical English only</p>
        <p className="text-sm text-fg-muted">
          Every governance verdict, supervisor evaluation, and SOP proposal lives in
          a single canonical language. No cross-language drift.
        </p>
      </div>
      <div className="bg-bg-raised p-6 space-y-2">
        <p className="font-mono text-2xs uppercase tracking-widest text-accent">
          Egress
        </p>
        <p className="font-display text-lg text-fg">
          canonical English → customer language
        </p>
        <p className="text-sm text-fg-muted">
          Localisation rebuilds presentation in the customer&apos;s language.
          Operational meaning remains canonical.
        </p>
      </div>
    </div>
  </SectionShell>
);
