import Link from "next/link";

const proofStrip = [
  {
    label: "Operational Domains",
    value: "Hardware. Telco. Insurance. Banking.",
  },
  {
    label: "Channel Coverage",
    value: "Voice. Chat. Email. WhatsApp.",
  },
  {
    label: "Decision Accountability",
    value: "Every action governed. Every record permanent.",
  },
  {
    label: "Language Operations",
    value: "English. Arabic. Indonesian. Spanish. French. Chinese.",
  },
  {
    label: "Deployment Model",
    value: "Enterprise SaaS. Pilot to production in 60 days.",
  },
];

const problemColumns = [
  {
    title: "THE ACCOUNTABILITY GAP",
    body: [
      "When an AI agent approves a warranty claim, denies a refund, or escalates a case - who authorized that decision? What evidence exists? Can your legal team reconstruct it six months from now?",
      "In most enterprise operations today, the answer is no.",
    ],
  },
  {
    title: "THE SCALE CEILING",
    body: [
      "Human Tier 1 and Tier 2 operations do not scale without proportional headcount. Every new market, language, or product line requires more agents, more training, more oversight, and more cost - with no improvement in accountability.",
    ],
  },
  {
    title: "THE GOVERNANCE FAILURE",
    body: [
      "AI tools built into existing platforms - Zendesk, Salesforce, ServiceNow - operate within those platforms' rules, not yours. Policy enforcement, approval workflows, and audit trails remain your problem to solve.",
    ],
  },
];

const solutionColumns = [
  {
    title: "GOVERNED EXECUTION",
    body: "Every operational action - whether initiated by AI or a human agent - passes through Operious before it executes. Policy is checked. Authorization is verified. The decision and its full justification are permanently recorded.",
  },
  {
    title: "FORENSIC ACCOUNTABILITY",
    body: "Any decision made through Operious can be reconstructed in full - the input, the policy evaluated, the authorization chain, the action taken, and the outcome - at any point in time. Your auditors have what they need before they ask.",
  },
  {
    title: "SCALE WITHOUT RISK",
    body: "Voice calls answered. Emails resolved. WhatsApp handled. Warranty claims processed. Refunds authorized. Escalations routed. Operious runs the workflow, enforces the policy, and produces the evidence - in six languages, at enterprise volume.",
  },
];

const steps = [
  {
    title: "INTAKE AND CLASSIFICATION",
    body: "Customer contacts arrive via any channel. Operious classifies the intent, detects the language, validates the source, and routes to the appropriate workflow. Every contact creates an immutable intake record.",
  },
  {
    title: "GOVERNANCE AND AUTHORIZATION",
    body: "Before any action executes, Operious evaluates the applicable policy chain. Low-risk actions are authorized and executed automatically. High-risk actions are routed to a human decision-maker with full context. No action bypasses governance.",
  },
  {
    title: "EXECUTION AND EVIDENCE",
    body: "Actions execute with a permanent forensic record - the policy applied, the authorization granted, the action taken, the outcome delivered. Your operations team, your compliance team, and your legal team have the evidence they need, without asking for it.",
  },
];

const domains = [
  {
    title: "CONSUMER ELECTRONICS",
    body: "Warranty claims, replacement authorizations, repair routing, and defect escalation - governed, executed, and fully documented at global scale.",
  },
  {
    title: "TELECOMMUNICATIONS",
    body: "Service disputes, contract modifications, billing escalations, and plan changes - handled within policy and recorded for regulatory compliance.",
  },
  {
    title: "INSURANCE",
    body: "Claims intake, policy exception approvals, adjuster routing, and compliance documentation - every step authorized and auditable.",
  },
  {
    title: "BANKING AND FINANCIAL SERVICES",
    body: "Account management, dispute resolution, fraud escalation, and regulatory correspondence - with the audit trail financial regulators require.",
  },
  {
    title: "HEALTHCARE",
    body: "Patient inquiry handling, authorization requests, billing disputes, and escalation routing - within the governance framework healthcare compliance demands.",
  },
  {
    title: "LOGISTICS",
    body: "Shipment exceptions, claims resolution, carrier disputes, and customer escalations - handled at volume with complete accountability.",
  },
];

const pilotItems = [
  "Operational policy mapping and configuration",
  "Channel integration with your existing infrastructure",
  "Full governance deployment with defined approval thresholds",
  "Live audit trail and evidence access for your compliance team",
  "Weekly operational review with your leadership team",
];

