import { Reveal } from '../ui/reveal';
import { SectionLabel } from '../ui/section-label';
import { SubstrateChat } from '../chat/substrate-chat';

/**
 * SECTION 7 — ASK THE SUBSTRATE  (light canvas, dark inset)
 *
 * Editorial copy left, dark chat panel right.
 */
export const SubstrateChatSection = () => (
  <section
    id="substrate"
    className="relative bg-canvas-raised border-y border-line-subtle"
  >
    <div className="mx-auto max-w-hero px-6 py-40 md:px-16">
      <div className="grid gap-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:items-start">
        <div>
          <Reveal>
            <SectionLabel index="06">LIVE COGNITION</SectionLabel>
          </Reveal>
          <Reveal delay={120}>
            <h2 className="heading-xl text-ink-primary mt-6">
              Ask the substrate directly.
            </h2>
          </Reveal>
          <Reveal delay={240}>
            <p className="body-l text-ink-body mt-6 max-w-prose">
              This chat interface runs on the same governed cognition runtime
              that powers Operious deployments. Ask architectural questions,
              technical questions, or operational scenarios. Responses are
              grounded in Operious documentation and policy-bounded by the
              governance substrate.
            </p>
          </Reveal>
          <Reveal delay={360}>
            <ul className="mt-8 space-y-3 body-s text-ink-secondary">
              <li className="flex gap-3">
                <span className="mt-1.5 h-1.5 w-1.5 flex-none rounded-full bg-gold" />
                <span>
                  Replies are bounded by the same ToolInvoker that governs
                  production tenants.
                </span>
              </li>
              <li className="flex gap-3">
                <span className="mt-1.5 h-1.5 w-1.5 flex-none rounded-full bg-gold" />
                <span>
                  Procurement and commercial terms are routed to the
                  enterprise contact track.
                </span>
              </li>
              <li className="flex gap-3">
                <span className="mt-1.5 h-1.5 w-1.5 flex-none rounded-full bg-gold" />
                <span>
                  Conversation lineage is persisted and replayable for
                  substrate evaluation.
                </span>
              </li>
            </ul>
          </Reveal>
        </div>

        <Reveal delay={180} className="lg:max-w-[820px]">
          <SubstrateChat variant="inset" />
        </Reveal>
      </div>
    </div>
  </section>
);

export default SubstrateChatSection;
