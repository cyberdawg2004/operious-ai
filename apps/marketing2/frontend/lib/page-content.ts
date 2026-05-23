import {
  companyLinks,
  industryLinks,
  insightLinks,
  platformLinks,
  trustLinks,
  type SiteLink,
} from "./site-links";

export type ContentSection = {
  title: string;
  body: string[];
};

export type ContentCard = {
  title: string;
  body: string;
  href?: string;
  meta?: string;
};

export type PageContent = {
  eyebrow: string;
  title: string;
  subtitle: string;
  intro: string[];
  sections: ContentSection[];
  cards?: ContentCard[];
  ctas?: SiteLink[];
};

export type PageKey =
  | "platform"
  | "platformGovernance"
  | "platformReplay"
  | "platformAgents"
  | "industries"
  | "industryHardware"
  | "industryFinancialServices"
  | "industryHealthcare"
  | "industryInsurance"
  | "industryTelecom"
  | "industryLogistics"
  | "industryPublicSector"
  | "trust"
  | "trustArchitecture"
  | "trustCompliance"
  | "insights"
  | "articleConstitutionalGovernance"
  | "articleReconstructibleTruth"
  | "articleBeyondWrappers"
  | "articleAuditTrailProduct"
  | "articleMultiLanguage"
  | "pricing"
  | "company"
  | "privacy"
  | "terms"
  | "security";