const roiColumns = [
  {
    title: "COST REDUCTION",
    body: "Enterprise Tier 1 and Tier 2 BPO operations typically cost $15,000 to $40,000 per month per 3,000 daily contacts. Operious delivers equivalent or superior resolution outcomes with a fixed, predictable infrastructure cost - regardless of contact volume growth.",
  },
  {
    title: "LIABILITY ELIMINATION",
    body: "Every unauthorized action by an AI system represents an unquantified liability. The cost of a single regulatory inquiry, legal challenge, or compliance failure typically exceeds annual Operious deployment costs. Governance infrastructure is not a cost center. It is risk management.",
  },
  {
    title: "OPERATIONAL INTELLIGENCE",
    body: "Operious transforms every operational contact into a structured, queryable data asset. Pattern detection, defect correlation, SOP improvement, and compliance reporting become byproducts of operations - not separate workstreams requiring additional staffing.",
  },
];

function PrimaryCta({ children, href }: { children: string; href: string }) {
  return (
    <Link
      href={href}
      className="inline-flex min-h-12 items-center justify-center rounded-md bg-[#C9A84C] px-5 text-[14px] font-semibold text-[#05080F] transition-colors duration-200 hover:bg-[#D9B85A]"
    >
      {children}
    </Link>
  );
}

function SecondaryCta({ children, href }: { children: string; href: string }) {
  return (
    <Link
      href={href}
      className="inline-flex min-h-12 items-center justify-center rounded-md border border-white/15 px-5 text-[14px] font-semibold text-white transition-colors duration-200 hover:border-[#C9A84C]/60 hover:text-[#C9A84C]"
    >
      {children}
    </Link>
  );
}

function SectionLabel({ children }: { children: string }) {
  return (
    <p className="font-mono text-[12px] font-semibold uppercase tracking-[0.08em] text-white/55">
      {children}
    </p>
  );
}

function SectionHeader({
  label,
  title,
  body,
}: {
  label: string;
  title: string;
  body?: string;
}) {
  return (
    <div className="max-w-[940px]">
      <SectionLabel>{label}</SectionLabel>
      <h2 className="mt-5 text-[40px] font-semibold leading-[1.05] tracking-[-0.02em] text-white sm:text-[56px] lg:text-[68px]">
        {title}
      </h2>
      {body && (
        <p className="mt-6 max-w-[780px] text-[20px] font-normal leading-[1.6] text-white/55 sm:text-[22px]">
          {body}
        </p>
      )}
    </div>
  );
}

function TextCard({
  title,
  body,
}: {
  title: string;
  body: string | string[];
}) {
  const paragraphs = Array.isArray(body) ? body : [body];

  return (
    <article className="border-t border-white/12 pt-6">
      <h3 className="font-mono text-[12px] font-semibold uppercase tracking-[0.08em] text-[#C9A84C]">
        {title}
      </h3>
      <div className="mt-5 space-y-5">
        {paragraphs.map((paragraph) => (
          <p
            key={paragraph}
            className="text-[17px] font-normal leading-[1.7] text-white/65"
          >
            {paragraph}
          </p>
        ))}
      </div>
    </article>
  );
}

function LightSection({
  id,
  label,
  title,
  body,
  children,
}: {
  id?: string;
  label: string;
  title: string;
  body?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="border-t border-white/10 bg-[#050508] px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
      <div className="mx-auto max-w-[1280px]">
        <SectionHeader label={label} title={title} body={body} />
        {children}
      </div>
    </section>
  );
}

export default function Home() {
  return (
    <main className="flex-1 overflow-x-hidden bg-[#050508] text-white">
      <section
        id="platform"
        className="border-b border-white/10 bg-[#050508] px-4 pb-16 pt-32 sm:px-8 sm:pb-20 sm:pt-40 lg:px-16"
      >
        <div className="mx-auto max-w-[1280px]">
          <SectionLabel>Operational Governance Infrastructure</SectionLabel>
          <div className="mt-8 max-w-[1040px]">
            <h1 className="text-[46px] font-semibold leading-[1.02] tracking-[-0.02em] text-white sm:text-[64px] lg:text-[72px]">
              Operational workflows that scale.
              <br />
              Decisions that hold up in any audit.
            </h1>
            <p className="mt-8 max-w-[900px] text-[20px] font-normal leading-[1.6] text-white/60 sm:text-[24px]">
              Operious runs Tier 1 and Tier 2 enterprise operations - support,
              warranty, claims, escalations, and approvals - with enforced
              policy, complete governance, and a forensic record of every
              decision made.
            </p>
          </div>

          <div className="mt-10 flex flex-col gap-3 sm:flex-row">
            <PrimaryCta href="/company/contact?topic=architecture-review">
              Book an Architecture Review
            </PrimaryCta>
            <SecondaryCta href="/company/contact?topic=security">
              Request Security Overview
            </SecondaryCta>
          </div>

          <p className="mt-6 max-w-[760px] font-mono text-[12px] uppercase tracking-[0.08em] text-white/45">
            Pilot engagement currently active with a major global consumer
            electronics manufacturer.
          </p>
        </div>
      </section>

      <section className="border-b border-white/10 bg-[#050508] px-4 py-8 sm:px-8 lg:px-16">
        <div className="mx-auto grid max-w-[1280px] gap-6 md:grid-cols-5 md:gap-0">
          {proofStrip.map((item) => (
            <div
              key={item.label}
              className="border-white/10 md:border-r md:px-5 md:first:pl-0 md:last:border-r-0 md:last:pr-0"
            >
              <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-white/40">
                {item.label}
              </p>
              <p className="mt-2 text-[15px] leading-[1.55] text-white/75">
                {item.value}
              </p>
            </div>
          ))}
        </div>
      </section>

      <LightSection
        label="The Problem"
        title="Enterprise operations carry operational and legal risk that human BPO and ungoverned AI cannot resolve."
      >
        <div className="mt-14 grid gap-8 lg:grid-cols-3">
          {problemColumns.map((column) => (
            <TextCard key={column.title} title={column.title} body={column.body} />
          ))}
        </div>
      </LightSection>

      <LightSection
        label="The Solution"
        title="Operious is the operational governance layer that runs between your enterprise systems and your customers."
        body="Not a chatbot. Not a workflow tool. The infrastructure that enforces policy, controls actions, and proves every decision."
      >
        <div className="mt-14 grid gap-8 lg:grid-cols-3">
          {solutionColumns.map((column) => (
            <TextCard key={column.title} title={column.title} body={column.body} />
          ))}
        </div>
      </LightSection>

      <LightSection
        label="How It Works"
        title="Three layers. Complete operational control."
      >
        <div className="mt-14 grid gap-5 lg:grid-cols-3">
          {steps.map((step, index) => (
            <article
              key={step.title}
              className="border border-white/10 bg-white/[0.025] p-6"
            >
              <p className="font-mono text-[12px] font-semibold uppercase tracking-[0.08em] text-[#C9A84C]">
                {String(index + 1).padStart(2, "0")}
              </p>
              <h3 className="mt-8 font-mono text-[12px] font-semibold uppercase tracking-[0.08em] text-white">
                {step.title}
              </h3>
              <p className="mt-5 text-[17px] leading-[1.7] text-white/62">
                {step.body}
              </p>
            </article>
          ))}
        </div>
      </LightSection>

      <LightSection
        id="solutions"
        label="Operational Domains"
        title="Built for the operational complexity of regulated enterprise business."
      >
        <div className="mt-14 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {domains.map((domain) => (
            <article
              key={domain.title}
              className="min-h-[220px] border border-white/10 bg-[#0B0D12] p-6"
            >
              <h3 className="font-mono text-[12px] font-semibold uppercase tracking-[0.08em] text-white">
                {domain.title}
              </h3>
              <p className="mt-5 text-[17px] leading-[1.7] text-white/62">
                {domain.body}
              </p>
            </article>
          ))}
        </div>
      </LightSection>

      <LightSection
        label="Integration"
        title="Operious operates alongside your existing stack. Not instead of it."
        body="Your CRM, ticketing platform, and telephony infrastructure stay in place. Operious connects to your existing channels, applies governance to every action, and writes evidence back to your systems of record."
      >
        <div className="mt-10 grid gap-8 lg:grid-cols-[1fr_0.85fr]">
          <div className="border border-white/10 bg-white/[0.025] p-6 sm:p-8">
            <p className="text-[17px] leading-[1.7] text-white/65">
              Operious works alongside Zendesk, Salesforce, ServiceNow, and any
              other platform your operations teams currently use. The
              governance layer sits between your AI actions and your customers -
              ensuring every decision is authorized before it executes,
              regardless of which system initiated it.
            </p>
          </div>
          <div className="grid gap-5">
            <div className="border-t border-white/12 pt-5">
              <h3 className="font-mono text-[12px] font-semibold uppercase tracking-[0.08em] text-[#C9A84C]">
                Channels accepted
              </h3>
              <p className="mt-4 text-[17px] leading-[1.7] text-white/65">
                Email • WhatsApp Business • Voice (Twilio and compatible) • Web
                chat • Zendesk • Shulex • Lark
              </p>
            </div>
            <div className="border-t border-white/12 pt-5">
              <h3 className="font-mono text-[12px] font-semibold uppercase tracking-[0.08em] text-[#C9A84C]">
                Evidence delivered to
              </h3>
              <p className="mt-4 text-[17px] leading-[1.7] text-white/65">
                Jira • Linear • Your CRM • Your ticketing system • Your
                compliance team • Your audit record
              </p>
            </div>
          </div>
        </div>
      </LightSection>

      <LightSection
        id="security"
        label="Security And Trust"
        title="Built to the accountability standard your compliance and legal teams require."
      >
        <div className="mt-14 grid gap-8 lg:grid-cols-2">
          <TextCard
            title="ARCHITECTURE"
            body="All data is tenant-isolated at the database row level, with mandatory security policies enforced at the storage layer. Credentials are encrypted at rest using AES-GCM. Access is governed by role-based authorization with complete session audit logging."
          />
          <TextCard
            title="EVIDENCE"
            body="Every operational decision generates a permanent, append-only record including: the input received, the policy evaluated, the authorization chain, the action taken, and the outcome. Records are cryptographically identified and cannot be modified after creation."
          />
        </div>
        <div className="mt-10 flex flex-col gap-5 border-t border-white/12 pt-8 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-[760px] text-[17px] leading-[1.7] text-white/62">
            Security architecture documentation and data processing addendum
            available to qualified prospects.
          </p>
          <PrimaryCta href="/company/contact?topic=security-packet">
            Request Security Packet →
          </PrimaryCta>
        </div>
      </LightSection>

      <LightSection
        id="pilot"
        label="Pilot Program"
        title="60-day production pilot. Real operations. Complete accountability from Day 1."
        body="The Operious pilot is not a sandbox demonstration. It is a full production deployment against your real operational volume, your real policies, and your real customers - with complete governance enforcement and a live audit trail from the first contact."
      >
        <div className="mt-12 grid gap-8 lg:grid-cols-[0.85fr_1.15fr]">
          <div className="border border-white/10 bg-white/[0.025] p-6 sm:p-8">
            <h3 className="font-mono text-[12px] font-semibold uppercase tracking-[0.08em] text-[#C9A84C]">
              Pilot engagements include
            </h3>
            <ul className="mt-6 space-y-4">
              {pilotItems.map((item) => (
                <li
                  key={item}
                  className="border-t border-white/10 pt-4 text-[17px] leading-[1.65] text-white/65"
                >
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div className="flex flex-col justify-between border border-white/10 bg-[#0B0D12] p-6 sm:p-8">
            <p className="text-[22px] leading-[1.55] text-white/76">
              A current pilot is active with a global consumer electronics
              manufacturer, covering multilingual support operations across
              email, WhatsApp, and voice channels.
            </p>
            <div className="mt-10 flex flex-col gap-3 sm:flex-row">
              <PrimaryCta href="/company/contact?topic=pilot">
                Apply for a Pilot Engagement →
              </PrimaryCta>
              <SecondaryCta href="/company/contact?topic=architecture-review">
                Book an Architecture Review First
              </SecondaryCta>
            </div>
          </div>
        </div>
      </LightSection>

      <LightSection
        label="ROI"
        title="The economic case for governed AI operations."
      >
        <div className="mt-14 grid gap-8 lg:grid-cols-3">
          {roiColumns.map((column) => (
            <TextCard key={column.title} title={column.title} body={column.body} />
          ))}
        </div>
      </LightSection>

      <section className="border-t border-white/10 bg-[#050508] px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
        <div className="mx-auto max-w-[980px] text-center">
          <h2 className="text-[40px] font-semibold leading-[1.08] tracking-[-0.02em] text-white sm:text-[56px] lg:text-[68px]">
            The companies that govern their AI operations now will not be
            explaining their decisions later.
          </h2>
          <p className="mx-auto mt-6 max-w-[780px] text-[20px] leading-[1.6] text-white/58">
            Regulatory scrutiny of automated enterprise decisions is
            accelerating. The question is not whether your operations will be
            examined - it is whether you will have the evidence to withstand
            examination.
          </p>
          <div className="mt-10 flex flex-col justify-center gap-3 sm:flex-row">
            <PrimaryCta href="/company/contact?topic=architecture-review">
              Book an Architecture Review
            </PrimaryCta>
            <SecondaryCta href="/company/contact?topic=security-documentation">
              Request Security Documentation
            </SecondaryCta>
          </div>
          <div className="mt-8 flex flex-col justify-center gap-3 font-mono text-[11px] uppercase tracking-[0.08em] text-white/45 sm:flex-row">
            <span>Enterprise SaaS deployment</span>
            <span className="hidden text-white/20 sm:inline">•</span>
            <span>60-day pilot to full production</span>
            <span className="hidden text-white/20 sm:inline">•</span>
            <span>Forensic audit trail from Day 1</span>
          </div>
        </div>
      </section>
    </main>
  );
}