export const pages: Record<PageKey, PageContent> = {
  platform: {
    eyebrow: "Platform",
    title: "A deterministic operating layer for regulated enterprise work.",
    subtitle:
      "Operious coordinates agents, policies, sessions, execution, supervision, and replay as one governed substrate.",
    intro: [
      "Most enterprise AI products begin with a model and wrap operational controls around it later. Operious starts from the opposite premise: authority, identity, governance, and replay must exist before autonomy is allowed to execute.",
      "The platform is organized as an operational substrate. Boundary, coordination, governance, session, execution, supervisor, and arbitration layers each own a narrow responsibility. That separation lets enterprises automate work while preserving a defensible account of what happened, why it happened, and which policy authorized it.",
    ],
    sections: [
      {
        title: "Governance before execution",
        body: [
          "Every proposed action must pass deterministic policy evaluation before it can change state, communicate externally, or invoke a tool. The governance layer issues admission tokens for permitted actions and denies everything else by default.",
        ],
      },
      {
        title: "Replay as an operating requirement",
        body: [
          "Operational events are written to an append-only fabric. Deterministic identity, immutable event ordering, and projection bridges allow a decision to be reconstructed from the exact state available at the time.",
        ],
      },
      {
        title: "Agents with bounded authority",
        body: [
          "Specialized agents can diagnose, escalate, verify, and retrieve procedure knowledge. They propose work. The substrate decides what is legal to execute.",
        ],
      },
    ],
    cards: platformLinks.map((link) => ({
      title: link.label,
      body: link.description ?? "",
      href: link.href,
    })),
    ctas: [{ label: "Request enterprise access", href: "/company/contact" }],
  },
  platformGovernance: {
    eyebrow: "Platform / Governance",
    title: "Constitutional governance is runtime enforcement, not policy theater.",
    subtitle:
      "Operious treats policy as an executable control plane with fail-closed defaults and durable admission records.",
    intro: [
      "Prompts are not governance. A prompt can instruct a model to follow policy, but it cannot prove that policy was evaluated, that the correct rule version was used, or that an unauthorized action was structurally impossible.",
      "Operious places governance between cognition and execution. Agents may classify, summarize, or recommend. They cannot send a message, approve a refund, mutate a case, or call an external system until the governance runtime grants an admission token.",
    ],
    sections: [
      {
        title: "Fail-closed by default",
        body: [
          "When no policy chain exists, when the subject cannot be resolved, or when evidence is incomplete, the system denies the action. This default is intentionally conservative because regulated operations require proof of permission, not proof that nothing went wrong.",
        ],
      },
      {
        title: "Capability legality gates",
        body: [
          "Each agent capability is declared, scoped, and evaluated against tenant policy. The legality gate binds actor, action, target, evidence, and policy version into an execution decision that can be stored and replayed.",
        ],
      },
      {
        title: "Persistent governance failures",
        body: [
          "A denied action is not discarded as a runtime error. It becomes an operational fact. The denial, reason, policy chain, and relevant context are preserved so supervisors and auditors can inspect the boundary condition.",
        ],
      },
    ],
    ctas: [
      { label: "See forensic replay", href: "/platform/replay" },
      { label: "Schedule an architecture review", href: "/company/contact" },
    ],
  },
  platformReplay: {
    eyebrow: "Platform / Replay",
    title: "Reconstructible organizational truth for decisions under scrutiny.",
    subtitle:
      "Operious makes operational decisions replayable from deterministic identity, append-only events, and tenant-owned state.",
    intro: [
      "The central audit question is not whether an AI system produced a log line. The question is whether the enterprise can reconstruct the decision as it existed at that point in time, including state, policy, evidence, agent proposal, and execution result.",
      "Operious builds that reconstruction path into the architecture. Events are appended, identities are deterministic, and projections are derived rather than treated as the source of truth.",
    ],
    sections: [
      {
        title: "UUID5 deterministic identity",
        body: [
          "Stable identifiers are derived from canonical business facts where appropriate. The same tenant, workflow, subject, and version inputs produce the same identity, which reduces ambiguity across replay, trace inspection, and downstream projections.",
        ],
      },
      {
        title: "Append-only event fabric",
        body: [
          "Operational events are not a side-channel log. They are the audit spine of the system. Derived views can be rebuilt, but the event fabric remains the durable record of decisions, denials, approvals, and state transitions.",
        ],
      },
      {
        title: "Projection bridges",
        body: [
          "Operational screens, reports, and exports are projections from the event fabric. This keeps human-facing views useful without turning them into unverifiable sources of truth.",
        ],
      },
    ],
    ctas: [
      { label: "Read the replay article", href: "/insights/reconstructible-truth" },
      { label: "Request enterprise access", href: "/company/contact" },
    ],
  },
  platformAgents: {
    eyebrow: "Platform / Agents",
    title: "Multi-agent coordination with authority boundaries.",
    subtitle:
      "Operious uses specialized agents for cognition while preserving deterministic control over execution.",
    intro: [
      "A regulated enterprise does not need a swarm of unconstrained agents improvising inside production operations. It needs bounded specialization, clear authority, and an audit trail that explains how a recommendation became an action.",
      "Operious separates agent cognition from execution authority. Agents propose, retrieve, classify, diagnose, and escalate. The governance and supervisor runtimes determine whether proposed work may proceed.",
    ],
    sections: [
      {
        title: "Specialized operational agents",
        body: [
          "Diagnostic agents inspect case context and identify probable paths. Escalation agents determine when a human, queue, or policy exception is required. QA agents evaluate response quality. SOP intelligence agents retrieve and ground procedural knowledge.",
        ],
      },
      {
        title: "Supervisor runtime",
        body: [
          "The supervisor runtime observes agent work, evaluates completion criteria, and records findings. It is not a cosmetic dashboard layer; it is part of the control plane that keeps workflows bounded and inspectable.",
        ],
      },
      {
        title: "LLM proposes, governance enforces",
        body: [
          "Language models are useful for interpretation and classification. They do not own authority. Operious keeps final execution inside deterministic substrate rules that can be tested, replayed, and audited.",
        ],
      },
    ],
    ctas: [
      { label: "Explore platform overview", href: "/platform" },
      { label: "Schedule an architecture review", href: "/company/contact" },
    ],
  },
  industries: {
    eyebrow: "Industries",
    title: "Operational infrastructure for regulated domains.",
    subtitle:
      "Operious is designed for domains where automation must be explainable, policy-bound, and tenant-isolated.",
    intro: [
      "Across regulated industries, the pattern is consistent: high-volume operational work, multilingual customer or citizen communication, fragmented systems of record, and audit expectations that ordinary AI tools cannot satisfy.",
      "Operious gives each domain a governed execution layer that can coordinate work without erasing accountability.",
    ],
    sections: [
      {
        title: "Domain-specific policy",
        body: [
          "Each deployment carries tenant-owned policies, procedures, knowledge, escalation rules, and compliance constraints. The substrate remains consistent while the operational constitution adapts to the domain.",
        ],
      },
      {
        title: "One architecture, many regulated workflows",
        body: [
          "The same event fabric and governance runtime can support warranty triage, healthcare intake, dispute resolution, claims handling, service interruption tickets, shipment exceptions, and citizen service requests.",
        ],
      },
    ],
    cards: industryLinks.slice(1).map((link) => ({
      title: link.label,
      body: link.description ?? "",
      href: link.href,
    })),
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact" }],
  },
  industryHardware: {
    eyebrow: "Industries / Hardware",
    title: "Operious for hardware companies.",
    subtitle:
      "Governed execution for consumer electronics warranty, returns, defect triage, and multilingual support.",
    intro: [
      "Hardware operations combine physical product behavior, warranty rules, return windows, regional obligations, and customer communication under pressure. A charging issue, recurring defect, or ambiguous return request can move through multiple teams before a final decision is made.",
      "Operious provides a governed layer for Tier 1 and Tier 2 workflows where every recommendation, escalation, approval, and denial remains reconstructible.",
    ],
    sections: [
      {
        title: "Where it fits",
        body: [
          "Warranty eligibility checks, returns processing, charging-issue triage, defect categorization, parts availability routing, multilingual support classification, and escalation to engineering or quality teams.",
        ],
      },
      {
        title: "Governance considerations",
        body: [
          "Refund authority, replacement authorization, regional warranty language, safety-related defect handling, and customer communication templates can be encoded as tenant-controlled policy.",
        ],
      },
      {
        title: "Example workflow",
        body: [
          "A customer reports a device that will not charge. Operious classifies the symptom, retrieves the current troubleshooting procedure, checks warranty state, records evidence, and either proposes a guided response or escalates for replacement approval when policy requires human review.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=hardware" }],
  },
  industryFinancialServices: {
    eyebrow: "Industries / Financial Services",
    title: "Operious for financial services.",
    subtitle:
      "Deterministic triage for disputes, fraud-adjacent tickets, service requests, and regulator-facing audit trails.",
    intro: [
      "Financial operations teams need automation that can move quickly without confusing judgment, compliance, and execution authority. Disputes, account servicing, exception requests, and fraud-adjacent tickets require evidence discipline.",
      "Operious coordinates operational work while keeping policy evaluation and event lineage outside the language model.",
    ],
    sections: [
      {
        title: "Where it fits",
        body: [
          "Dispute intake, fraud-adjacent triage, document completeness checks, service request routing, exception classification, escalation recommendations, and customer communication drafting.",
        ],
      },
      {
        title: "Governance considerations",
        body: [
          "FINRA, CFPB, GLBA, retention requirements, complaint handling, and internal approval limits can be represented as policies and reviewed as part of the event trace. Certification and attestation scope depends on the deployment.",
        ],
      },
      {
        title: "Example workflow",
        body: [
          "A disputed transaction enters the queue. Operious extracts relevant facts, checks required evidence, evaluates routing policy, records the decision path, and escalates to the appropriate team when the request approaches regulated complaint criteria.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=financial-services" }],
  },
  industryHealthcare: {
    eyebrow: "Industries / Healthcare",
    title: "Operious for healthcare.",
    subtitle:
      "PHI-aware operational automation for patient communication, intake, and governed routing.",
    intro: [
      "Healthcare operations require careful separation between administrative support, clinical judgment, PHI handling, and patient communication. Automation that cannot prove where information came from or which policy allowed an action creates unacceptable risk.",
      "Operious supports patient-facing and administrative workflows with tenant isolation, governed access, and replayable decision records.",
    ],
    sections: [
      {
        title: "Where it fits",
        body: [
          "Patient intake automation, eligibility routing, appointment support, document completeness checks, non-clinical communication drafting, prior authorization support, and escalation to authorized staff.",
        ],
      },
      {
        title: "Governance considerations",
        body: [
          "HIPAA-aligned handling, PHI minimization, role-bound access, audit exports, and Business Associate Agreement support are treated as deployment requirements rather than optional add-ons.",
        ],
      },
      {
        title: "Example workflow",
        body: [
          "A patient submits an intake request with incomplete information. Operious identifies missing fields, checks what communication is permitted, drafts a compliant request for clarification, and records the policy basis for the outbound message.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=healthcare" }],
  },
  industryInsurance: {
    eyebrow: "Industries / Insurance",
    title: "Operious for insurance.",
    subtitle:
      "Governed automation for FNOL intake, claims triage, policy questions, and escalation control.",
    intro: [
      "Insurance operations depend on accurate intake, clear policy interpretation, timely triage, and evidence-preserving handoffs. An AI system that invents coverage language or loses decision context cannot be trusted near claims workflows.",
      "Operious keeps cognition useful while preserving deterministic governance around what can be communicated, escalated, or executed.",
    ],
    sections: [
      {
        title: "Where it fits",
        body: [
          "First notice of loss handling, claims triage, document checks, coverage question routing, policyholder communication drafting, and escalation to licensed adjusters or specialist queues.",
        ],
      },
      {
        title: "Governance considerations",
        body: [
          "State-specific rules, policy versioning, unfair claims practice controls, retention obligations, and adjuster authority boundaries can be encoded into tenant governance.",
        ],
      },
      {
        title: "Example workflow",
        body: [
          "A policyholder reports a loss. Operious gathers structured facts, checks required documentation, classifies severity, records the decision path, and escalates when the policy or jurisdiction requires licensed review.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=insurance" }],
  },
  industryTelecom: {
    eyebrow: "Industries / Telecommunications",
    title: "Operious for telecommunications.",
    subtitle:
      "Governed execution for service interruptions, billing disputes, SIM flows, and device provisioning.",
    intro: [
      "Telecom operations run at high volume across network state, billing systems, provisioning tools, device catalogs, and regulatory obligations. Customers expect speed, while operations leaders need consistency and auditability.",
      "Operious provides deterministic coordination for support workflows that span systems and require policy-bound decisions.",
    ],
    sections: [
      {
        title: "Where it fits",
        body: [
          "Service interruption tickets, outage-related routing, billing dispute intake, SIM activation support, device provisioning checks, plan migration questions, and escalation to network or billing specialists.",
        ],
      },
      {
        title: "Governance considerations",
        body: [
          "Customer consent, regulatory disclosures, account ownership checks, carrier-specific policy, and provisioning authority can be enforced before execution.",
        ],
      },
      {
        title: "Example workflow",
        body: [
          "A customer reports loss of service after a SIM change. Operious checks account context, recent provisioning events, outage signals, and policy constraints before proposing the next support action or escalating to a network queue.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=telecom" }],
  },
  industryLogistics: {
    eyebrow: "Industries / Logistics",
    title: "Operious for logistics.",
    subtitle:
      "Replayable operational decisions for shipment exceptions, cross-border documentation, and delivery disputes.",
    intro: [
      "Logistics teams operate through exceptions: delayed shipments, address mismatches, customs documentation issues, carrier handoffs, and delivery disputes. Each exception touches contractual promises and customer communication.",
      "Operious creates a governed decision layer that can coordinate triage and preserve the evidence trail behind every operational action.",
    ],
    sections: [
      {
        title: "Where it fits",
        body: [
          "Shipment exception triage, cross-border documentation review, delivery dispute intake, carrier SLA routing, damaged goods workflows, and customer status communication.",
        ],
      },
      {
        title: "Governance considerations",
        body: [
          "Customs documentation rules, carrier contract policy, customer notification boundaries, and refund or credit authority can be encoded per tenant and region.",
        ],
      },
      {
        title: "Example workflow",
        body: [
          "A shipment stalls at a border checkpoint. Operious checks required documents, classifies the exception, routes the case to the correct operations queue, and records why a customer message or escalation was permitted.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=logistics" }],
  },
  industryPublicSector: {
    eyebrow: "Industries / Public Sector",
    title: "Operious for public sector.",
    subtitle:
      "Governed handling for citizen requests, jurisdictional policy, and FOIA-compatible audit records.",
    intro: [
      "Public sector operations must serve citizens consistently across departments, programs, languages, and jurisdictions. Automation must respect policy boundaries while producing records that can withstand public accountability.",
      "Operious supports service request workflows with deterministic governance and replayable event histories.",
    ],
    sections: [
      {
        title: "Where it fits",
        body: [
          "Citizen service requests, permit intake, benefits routing, public works tickets, records request handling, multilingual communication drafting, and escalation across agencies or jurisdictions.",
        ],
      },
      {
        title: "Governance considerations",
        body: [
          "FOIA-compatible audit logs, public records retention, accessibility, jurisdiction-specific rules, and FedRAMP-aligned deployment planning can be represented in the architecture. FedRAMP authorization remains roadmap-dependent for deployment scope.",
        ],
      },
      {
        title: "Example workflow",
        body: [
          "A citizen submits a service request that crosses departmental boundaries. Operious classifies the request, checks jurisdictional routing policy, records the decision path, and assigns the case without losing the audit trail.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=public-sector" }],
  },
  trust: {
    eyebrow: "Trust",
    title: "Security and governance are part of the product boundary.",
    subtitle:
      "Operious is designed around tenant isolation, encrypted credentials, fail-closed governance, and audit reconstruction.",
    intro: [
      "Regulated enterprises cannot adopt AI operations on the basis of model quality alone. They need architecture that answers questions from security teams, compliance teams, regulators, and operations leaders.",
      "Operious treats trust as a system property. Identity, isolation, authorization, event lineage, and replay are designed together.",
    ],
    sections: [
      {
        title: "Tenant isolation",
        body: [
          "Tenant-scoped data access is enforced as a database and application contract. Credentials, policies, documents, operational events, and projected views are isolated by tenant.",
        ],
      },
      {
        title: "Governance fail-closed",
        body: [
          "When governance cannot prove an action is permitted, the default result is denial. This keeps uncertainty from becoming unauthorized execution.",
        ],
      },
      {
        title: "Compliance roadmap",
        body: [
          "Operious communicates certification status plainly. SOC 2 Type II and ISO 27001 are roadmap items, HIPAA BAA support is available for healthcare deployments, and deployment-specific attestations are handled during enterprise review.",
        ],
      },
    ],
    cards: trustLinks.map((link) => ({
      title: link.label,
      body: link.description ?? "",
      href: link.href,
    })),
    ctas: [{ label: "Request security review", href: "/company/contact?topic=security" }],
  },
  trustArchitecture: {
    eyebrow: "Trust / Architecture",
    title: "Technical security architecture for governed execution.",
    subtitle:
      "The security model combines tenant isolation, credential encryption, append-only auditability, and static boundary enforcement.",
    intro: [
      "Operious is built for environments where operational automation touches sensitive data, regulated workflows, and enterprise systems of record. The architecture must limit blast radius and preserve evidence.",
      "Security controls are mapped to the substrate: credentials are tenant-scoped, database access is tenant-scoped, events are append-only, and cross-substrate bypass paths are treated as design violations.",
    ],
    sections: [
      {
        title: "Encrypted tenant credentials",
        body: [
          "Credential material is designed for AES-256-GCM encryption with tenant-specific keys derived through HKDF. The intended operating model prevents one tenant's credentials from being usable in another tenant context.",
        ],
      },
      {
        title: "Row-level tenant isolation",
        body: [
          "Operational records are scoped by tenant at the data layer and at the service boundary. Tenant context is not a UI filter; it is an access invariant.",
        ],
      },
      {
        title: "Append-only audit event fabric",
        body: [
          "Governance decisions, execution attempts, denials, approvals, and derived projections flow from an event fabric that can be inspected and replayed.",
        ],
      },
    ],
    ctas: [
      { label: "Read compliance posture", href: "/trust/compliance" },
      { label: "Request enterprise access", href: "/company/contact?topic=security" },
    ],
  },
  trustCompliance: {
    eyebrow: "Trust / Compliance",
    title: "Honest compliance posture and roadmap.",
    subtitle:
      "Operious is explicit about what is available now, what is in progress, and what depends on deployment scope.",
    intro: [
      "Enterprise buyers do not need inflated certification claims. They need a precise understanding of current controls, planned audits, healthcare deployment support, and roadmap commitments.",
      "Operious documents compliance status as part of the architecture review so procurement, security, and compliance teams can evaluate risk with the same facts.",
    ],
    sections: [
      {
        title: "Current posture",
        body: [
          "GDPR-aligned data handling is part of the product direction. HIPAA Business Associate Agreement support is available for healthcare clients where deployment scope and controls are agreed. Security disclosures are maintained separately.",
        ],
      },
      {
        title: "In progress",
        body: [
          "SOC 2 Type II audit planning is targeted for Q3 2026. ISO 27001 certification remains on the roadmap. Tenant-controlled data residency is also roadmap work and should be discussed during architecture review.",
        ],
      },
      {
        title: "Deployment-specific review",
        body: [
          "Compliance posture varies by tenant configuration, data residency needs, integrations, and regulated workflow scope. Operious treats that review as part of enterprise onboarding.",
        ],
      },
    ],
    ctas: [{ label: "Request compliance review", href: "/company/contact?topic=compliance" }],
  },
  insights: {
    eyebrow: "Insights",
    title: "Writing on governed execution and operational AI infrastructure.",
    subtitle:
      "Technical articles for leaders evaluating whether AI systems can be made accountable enough for regulated operations.",
    intro: [
      "The core question is no longer whether AI can generate useful output. It is whether an enterprise can authorize, constrain, reconstruct, and defend the decisions made around that output.",
    ],
    sections: [
      {
        title: "Architectural seriousness over feature breadth",
        body: [
          "Operious writing focuses on the primitives that matter for production operations: governance, replay, tenant isolation, event fabrics, agent authority, and multilingual execution.",
        ],
      },
    ],
    cards: insightLinks.slice(1).map((link) => ({
      title: link.label,
      body: link.description ?? "",
      href: link.href,
      meta: "Article",
    })),
  },
  articleConstitutionalGovernance: {
    eyebrow: "Insights",
    title: "Constitutional AI governance requires runtime enforcement.",
    subtitle:
      "Policy-as-prompt is a useful instruction pattern. It is not a governance system for regulated enterprise operations.",
    intro: [
      "A model can be instructed to obey policy. That does not mean policy was executed. In regulated workflows, the system must prove which rule applied, what evidence was evaluated, and why an action was permitted or denied.",
      "Operious treats constitutional governance as an executable runtime that sits between agent proposals and operational execution.",
    ],
    sections: [
      {
        title: "The prompt boundary is not enough",
        body: [
          "Prompts can be ignored, misinterpreted, or bypassed by downstream integration code. Runtime enforcement gives policy its own authority path and produces durable governance records.",
        ],
      },
      {
        title: "Admission tokens",
        body: [
          "A permitted action receives a governance admission token that binds actor, capability, subject, evidence, policy version, and decision result. Execution without that token is rejected.",
        ],
      },
      {
        title: "Why this matters",
        body: [
          "Operations leaders gain automation without turning compliance into a post-hoc explanation exercise. The system can show why it acted and why it refused to act.",
        ],
      },
    ],
    ctas: [{ label: "Explore governance", href: "/platform/governance" }],
  },
  articleReconstructibleTruth: {
    eyebrow: "Insights",
    title: "Reconstructible truth is the missing audit primitive in AI operations.",
    subtitle:
      "Logs describe activity. Reconstructible systems can replay the decision from the state and policy that existed at the time.",
    intro: [
      "Most AI systems can provide transcripts and logs. Few can prove the exact operational state, policy version, and evidence bundle that produced a decision.",
      "Operious is designed around forensic reconstruction. The event fabric is the source of organizational truth, and projections are rebuilt from it.",
    ],
    sections: [
      {
        title: "Why logs fall short",
        body: [
          "A log line can show that a decision occurred. It often cannot prove what the system knew, which policy was in force, or whether a derived view was stale.",
        ],
      },
      {
        title: "Deterministic identity",
        body: [
          "UUID5 identity helps align events, traces, workflow subjects, and replay inputs around stable facts instead of accidental runtime identifiers.",
        ],
      },
      {
        title: "The replay test",
        body: [
          "A system is trustworthy when a denied refund, escalation, approval, or communication can be reconstructed from preserved state and deterministic rules.",
        ],
      },
    ],
    ctas: [{ label: "Explore replay", href: "/platform/replay" }],
  },
  articleBeyondWrappers: {
    eyebrow: "Insights",
    title: "Beyond LLM wrappers: what makes an AI platform infrastructure.",
    subtitle:
      "Model calls are not enough. Regulated operations require substrates for authority, state, governance, and replay.",
    intro: [
      "The market is crowded with interfaces that call an LLM, connect to tools, and label the result a platform. That may be useful for internal productivity. It is not sufficient for regulated enterprise operations.",
      "Infrastructure begins when the system can constrain authority, preserve tenant boundaries, and explain execution after the fact.",
    ],
    sections: [
      {
        title: "The seven substrates",
        body: [
          "Boundary, coordination, governance, session, execution, supervisor, and arbitration layers are separate because each owns a different failure mode.",
        ],
      },
      {
        title: "Where LLMs belong",
        body: [
          "Models are appropriate for cognition, classification, summarization, and drafting. They must not own governance, execution authority, tenant boundaries, or audit truth.",
        ],
      },
      {
        title: "What buyers should ask",
        body: [
          "Ask whether the vendor can replay a decision, prove a denied action was denied by policy, and show where tenant data boundaries are enforced.",
        ],
      },
    ],
    ctas: [{ label: "Read platform overview", href: "/platform" }],
  },
  articleAuditTrailProduct: {
    eyebrow: "Insights",
    title: "The audit trail is a product feature.",
    subtitle:
      "For regulated enterprises, auditability is not cleanup work. It is part of the customer-facing operating promise.",
    intro: [
      "Operational AI systems tend to treat logs as exhaust. Regulated enterprises treat auditability as a business requirement because decisions may be challenged by customers, regulators, auditors, and internal risk teams.",
      "Operious treats operational events as the live audit spine of the product.",
    ],
    sections: [
      {
        title: "Log files versus event fabric",
        body: [
          "Logs are often optimized for debugging. An event fabric is optimized for durable reconstruction, policy attribution, and downstream projections.",
        ],
      },
      {
        title: "Auditable by design",
        body: [
          "Governance decisions, execution attempts, denials, approvals, and supervisor findings are operational facts, not optional telemetry.",
        ],
      },
      {
        title: "A buyer-visible advantage",
        body: [
          "When auditability is a product feature, compliance leaders can evaluate the system before incidents rather than assemble evidence after them.",
        ],
      },
    ],
    ctas: [{ label: "Explore trust posture", href: "/trust" }],
  },
  articleMultiLanguage: {
    eyebrow: "Insights",
    title: "Multi-language operations need governance, not translation gloss.",
    subtitle:
      "Language coverage becomes operational risk when dialect, policy, and customer intent are treated as a thin UI concern.",
    intro: [
      "Many AI operations products perform reasonably in English and common Romance-language workflows, then degrade when faced with Arabic, dialectal Arabic, mixed-script messages, and region-specific service policies.",
      "Operious treats language as part of the operational substrate: classification, grounding, policy selection, escalation, and replay must all preserve the language context that shaped the decision.",
    ],
    sections: [
      {
        title: "The Arabic-language gap",
        body: [
          "Arabic support requires more than translation. Dialect, formality, code switching, and regional service language can change the meaning of a request and the policy that applies.",
        ],
      },
      {
        title: "Language as evidence",
        body: [
          "Operious can preserve source language, translation artifacts, model confidence, and policy evidence in the event trace so supervisors can review decisions in context.",
        ],
      },
      {
        title: "Governed escalation",
        body: [
          "When language confidence is too low or region-specific policy is ambiguous, the system should escalate rather than improvise.",
        ],
      },
    ],
    ctas: [{ label: "Schedule a language operations review", href: "/company/contact?topic=multi-language" }],
  },
  pricing: {
    eyebrow: "Pricing",
    title: "Enterprise pricing aligned to operational scale.",
    subtitle:
      "Operious is priced by deployment scope, operating domain, governance requirements, and ticket volume. Specific dollar amounts are quoted after architecture review.",
    intro: [
      "Regulated operations rarely fit a public self-serve price grid. Data boundaries, compliance posture, integrations, and workflow scope materially affect implementation.",
    ],
    sections: [
      {
        title: "Foundation",
        body: [
          "For pilots and proof-of-value engagements. Custom pricing. Up to 5,000 tickets per month, one operational domain, and 60-day pilot terms.",
        ],
      },
      {
        title: "Operational",
        body: [
          "For production deployments at single-domain scale. Custom pricing. Up to 50,000 tickets per month, single tenant, full governance and audit capabilities.",
        ],
      },
      {
        title: "Enterprise",
        body: [
          "For multi-domain, multi-tenant production. Custom pricing. Unlimited volume, dedicated SLA, and custom compliance attestations.",
        ],
      },
    ],
    cards: [
      {
        title: "Foundation",
        meta: "Contact for pricing",
        body: "Pilot and proof-of-value terms for one operational domain.",
        href: "/company/contact?tier=foundation",
      },
      {
        title: "Operational",
        meta: "Contact for pricing",
        body: "Production deployment at single-domain scale with governance and audit.",
        href: "/company/contact?tier=operational",
      },
      {
        title: "Enterprise",
        meta: "Contact for pricing",
        body: "Multi-domain production with dedicated SLA and compliance review.",
        href: "/company/contact?tier=enterprise",
      },
    ],
    ctas: [{ label: "Request pricing review", href: "/company/contact?topic=pricing" }],
  },
  company: {
    eyebrow: "Company",
    title: "Operious exists to make enterprise AI operations accountable.",
    subtitle:
      "Founded in 2026 by Imad Baraja, Operious is built from the conviction that autonomy must be governed before it is scaled.",
    intro: [
      "Operious was founded in 2026 by Imad Baraja, who spent his early career inside enterprise customer operations and built Operious to address the architectural gaps he observed there.",
      "The company is organized around one belief: regulated enterprises should not have to choose between automation and accountability.",
    ],
    sections: [
      {
        title: "The architectural conviction",
        body: [
          "AI systems that touch production operations need deterministic control surfaces, tenant-owned governance, and reconstructible truth. Without those primitives, automation becomes a liability transfer mechanism.",
        ],
      },
      {
        title: "The mission",
        body: [
          "Operious builds governed execution infrastructure so operations leaders can automate Tier 1 and Tier 2 workflows without surrendering policy control or audit defensibility.",
        ],
      },
    ],
    cards: companyLinks.map((link) => ({
      title: link.label,
      body: link.description ?? "",
      href: link.href,
    })),
    ctas: [{ label: "Request enterprise access", href: "/company/contact" }],
  },
  privacy: {
    eyebrow: "Legal",
    title: "Privacy policy.",
    subtitle: "Last updated: May 2026.",
    intro: [
      "This policy describes how Operious AI, Inc. handles personal information in connection with its websites, enterprise evaluations, and governed execution services.",
    ],
    sections: [
      {
        title: "Information we process",
        body: [
          "We may process contact information, company information, usage metadata, support communications, and tenant-provided operational data when an enterprise customer authorizes that processing.",
        ],
      },
      {
        title: "Enterprise data",
        body: [
          "Customer operational data remains controlled by the customer. Processing terms, retention, residency, subprocessors, and security controls are governed by the applicable enterprise agreement and data processing addendum.",
        ],
      },
      {
        title: "Rights and contact",
        body: [
          "Privacy requests can be sent to privacy@operious.ai. Operious will respond according to applicable law and contractual obligations.",
        ],
      },
    ],
  },
  terms: {
    eyebrow: "Legal",
    title: "Terms of service.",
    subtitle: "Last updated: May 2026.",
    intro: [
      "These terms govern access to the Operious website and non-production evaluation materials unless a separate written enterprise agreement applies.",
    ],
    sections: [
      {
        title: "Evaluation use",
        body: [
          "Product information, demonstrations, and evaluation environments are provided for enterprise review. Production use requires a written agreement covering scope, security, data handling, service levels, and compliance obligations.",
        ],
      },
      {
        title: "Acceptable use",
        body: [
          "Users may not attempt to bypass tenant isolation, interfere with service operations, reverse engineer security controls, or use the service in violation of law or third-party rights.",
        ],
      },
      {
        title: "No public warranty",
        body: [
          "Website materials are provided for informational purposes. Contractual warranties, support commitments, and compliance obligations are only those stated in the applicable written agreement.",
        ],
      },
    ],
  },
  security: {
    eyebrow: "Legal",
    title: "Security disclosures.",
    subtitle: "Last updated: May 2026.",
    intro: [
      "Operious welcomes responsible security research and treats credible reports as part of maintaining trustworthy enterprise infrastructure.",
    ],
    sections: [
      {
        title: "Responsible disclosure",
        body: [
          "Security reports can be sent to security@operious.ai. Please include affected systems, reproduction steps, impact, and any relevant evidence. Avoid accessing customer data or disrupting service availability.",
        ],
      },
      {
        title: "Scope",
        body: [
          "In-scope issues include authentication defects, tenant isolation failures, credential exposure, unauthorized data access, and vulnerabilities affecting production service integrity.",
        ],
      },
      {
        title: "Operating commitments",
        body: [
          "Operious prioritizes vulnerabilities according to severity, customer impact, exploitability, and deployment scope. Enterprise customers receive security handling terms through their written agreement.",
        ],
      },
    ],
    ctas: [{ label: "Request security review", href: "/company/contact?topic=security" }],
  },
};
