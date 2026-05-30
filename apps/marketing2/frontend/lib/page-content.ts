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
  bullets?: string[];
  code?: string;
};

export type ContentCard = {
  title: string;
  body: string;
  href?: string;
  meta?: string;
  items?: string[];
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

const architectureCards: ContentCard[] = platformLinks.map((link) => ({
  title: link.label,
  body: link.description ?? "",
  href: link.href,
}));

const industryCards: ContentCard[] = industryLinks.slice(1).map((link) => ({
  title: link.label,
  body: link.description ?? "",
  href: link.href,
}));

const insightCards: ContentCard[] = insightLinks.slice(1).map((link) => ({
  title: link.label,
  body: link.description ?? "",
  href: link.href,
  meta: "Article",
}));

export const pages: Record<PageKey, PageContent> = {
  platform: {
    eyebrow: "Platform",
    title: "A deterministic multi-agent operating system for regulated operations.",
    subtitle:
      "Operious is governed execution infrastructure: a policy-bound substrate where agents coordinate work, every action is admitted before execution, and every decision can be reconstructed from tenant-owned state.",
    intro: [
      "Most enterprise AI products begin with a language model and then add dashboards, prompts, and approval buttons around it. That order is backwards for regulated operations. A system that can act on customers, cases, refunds, claims, devices, appointments, or public records must first prove that it knows who is allowed to do what, under which policy, against which evidence, and with which audit trail.",
      "Operious starts from the operating system layer. The platform separates boundary, coordination, governance, session, execution, supervisor, and arbitration responsibilities so that cognition never becomes uncontrolled authority. An LLM may propose a diagnosis, classify intent, draft a response, or retrieve relevant procedure knowledge. The substrate decides whether the proposed action is legal, records the decision, and executes only when the governance path is satisfied.",
      "This distinction matters to operations leaders because throughput without accountability only moves risk faster. Operious is built for organizations that need automation, multilingual coverage, and cost discipline, but cannot accept hallucinated policy, unverifiable case handling, or audit trails that collapse under review.",
    ],
    cards: architectureCards,
    sections: [
      {
        title: "The seven-substrate model",
        body: [
          "The platform is organized around seven operational substrates. Boundary defines tenant, channel, credential, and data limits. Coordination determines which agents may collaborate and in what order. Governance evaluates legality before execution. Session maintains the active operational context. Execution invokes tools and changes external systems only after admission. Supervisor evaluates workflow progress and quality. Arbitration resolves conflicts, deadlocks, and competing claims through deterministic rules.",
          "This model gives enterprises a vocabulary for risk. If an incident occurs, the question is not simply what did the AI say. The better question is which substrate failed, which invariant should have stopped the action, and which event record proves the system state at the time. Operious is designed so that those questions can be answered without reverse engineering a chain of ad hoc prompts and callbacks.",
        ],
      },
      {
        title: "Governance is not advisory",
        body: [
          "Operious policies execute. They do not merely suggest behavior to an agent. A proposed action carries an actor, capability, subject, target, evidence bundle, tenant context, and policy version. The governance runtime evaluates that subject against tenant-controlled policy chains and returns a permit, deny, or review outcome. Execution cannot proceed without an admission record.",
          "The default is fail-closed. Empty policy chains deny. Missing evidence denies. Ambiguous tenant context denies. This is intentionally conservative because enterprise automation should prove authorization before it touches a customer record, external system, or operational commitment.",
        ],
      },
      {
        title: "Reconstructible truth",
        body: [
          "Operious treats operational_events as the live audit spine. Decisions, approvals, denials, messages, tool invocations, supervisor findings, and projection updates are recorded as append-only facts. Derived views can be rebuilt. The event fabric remains the source of reconstruction.",
          "Deterministic UUID5 identity is used where stable identity can be derived from canonical tenant, workflow, subject, and version facts. This reduces replay ambiguity and makes it possible to connect a screen-level trace to the underlying decision and evidence chain. The aim is not just observability. The aim is forensic reconstruction with cryptographic certainty where the deployment enables cryptographic chaining and preserved input state.",
        ],
      },
      {
        title: "Tenant-controlled operating doctrine",
        body: [
          "Every deployment carries tenant-owned policies, knowledge, procedures, channels, credentials, and escalation rules. Operious provides the runtime, but the enterprise controls the constitution under which operational work is admitted. That separation is essential for regulated domains where the vendor should not silently redefine refund authority, claim handling, patient communication, dispute routing, or public-service obligations.",
          "The platform is therefore not a generic chatbot installed over an enterprise queue. It is a governed operating layer that maps tenant doctrine to executable controls, then preserves the evidence that those controls were applied.",
        ],
      },
    ],
    ctas: [
      { label: "Explore constitutional governance", href: "/platform/governance" },
      { label: "Book an Architecture Review", href: "/company/contact?topic=architecture-review" },
    ],
  },

  platformGovernance: {
    eyebrow: "Platform / Governance",
    title: "Constitutional governance is runtime enforcement.",
    subtitle:
      "Operious turns enterprise policy into executable admission control with fail-closed defaults, capability legality gates, governance tokens, and persistent denial records.",
    intro: [
      "AI vendors often describe governance as a prompt, a checklist, a system message, or a review queue. Those mechanisms can be useful, but they are not sufficient when an automated system can change operational state. A prompt cannot prove that the correct policy version was applied. A dashboard cannot guarantee that execution was impossible before approval. A review queue cannot explain denied actions that never reached a human.",
      "Operious treats governance as a constitutional runtime. Every action proposed by an agent enters a legality path before it can be executed. The path binds tenant, actor, capability, subject, evidence, policy chain, and decision result. That record becomes part of the operational event fabric, which means governance itself is auditable.",
    ],
    sections: [
      {
        title: "Policy-as-prompt is not enough",
        body: [
          "A prompt can instruct a model not to approve refunds above a threshold, not to discuss clinical advice, or not to modify a regulated account without evidence. It cannot make those actions impossible. Downstream code may still call a tool. An integration may still mutate a record. A model may still produce a plausible explanation that sounds compliant while missing a policy boundary.",
          "Operious moves the authority boundary out of the prompt. The model may propose. The governance layer admits or denies. This separation is the foundation of deterministic enterprise AI because it keeps interpretive cognition away from final execution authority.",
        ],
      },
      {
        title: "Fail-closed default",
        body: [
          "The governance runtime denies when it cannot prove permission. If a policy chain is empty, the system denies. If subject construction fails, the system denies. If evidence is missing, the system denies. If tenant context is unresolved, the system denies. The system is allowed to be conservative because a denied action is inspectable, while an unauthorized action can become operational liability.",
          "Fail-closed behavior also changes the buyer conversation. Instead of asking whether an AI assistant usually follows instructions, the enterprise can ask whether the runtime has any path to execute without policy admission. In Operious, that path is intentionally closed.",
        ],
      },
      {
        title: "Capability legality gates",
        body: [
          "Each capability is declared before it is used. A diagnostic agent may classify a charging issue. An escalation agent may route a claim to a human queue. A QA agent may evaluate response quality. A tool invocation may attempt to update a case. Each capability has a legality gate that evaluates whether this actor may perform this action against this subject under this tenant's constitution.",
          "The gate is not a user-interface permission check. It is part of the execution path. The gate receives structured facts and returns a durable governance decision. The result is stored even when the action is denied, because denials explain the boundary conditions of the operating system.",
        ],
      },
      {
        title: "Policy chains",
        body: [
          "A regulated operation rarely depends on a single rule. A refund may require warranty eligibility, customer region, product defect code, return window, fraud indicator, agent authority, and communication language. A healthcare message may require PHI scope, role authorization, communication channel, and patient consent. Operious represents these as chains of policy evaluators rather than free-form model reasoning.",
          "Policy chains make governance testable. A tenant can add a rule, version it, run deterministic checks, and inspect how it affected admission. The system can show which evaluator produced the decisive deny or permit and which evidence was present when the chain ran.",
        ],
      },
      {
        title: "Governance admission tokens",
        body: [
          "When a proposed action is permitted, the governance runtime produces an admission token. The token is not a marketing metaphor. It is a structured artifact that binds the proposed execution to the policy decision that allowed it. Execution code must present that artifact before it can call the relevant tool or mutate operational state.",
          "The token gives auditors a durable bridge between policy evaluation and action. A later review can connect the message sent, the record changed, or the workflow advanced to the exact governance decision that admitted it.",
        ],
        code: `subject = build_subject(tenant, actor, capability, target, evidence)
decision = governance.evaluate(subject, policy_chain_version)

if decision.result != "permit":
    persist_governance_failure(subject, decision)
    return deny_execution(decision.reason)

token = issue_admission_token(subject, decision)
execution.invoke(tool, token, payload)`,
      },
      {
        title: "Governance failure persistence",
        body: [
          "A denial is an operational event. Operious preserves denied proposals, failed subject construction, missing evidence, and policy-chain failures so supervisors can inspect why work stopped. This matters because regulated operations need to distinguish between the system refusing correctly and the system being blocked by incomplete configuration.",
          "Persistent failures also help operations teams harden the deployment. Repeated denials may reveal a missing policy, a channel misconfiguration, an ambiguous SOP, or a workflow that requires a human exception path. Governance therefore becomes not only a control surface, but an operating feedback loop.",
        ],
      },
      {
        title: "What leaders can rely on",
        body: [
          "The practical promise is narrow and serious. Operious does not claim that models never make mistakes. It claims that model output is not allowed to become operational execution until deterministic governance admits it. That is the difference between an AI assistant that tries to behave and infrastructure that can be defended.",
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
      "Operious is designed so a regulated enterprise can reconstruct any operational decision from deterministic identity, append-only events, policy versions, projections, and preserved tenant state.",
    intro: [
      "Traditional audit trails answer a partial question: what did the application log. Regulated enterprises need a harder answer: what did the organization know, which policy applied, who or what proposed the action, why was the action admitted or denied, and can that decision be reconstructed later without trusting memory or narrative.",
      "Operious calls this reconstructible organizational truth. It is the ability to replay an operational decision as a governed state transition, not merely to read a transcript. The architecture is built around deterministic identity, an append-only event fabric, projection bridges, and replay-safe execution semantics.",
    ],
    sections: [
      {
        title: "The audit problem in AI operations",
        body: [
          "Most AI systems can store prompts, completions, tool calls, and timestamps. That is useful, but it does not automatically prove decision state. A transcript may omit the policy version, source document version, tenant configuration, external system response, or escalation rule that shaped the outcome. When a customer, regulator, or internal risk team challenges a decision, the enterprise needs more than conversation history.",
          "Operious makes the decision record part of the operational substrate. The system records the subject evaluated, the governance decision, the evidence bundle, the agent proposal, the execution result, and supervisor findings as linked facts. Replay begins from those facts rather than from an engineer assembling log fragments.",
        ],
      },
      {
        title: "UUID5 deterministic identity",
        body: [
          "Runtime-generated identifiers are convenient for software, but they can make reconstruction ambiguous. Operious uses UUID5 deterministic identity where stable identifiers can be derived from canonical tenant, workflow, subject, version, and event facts. The same canonical input produces the same identity, which means replay can connect records without relying on accidental process state.",
          "This does not mean every object is globally predictable. It means important operational identities can be tied to normalized facts. A denied refund decision, a warranty workflow subject, a policy version, or a retrieved SOP chunk can maintain stable identity across projections and replay runs.",
        ],
      },
      {
        title: "Append-only event fabric",
        body: [
          "The operational_events fabric is not a debug log. It is the audit spine. Events are appended as decisions occur, and derived views are projections. A queue screen, dashboard metric, export, or supervisor summary may help humans work, but those views are not the canonical truth.",
          "Append-only design matters because regulated review often happens after the operational context has moved on. A customer record may have changed, a policy may have been updated, and a model may have been replaced. The event fabric preserves what happened in order, with the relevant state references needed to reconstruct the decision.",
        ],
      },
      {
        title: "Projection bridges",
        body: [
          "Enterprises still need usable screens, reports, and integrations. Operious creates projection bridges from the event fabric into operational views. The bridge pattern allows teams to work from current state without confusing that current view for the historical source of truth.",
          "If a projection is rebuilt, the underlying events remain. If a dashboard changes, the audit spine remains. If an export is required, the system can point back to the decision events that created the projected state.",
        ],
      },
      {
        title: "Byte-replay determinism",
        body: [
          "Replay-safe systems must control nondeterminism. Operious narrows nondeterministic behavior by separating model cognition from governed execution and by preserving the inputs that matter to operational authority. The goal is that the same relevant state, policy version, and evidence produce the same governance result.",
          "Where an LLM contributes interpretation, the output is treated as evidence or proposal, not as the final authority. Replay can therefore distinguish between what the model suggested and what the governance runtime admitted. That distinction is crucial when reviewing disputed decisions.",
        ],
      },
      {
        title: "Why regulators care",
        body: [
          "A regulator is rarely satisfied by the statement that an AI tool made a reasonable decision. The enterprise must explain its own operational decision. It must show policy, evidence, authorization, and process. Operious is designed to provide that chain without asking the buyer to trust opaque model behavior.",
          "For operations leadership, this changes deployment risk. Automation no longer requires surrendering reconstructibility. The enterprise can scale routine work while maintaining a defensible record of what the organization did.",
        ],
      },
      {
        title: "Operational value of replay",
        body: [
          "Replay also improves day-to-day operations. Supervisors can inspect why a case stopped, why a policy denied execution, why an escalation path was selected, or why a response was grounded in a particular document. This turns audit infrastructure into an operating tool rather than a compliance archive.",
          "The same record helps teams refine policies. If many cases deny because evidence is absent, intake can be improved. If many cases escalate because language confidence is low, the tenant can adjust review staffing or knowledge coverage. Replay therefore supports both accountability and continuous improvement.",
        ],
      },
    ],
    ctas: [
      { label: "Read the replay article", href: "/insights/reconstructible-truth" },
      { label: "Book an Architecture Review", href: "/company/contact?topic=architecture-review" },
    ],
  },

  platformAgents: {
    eyebrow: "Platform / Agents",
    title: "Multi-agent coordination with deterministic authority boundaries.",
    subtitle:
      "Operious uses specialized agents for cognition and workflow coordination while keeping governance, execution authority, and replay outside the model.",
    intro: [
      "A regulated enterprise does not need a swarm of autonomous agents improvising inside production operations. It needs bounded specialization. Each agent should do a limited job, produce structured evidence, respect tenant policy, and leave a trace that supervisors can inspect.",
      "Operious coordinates agents through a deterministic operating substrate. The language model can interpret, classify, summarize, and draft. It cannot claim authority to execute. Governance enforces legality, the supervisor runtime evaluates progress, and arbitration resolves conflicts through explicit rules.",
    ],
    sections: [
      {
        title: "Diagnostic Agent",
        body: [
          "The Diagnostic Agent inspects the current operational context and identifies the likely case path. In a hardware deployment, it may classify a charging issue, identify warranty evidence, and map symptoms to defect categories. In financial services, it may distinguish a routine service request from a dispute or fraud-adjacent ticket. In healthcare, it may route an intake message without crossing into clinical judgment.",
          "The diagnostic output is not execution. It is a structured proposal with evidence references. Governance and supervisor checks determine whether the next action may proceed.",
        ],
      },
      {
        title: "Escalation Agent",
        body: [
          "The Escalation Agent determines when work should leave the automated path. It can identify missing evidence, ambiguous policy, language confidence issues, high-risk categories, or authority limits. Its job is not to keep automation running at all costs. Its job is to protect the operating system from unsafe continuation.",
          "Escalation recommendations are recorded as events. When a case is routed to a human, the trace explains why the escalation occurred and which rule or confidence threshold triggered it.",
        ],
      },
      {
        title: "QA Agent",
        body: [
          "The QA Agent evaluates proposed responses and workflow outputs against tenant requirements. It can check whether a response is grounded in approved knowledge, whether required disclosures are present, whether language is appropriate, and whether the answer attempts to exceed policy.",
          "Quality assurance is especially important for multilingual operations. A response can be fluent while still violating local policy, tone requirements, or escalation rules. Operious treats QA as part of the governed workflow rather than as a cosmetic review step.",
        ],
      },
      {
        title: "SOP Intelligence Agent",
        body: [
          "The SOP Intelligence Agent retrieves and assembles tenant-owned procedural knowledge. It helps agents use the current version of a policy, support procedure, warranty rule, claims instruction, or compliance note. Retrieval results become evidence in the decision trace.",
          "This prevents a common AI failure mode: answering from general model memory when the enterprise has a specific procedure. Operious makes tenant knowledge the operational source, not a suggestion layered onto generic generation.",
        ],
      },
      {
        title: "Supervisor Runtime",
        body: [
          "The Supervisor Runtime observes agent work, evaluates completion, records findings, and preserves the control-plane view of the workflow. It can identify incomplete evidence, unresolved conflicts, stale projections, repeated denials, or a need for human review.",
          "The supervisor is not merely a dashboard. It is part of the runtime that keeps agent activity bounded, inspectable, and recoverable. This matters when multiple agents collaborate on the same case or when a queue contains operational work with different risk classes.",
        ],
      },
      {
        title: "Conflict and deadlock control",
        body: [
          "Multi-agent systems can fail through conflict, circular waiting, duplicate work, or inconsistent claims over the same subject. Operious uses deterministic coordination and arbitration to limit those failure modes. Agents do not simply race to act. Work is claimed, evaluated, admitted, and recorded.",
          "Structural guarantees against deadlock and conflict are part of the architectural wedge. Enterprise operations cannot depend on a set of agents that usually cooperate. They need a runtime that can prove how cooperation is constrained.",
        ],
      },
      {
        title: "LLM proposes, governance enforces",
        body: [
          "Operious is honest about the role of language models. They are useful for cognition, classification, summarization, translation assistance, and drafting. They are not the right place to store authority, tenant boundaries, or audit truth.",
          "The result is a multi-agent system where autonomy is useful because it is bounded. Agents can make operational work faster without becoming the final source of policy or execution authority.",
        ],
      },
      {
        title: "Testing the coordination layer",
        body: [
          "Agent coordination must be tested as infrastructure, not observed casually in demos. Operious workflows can be evaluated for ordering, capability legality, deadlock behavior, supervisor findings, denied actions, and replay consistency. The goal is to prove that a class of agent behavior remains inside the operating envelope.",
          "This is especially important when a workflow touches multiple domains or channels. A customer message may trigger retrieval, classification, evidence checks, policy evaluation, drafting, QA review, and escalation. Each handoff must preserve tenant context and operational identity.",
          "Production readiness should therefore include adversarial workflow tests: incomplete evidence, conflicting agent proposals, low-confidence language, stale knowledge, and unavailable channels. The system should fail closed and leave a useful trace.",
          "That is how multi-agent behavior becomes governable instead of merely impressive. The buyer should be able to inspect those tests before trusting agents with production work.",
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
    title: "Governed execution for regulated operational domains.",
    subtitle:
      "Operious is built for domains where high-volume operational work must be automated without losing policy control, tenant isolation, multilingual coverage, or audit defensibility.",
    intro: [
      "The surface details differ across industries, but the underlying operating problem is consistent. Enterprises receive large volumes of customer, patient, member, citizen, or partner requests. Those requests span multiple systems of record, rely on evolving policies, require language sensitivity, and create decisions that may later be challenged.",
      "Generic AI tools often improve response speed while weakening accountability. Operious is designed to preserve the accountability layer. Each deployment maps tenant-specific policy, procedure knowledge, authority limits, escalation rules, and data boundaries into the governed execution substrate.",
    ],
    cards: industryCards,
    sections: [
      {
        title: "Common operating pattern",
        body: [
          "A request enters through a channel. The system identifies tenant, language, domain, subject, and available evidence. Agents classify and retrieve relevant procedure knowledge. Governance evaluates whether the next action is permitted. Execution proceeds only after admission. Supervisor findings and events preserve the record.",
          "That pattern can support warranty triage, dispute handling, patient intake, insurance FNOL, SIM provisioning, shipment exceptions, and public service routing because the substrate is consistent while the tenant constitution changes by domain.",
        ],
      },
      {
        title: "What changes by industry",
        body: [
          "The policy vocabulary changes. Hardware deployments emphasize warranty language, defect categorization, replacement authority, and regional returns. Financial services emphasize dispute rules, complaint handling, retention, and escalation. Healthcare emphasizes PHI handling, role-bound access, and patient communication. Public sector deployments emphasize jurisdiction, public records, accessibility, and transparency.",
          "Operious is therefore not positioned as a horizontal chatbot. It is operational infrastructure that can be configured for regulated domains without sacrificing deterministic auditability.",
        ],
      },
      {
        title: "Evaluation criteria",
        body: [
          "A serious enterprise evaluation should ask whether the system can show the governing policy for a decision, reconstruct the state at the time, preserve tenant isolation, handle multilingual ambiguity without unsafe improvisation, and escalate when authority is unclear. Operious is built around those questions.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact" }],
  },

  industryHardware: {
    eyebrow: "Industries / Hardware",
    title: "Operious for hardware companies.",
    subtitle:
      "Governed execution for consumer electronics warranty operations, returns processing, multi-language customer support, charging issues, and defect categorization.",
    intro: [
      "Hardware support is operationally complex because every customer interaction sits between product behavior, warranty rules, regional obligations, return logistics, inventory realities, and brand trust. A customer who says a device will not charge may need troubleshooting, defect classification, replacement evaluation, safety escalation, or return instructions. The wrong automated answer can create financial leakage, safety exposure, or an inconsistent warranty precedent.",
      "Operious gives hardware companies a deterministic execution layer for Tier 1 and Tier 2 workflows. Agents can classify symptoms, retrieve approved procedures, identify likely defect categories, draft multilingual responses, and prepare escalation evidence. Governance determines whether the system may authorize a replacement, request additional proof, route to engineering, or send a particular customer message.",
    ],
    sections: [
      {
        title: "Problem statement",
        body: [
          "Consumer electronics operations are pressured by seasonal surges, product launches, regional language coverage, and fast-moving defect signals. Traditional support workflows depend on agents remembering the latest warranty policy, recognizing product-specific issues, and applying regional rules consistently. When generative AI is added without deterministic controls, it can produce confident but incorrect guidance, misstate warranty rights, or approve outcomes outside authority.",
          "Charging issues are a useful example. The same surface complaint may involve cable compatibility, firmware state, battery degradation, moisture exposure, regional adapter differences, or a known defect pattern. A support system must gather facts and categorize the issue without jumping to replacement. It also must preserve the evidence path because defect trends can matter to quality, engineering, legal, and finance teams.",
        ],
      },
      {
        title: "How Operious addresses it",
        body: [
          "Operious separates diagnosis from authorization. The Diagnostic Agent can classify symptoms, ask approved follow-up questions, and map the case to a defect taxonomy. The SOP Intelligence Agent retrieves the current troubleshooting procedure and warranty rule. The Escalation Agent routes cases involving safety, repeat defects, or missing evidence. Governance enforces replacement authority and regional return policy before execution.",
        ],
        bullets: [
          "Warranty eligibility checks with policy-version attribution.",
          "Returns processing that records why a refund, exchange, or repair path was admitted.",
          "Multi-language response drafting with escalation when confidence or policy context is insufficient.",
          "Charging issue workflows that preserve product model, accessory, firmware, and defect evidence.",
          "Defect categorization that can feed quality review without treating a support transcript as the source of truth.",
        ],
      },
      {
        title: "Compliance and governance considerations",
        body: [
          "Hardware operations may involve consumer protection rules, regional return obligations, safety reporting, warranty language, and internal approval limits. Operious lets the tenant encode these constraints as governance policy rather than relying on a model to remember them.",
          "The system is also useful for multilingual support because language is treated as operational evidence. Source language, translation context, response language, and confidence can be preserved in the trace, which helps supervisors review decisions across markets.",
        ],
      },
      {
        title: "Implementation shape",
        body: [
          "A hardware deployment usually begins with a narrow workflow family: warranty triage for a product line, returns authorization for a region, or defect classification for a high-volume support queue. Operious maps the procedure, identifies authority limits, imports approved knowledge, and configures governance checks before automation touches customer outcomes.",
          "The early value is not only faster responses. It is a cleaner operational record. Quality teams can see which defect categories are rising. Support leaders can see where policy denies automation. Finance can see which return paths are being admitted. Compliance can inspect why a customer-facing decision occurred.",
        ],
      },
      {
        title: "Example workflow walkthrough",
        body: [
          "A customer in a non-English market reports that a portable charger no longer charges a phone. Operious identifies the language, product model, purchase region, warranty period, and symptom cluster. It retrieves the approved troubleshooting script, asks for the allowed evidence, and classifies the case as possible cable incompatibility rather than immediate product failure.",
          "If the customer provides evidence that matches a known defect category, governance evaluates replacement authority. If the policy permits replacement, an admission token is issued and the return workflow proceeds. If evidence is incomplete or the defect category is safety-sensitive, the case escalates with a reconstructible record of what was known and why automation stopped.",
        ],
      },
      {
        title: "Executive outcome",
        body: [
          "For a VP of Customer Operations, the outcome is a support operation that can scale without losing policy consistency. For a quality leader, it is a cleaner signal about defects and failure modes. For compliance and legal teams, it is a defensible record of warranty and returns decisions across languages and regions.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=hardware" }],
  },

  industryFinancialServices: {
    eyebrow: "Industries / Financial Services",
    title: "Operious for financial services.",
    subtitle:
      "Deterministic triage for dispute resolution, fraud-adjacent tickets, service requests, and regulatory audit trails.",
    intro: [
      "Financial services operations move through evidence, authorization, and regulatory scrutiny. A dispute request may be routine, incomplete, fraud-adjacent, or close to complaint handling criteria. A service ticket may require identity checks, retention rules, and escalation. Automation that cannot show why it routed or communicated a decision creates risk that compounds quickly.",
      "Operious provides a governed execution layer for support and operations teams that need automation without losing regulator-grade traceability. Agents can classify, retrieve policy, identify missing documentation, draft communications, and recommend routing. Governance decides what can be executed under tenant policy.",
    ],
    sections: [
      {
        title: "Problem statement",
        body: [
          "Many financial institutions have fragmented operational stacks: case management, core banking systems, card processors, fraud tools, customer communication platforms, compliance archives, and specialist queues. Human teams often bridge those systems with undocumented judgment. Generic AI may improve summarization, but it can also blur the line between assistance and decision authority.",
          "The most sensitive category is the fraud-adjacent ticket. It may not be a confirmed fraud case, but it touches controls that require careful routing, language, and evidence preservation. A system must avoid making unsupported promises, must not bypass required checks, and must preserve a defensible audit trail.",
        ],
      },
      {
        title: "How Operious addresses it",
        body: [
          "Operious constrains the workflow through declared capabilities. The Diagnostic Agent classifies the request and identifies whether it is dispute, servicing, complaint-adjacent, or fraud-adjacent. SOP Intelligence retrieves current policy. Governance evaluates what the system may say or do. Supervisor findings preserve whether the case is complete, denied, escalated, or ready for execution.",
        ],
        bullets: [
          "Dispute intake that records evidence completeness and routing logic.",
          "Fraud-adjacent triage that escalates when risk category or authority is unclear.",
          "Regulatory audit trails tied to policy versions and decision events.",
          "Customer communications that are drafted from approved procedural knowledge.",
          "Retention-aware event histories that support later review.",
        ],
      },
      {
        title: "Compliance and governance considerations",
        body: [
          "Deployments may need to account for FINRA expectations, CFPB complaint handling, GLBA safeguards, internal model risk review, retention schedules, and organization-specific approval limits. Operious does not claim blanket certification for every financial services workflow. It provides an architecture that can encode and evidence the customer's operating policy.",
          "This honesty matters. Certification scope, data residency, system integrations, and controls must be reviewed by deployment. Operious is designed to make that review concrete rather than aspirational.",
        ],
      },
      {
        title: "Implementation shape",
        body: [
          "Financial services deployments should start with clear separation between advisory assistance and operational authority. Operious can automate classification, evidence collection, document checks, and drafting while keeping account changes, dispute advancement, complaint treatment, and fraud-adjacent escalation behind deterministic governance.",
          "The operating benefit is a queue that becomes more legible. Leaders can see why cases move, where evidence is missing, which policies generate review, and which automated paths are safe enough for production scope.",
        ],
      },
      {
        title: "Example workflow walkthrough",
        body: [
          "A customer disputes a transaction and includes partial evidence. Operious classifies the request, checks documentation requirements, retrieves the institution's dispute intake procedure, and identifies that the case cannot be advanced without a required statement. The system drafts a compliant request for missing information and records the evidence gap.",
          "If the ticket contains fraud-adjacent signals, the Escalation Agent routes it to the appropriate queue. Governance records why automated resolution was denied. A reviewer can later reconstruct the decision from the customer message, policy version, evidence state, and escalation event.",
        ],
      },
      {
        title: "Executive outcome",
        body: [
          "Operations leaders gain faster triage without turning judgment into uncontrolled automation. Compliance leaders gain policy-version evidence and denied-action records. Technology leaders gain an integration model where model output cannot directly mutate regulated systems without governance admission.",
          "The result is not a promise that every case can be automated. It is a disciplined way to decide which cases should be automated, which should be prepared for human review, and which should be denied until evidence is complete.",
        ],
      },
    ],
    ctas: [
      { label: "Schedule an architecture review", href: "/company/contact?industry=financial-services" },
    ],
  },

  industryHealthcare: {
    eyebrow: "Industries / Healthcare",
    title: "Operious for healthcare.",
    subtitle:
      "PHI-aware operational automation for patient communication, intake automation, eligibility support, and governed routing.",
    intro: [
      "Healthcare operations require a careful distinction between administrative support and clinical authority. Patient communication, intake forms, eligibility checks, appointment support, prior authorization assistance, and claims-adjacent questions all involve sensitive data and role-specific boundaries. AI that cannot enforce those boundaries should not be allowed to execute inside the workflow.",
      "Operious supports healthcare operations by separating interpretation from authority. Agents can classify requests, identify missing intake information, retrieve approved administrative procedures, and draft messages. Governance enforces PHI handling, role scope, channel permissions, and escalation requirements before any communication or state change is executed.",
    ],
    sections: [
      {
        title: "Problem statement",
        body: [
          "Healthcare teams face high message volume, staffing pressure, multilingual patient needs, and strict privacy expectations. A seemingly simple intake message can include PHI, appointment urgency, insurance information, medication references, or clinical symptoms. Generic automation may produce helpful language while crossing a boundary it does not understand.",
          "The risk is not only hallucination. The risk is unauthorized action: disclosing information through the wrong channel, answering beyond administrative scope, failing to escalate, or losing the evidence trail behind a patient communication.",
        ],
      },
      {
        title: "How Operious addresses it",
        body: [
          "Operious can treat PHI handling and role scope as governance subjects. The system evaluates whether the actor, channel, patient context, requested action, and evidence permit the next step. When policy requires human review, the automated path stops and records the reason.",
        ],
        bullets: [
          "Patient intake automation that checks completeness without inventing clinical guidance.",
          "PHI-aware communication routing with role and channel constraints.",
          "Eligibility and prior authorization support that preserves evidence and escalation records.",
          "Approved response drafting for administrative communications.",
          "Supervisor review paths for ambiguous, urgent, or clinical-adjacent messages.",
        ],
      },
      {
        title: "Compliance and governance considerations",
        body: [
          "Healthcare deployments may require HIPAA-aligned controls, Business Associate Agreement terms, minimum necessary data handling, access logging, retention requirements, and customer-specific security review. Operious supports HIPAA BAA availability for healthcare clients where deployment scope and controls are agreed.",
          "The system is intentionally conservative around clinical boundaries. Operious can support operational workflows, but it should not be configured to replace licensed clinical judgment. Governance policy can encode when a patient request must route to authorized staff.",
        ],
      },
      {
        title: "Implementation shape",
        body: [
          "A healthcare deployment should define the exact administrative workflow before automation begins. Intake completeness, appointment support, eligibility routing, and non-clinical communication are appropriate starting points because they can be governed through explicit evidence and role rules.",
          "The value is strongest when Operious reduces repetitive administrative load while preserving escalation paths for clinical, urgent, or ambiguous messages. Supervisors can review the event trace rather than reconstruct patient communication from scattered systems.",
        ],
      },
      {
        title: "Example workflow walkthrough",
        body: [
          "A patient submits an intake request in Arabic and omits insurance information. Operious identifies source language, extracts structured administrative facts, retrieves the approved intake procedure, and determines that a clarification message is allowed. It drafts a response in the appropriate language and records the policy basis for contacting the patient.",
          "If the same message includes urgent symptoms or a request for clinical advice, governance denies automated response and escalates. The trace preserves the source message, classification, policy version, denial reason, and escalation target.",
        ],
      },
      {
        title: "Executive outcome",
        body: [
          "Healthcare leaders can reduce repetitive administrative work while preserving PHI discipline and clinical boundaries. The operational value comes from safer intake, better evidence collection, and clearer escalation, not from asking a model to practice medicine.",
          "For compliance teams, the reconstructible trace is essential. It shows which communication was allowed, which information was used, and why the system routed the request to staff when automation was not appropriate.",
          "For patient experience leaders, the result is faster administrative response without losing the safeguards that make patient communication trustworthy.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=healthcare" }],
  },

  industryInsurance: {
    eyebrow: "Industries / Insurance",
    title: "Operious for insurance.",
    subtitle:
      "Governed automation for claims triage, policy questions, FNOL handling, document checks, and adjuster escalation.",
    intro: [
      "Insurance operations require timely intake and careful authority boundaries. A first notice of loss may need structured facts, policy lookup, coverage routing, document collection, severity classification, and escalation to a licensed adjuster. A generic AI answer that invents coverage language or promises an outcome can create serious risk.",
      "Operious supports insurers by making policy, evidence, and authority explicit. Agents can collect and classify information, retrieve approved procedure knowledge, and draft communications. Governance controls whether the system can send, route, deny, or escalate.",
    ],
    sections: [
      {
        title: "Problem statement",
        body: [
          "Claims and policy service teams operate across state-specific requirements, product variations, documentation needs, and customer urgency. High-volume workflows depend on consistent triage, but each case can contain facts that change authority. Automation must be fast without collapsing the difference between intake support and coverage determination.",
          "The audit trail matters because claims decisions are often challenged. The enterprise must show what information was available, what policy language was used, who had authority, and why a case was routed or escalated.",
        ],
      },
      {
        title: "How Operious addresses it",
        body: [
          "Operious keeps FNOL handling and claims triage within a governed path. The Diagnostic Agent structures facts and identifies missing documents. SOP Intelligence retrieves procedure and policy guidance. The Escalation Agent routes cases that require licensed review. Governance blocks any action that would exceed tenant-defined authority.",
        ],
        bullets: [
          "FNOL intake with structured evidence capture.",
          "Claims triage based on severity, policy type, jurisdiction, and completeness.",
          "Policy question routing that avoids unsupported coverage statements.",
          "Document completeness checks with replayable evidence.",
          "Escalation records for adjuster review and special handling.",
        ],
      },
      {
        title: "Compliance and governance considerations",
        body: [
          "Insurance deployments may need to encode state-specific rules, unfair claims practice controls, licensed adjuster boundaries, retention obligations, policy versioning, and communications approval. Operious gives the tenant a governance layer where those rules can be represented and tested.",
          "The goal is not to let AI decide coverage. The goal is to automate intake and operational coordination while preserving the authority boundaries that insurers already need to enforce.",
        ],
      },
      {
        title: "Implementation shape",
        body: [
          "Insurance deployments can begin with FNOL intake, document completeness, claim severity classification, or policyholder communication drafting. These workflows create measurable value without asking automation to make final coverage decisions.",
          "Operious helps claim leaders separate what can be automated from what must be reviewed. That separation is recorded in the event fabric, giving supervisors and compliance teams a defensible account of why the case moved to the next stage.",
        ],
      },
      {
        title: "Example workflow walkthrough",
        body: [
          "A policyholder reports a loss through a digital channel. Operious extracts the loss date, location, policy type, event category, and available documentation. It identifies missing evidence, retrieves the approved FNOL procedure, and drafts a request for the required information.",
          "If the loss category requires licensed review or crosses a jurisdictional rule, governance denies automated resolution and routes the case. The trace shows the facts, policy version, governance decision, and escalation path.",
        ],
      },
      {
        title: "Executive outcome",
        body: [
          "Claims leaders get a more consistent intake layer and better-prepared escalations. Policy and compliance leaders get a record that separates administrative assistance from coverage authority. Customer experience teams get faster communication without unsupported promises.",
          "Operious is most useful when insurers want to increase operational velocity while preserving the review boundaries that already govern claims work.",
          "That boundary is commercially important because it lets automation support adjusters rather than obscure their authority.",
          "It also gives leaders a clearer view of where claims are waiting for evidence, policy review, or specialist judgment, which is often the real source of delay, leakage, avoidable rework, customer frustration, supervisor churn, and operational cost.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=insurance" }],
  },

  industryTelecom: {
    eyebrow: "Industries / Telecommunications",
    title: "Operious for telecommunications.",
    subtitle:
      "Governed execution for service interruption tickets, billing disputes, SIM and device provisioning, and high-volume customer operations.",
    intro: [
      "Telecommunications operations combine network state, account ownership, billing systems, device catalogs, provisioning workflows, plan rules, and regulatory disclosures. Customers expect fast resolution, but many support actions can affect service access, charges, identity, or contractual obligations.",
      "Operious helps telecom teams automate Tier 1 and Tier 2 workflows while keeping account authority, customer consent, and provisioning actions under deterministic governance. Agents can diagnose, retrieve procedure knowledge, check evidence, and propose next steps. Execution is admitted only when policy permits.",
    ],
    sections: [
      {
        title: "Problem statement",
        body: [
          "A service interruption ticket may reflect an outage, device issue, SIM state, account suspension, provisioning failure, roaming condition, or local network impairment. A billing dispute may involve plan migration, promotional terms, taxes, credits, or prior communications. Generic AI can summarize these cases, but it cannot safely act without access constraints and policy controls.",
          "Telecom support also operates across languages and regions. A system must preserve language context, regulatory disclosure obligations, and account-verification requirements rather than treating every request as a generic support prompt.",
        ],
      },
      {
        title: "How Operious addresses it",
        body: [
          "Operious maps telecom workflows into governed capabilities. The Diagnostic Agent checks service and account context. SOP Intelligence retrieves the approved provisioning or billing procedure. Governance evaluates whether a SIM action, credit request, account update, or customer message is permitted. Escalation handles network, fraud-adjacent, or authority-sensitive cases.",
        ],
        bullets: [
          "Service interruption triage with outage and account context.",
          "Billing dispute intake with evidence and policy-version tracking.",
          "SIM and device provisioning support with account-ownership controls.",
          "Plan migration questions routed through approved procedure knowledge.",
          "Customer communication governed by disclosure and consent requirements.",
        ],
      },
      {
        title: "Compliance and governance considerations",
        body: [
          "Telecom deployments may involve customer identity checks, consent requirements, emergency-service disclosures, account security policy, regional telecom rules, and data retention obligations. Operious allows these constraints to be evaluated before operational execution.",
          "This is particularly important for provisioning actions. The system must not activate, deactivate, replace, or modify service based only on plausible language. It needs tenant-defined authority and evidence.",
        ],
      },
      {
        title: "Implementation shape",
        body: [
          "A telecom deployment should focus first on high-volume but policy-clear paths: outage triage, billing evidence collection, plan migration questions, SIM troubleshooting, and device provisioning support. Actions that affect account ownership or service control can remain gated by stronger review.",
          "The operating model lets teams improve response speed without weakening account security. Operious can draft, classify, and route while preserving the governance record for actions that touch billing or service state.",
        ],
      },
      {
        title: "Example workflow walkthrough",
        body: [
          "A customer reports that service stopped after a SIM swap. Operious checks account state, recent provisioning events, outage signals, device information, and the customer's verification status. It retrieves the approved troubleshooting path and identifies whether automated guidance is allowed.",
          "If account ownership is unresolved or the requested action could affect service control, governance denies execution and escalates. If the policy permits a guided troubleshooting message, the response is sent with the admission event preserved.",
        ],
      },
      {
        title: "Executive outcome",
        body: [
          "Telecom leaders gain a way to scale high-volume support while keeping service-affecting actions under control. The system can accelerate diagnosis and communication, but it does not treat provisioning authority as a model choice.",
          "The event trail is equally important for billing and service disputes. It preserves the facts, policy, and communication path that shaped the customer outcome.",
          "This gives operations and compliance teams the same record when a customer challenges a charge, outage response, or provisioning decision.",
          "It also makes repeated failure patterns visible across markets, devices, plans, and channels, which helps leaders distinguish individual tickets from systemic service issues earlier in the queue.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=telecom" }],
  },

  industryLogistics: {
    eyebrow: "Industries / Logistics",
    title: "Operious for logistics.",
    subtitle:
      "Replayable operational decisions for shipment exceptions, cross-border documentation, carrier routing, and delivery dispute resolution.",
    intro: [
      "Logistics operations are exception-driven. A shipment may be delayed by carrier handoff, customs documentation, weather, address quality, damaged goods, local delivery attempts, or contractual SLA rules. Every exception produces communication pressure and often requires coordination across systems.",
      "Operious provides a governed execution layer for shipment support and operations teams. Agents can classify exceptions, retrieve procedure knowledge, identify missing documents, draft customer updates, and recommend routing. Governance controls credits, escalations, communications, and external system changes.",
    ],
    sections: [
      {
        title: "Problem statement",
        body: [
          "Shipment exceptions often unfold across carriers, brokers, warehouses, customs systems, customer service platforms, and order management tools. Human teams spend time reconciling status and deciding which communication is safe. Generic AI can summarize the status, but it can also overpromise delivery dates, misstate customs requirements, or authorize credits outside policy.",
          "Cross-border documentation adds another layer of risk. Missing or incorrect commercial invoices, restricted goods declarations, duties, and local requirements can change the correct operational path. The system must preserve evidence and escalate when the policy is unclear.",
        ],
      },
      {
        title: "How Operious addresses it",
        body: [
          "Operious maps exceptions to governed workflows. The Diagnostic Agent classifies delay type and evidence state. SOP Intelligence retrieves the route, carrier, customs, or delivery dispute procedure. Governance evaluates whether the system may send an update, request documents, initiate rerouting, or recommend a credit. Supervisor findings preserve unresolved risks.",
        ],
        bullets: [
          "Shipment exception triage with event and carrier context.",
          "Cross-border documentation checks against approved procedures.",
          "Delivery dispute resolution with evidence preservation.",
          "Carrier SLA routing and escalation records.",
          "Customer communications that avoid unsupported commitments.",
        ],
      },
      {
        title: "Compliance and governance considerations",
        body: [
          "Logistics deployments may involve trade documentation, regional data handling, carrier contracts, customs obligations, sanctions screening processes, and customer-notification rules. Operious does not replace specialized compliance systems. It coordinates operational work while preserving the policy basis for actions taken.",
          "The event fabric is valuable because a delivery dispute may be reviewed after the package has moved, the carrier status has changed, and customer communications have accumulated. Replay gives the organization a stable account of the decision path.",
        ],
      },
      {
        title: "Implementation shape",
        body: [
          "A logistics deployment can start with exception classes that create high support load: stalled shipments, address issues, document gaps, delivery disputes, and carrier SLA questions. Operious maps the evidence required for each path and governs what the system may tell a customer or carrier.",
          "The result is a more consistent exception operation. Customers receive grounded updates, specialists receive better-prepared cases, and the organization retains the decision trail when a delivery outcome is challenged.",
        ],
      },
      {
        title: "Example workflow walkthrough",
        body: [
          "A cross-border shipment is held because documentation appears incomplete. Operious identifies the shipment, country pair, carrier status, order type, and missing document signal. It retrieves the approved documentation procedure and determines that a customer request for missing information is permitted.",
          "If the shipment involves restricted categories or the routing policy is ambiguous, governance denies automated resolution and escalates to a specialist queue. The trace preserves the carrier event, document evidence, policy version, customer message draft, and escalation decision.",
        ],
      },
      {
        title: "Executive outcome",
        body: [
          "Logistics leaders gain cleaner exception handling and more consistent customer communication. Specialists receive cases with evidence already organized, while routine updates can move faster under policy control.",
          "The audit trail matters because shipment facts change quickly. Operious preserves why a message, routing decision, document request, or escalation happened at the time it happened.",
          "That matters for carrier disputes, customer credits, customs documentation, and internal SLA review.",
          "It also gives teams a structured way to compare exception causes across lanes, regions, and carriers instead of relying on anecdotal escalation reports.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=logistics" }],
  },

  industryPublicSector: {
    eyebrow: "Industries / Public Sector",
    title: "Operious for public sector.",
    subtitle:
      "Governed handling for citizen service requests, FOIA-compatible audit logs, multi-jurisdictional compliance, and transparent operational routing.",
    intro: [
      "Public sector operations must serve citizens consistently across departments, programs, languages, eligibility rules, accessibility needs, and jurisdictions. Automation can help with volume, but only if it preserves public accountability. A system that cannot reconstruct why a request was routed, denied, or escalated is not ready for government work.",
      "Operious supports public-service operations with deterministic governance, tenant isolation, and replayable event records. Agents can classify requests, retrieve program rules, draft citizen communications, and recommend routing. Governance enforces jurisdiction, role, records, and escalation policy before execution.",
    ],
    sections: [
      {
        title: "Problem statement",
        body: [
          "Citizen service requests can cross agency lines. A single message may involve public works, benefits, permits, utilities, records access, accessibility accommodations, or emergency-adjacent concerns. Human teams often rely on local knowledge to route these requests. AI systems can improve intake, but they must not obscure how the decision was made.",
          "Public accountability changes the audit standard. FOIA-compatible logs, public records retention, jurisdictional policy, and accessible communication are not afterthoughts. They are part of the operating environment.",
        ],
      },
      {
        title: "How Operious addresses it",
        body: [
          "Operious structures citizen requests as governed workflow subjects. The Diagnostic Agent identifies request type, jurisdiction, program area, language, and evidence. SOP Intelligence retrieves the relevant procedure or public policy. Governance evaluates whether the system may route, respond, request more information, or escalate.",
        ],
        bullets: [
          "Citizen service request triage with jurisdiction-aware routing.",
          "FOIA-compatible event histories for decisions and communications.",
          "Multi-jurisdictional policy evaluation with explicit escalation paths.",
          "Language-aware drafting that preserves source context.",
          "Records-friendly event fabric for later review and export.",
        ],
      },
      {
        title: "Compliance and governance considerations",
        body: [
          "Public sector deployments may require public records retention, accessibility, procurement review, privacy controls, multi-jurisdictional compliance, and FedRAMP-aligned planning. Operious treats FedRAMP authorization as roadmap-dependent and deployment-specific, not as a current blanket claim.",
          "The architecture is designed to make those conversations concrete. Tenant boundaries, event histories, policy versions, and security controls can be reviewed before production scope is approved.",
        ],
      },
      {
        title: "Implementation shape",
        body: [
          "Public sector deployments should begin with clear service categories and jurisdiction rules. Permit intake, public works tickets, non-emergency service requests, benefit routing, and records request triage can be mapped into governed workflows before broader automation is considered.",
          "Operious helps agencies improve intake consistency while preserving public accountability. The system can show how a request was classified, which jurisdictional rule applied, why it was routed, and when human review was required.",
        ],
      },
      {
        title: "Example workflow walkthrough",
        body: [
          "A resident submits a multilingual request about a damaged public utility near a property boundary. Operious identifies the language, address, probable department, jurisdiction, and urgency. It retrieves the approved routing procedure and checks whether the system may acknowledge receipt and assign the case.",
          "If the request crosses jurisdictions or contains safety-adjacent language, governance escalates. The event trace records the source message, translation context, routing policy, admission or denial, and final assignment path.",
        ],
      },
      {
        title: "Executive outcome",
        body: [
          "Public sector leaders gain intake consistency without hiding accountability. Citizens receive clearer routing and communication, while agencies retain a record of why each request moved through a department, program, or jurisdiction.",
          "That record supports internal supervision and external accountability. When a decision is challenged, the agency can inspect policy, language context, evidence, routing, and escalation rather than relying on fragmented notes.",
          "The same architecture can support public records export and management review because the operating facts are preserved as events.",
          "For citizens, that means automation can improve responsiveness without weakening transparency, and for agencies it means review can start from preserved facts instead of recollection, email threads, spreadsheet extracts, queue screenshots, exports, or informal case notes.",
        ],
      },
    ],
    ctas: [{ label: "Schedule an architecture review", href: "/company/contact?industry=public-sector" }],
  },

  trust: {
    eyebrow: "Trust",
    title: "Security, compliance, and governance posture for regulated deployment.",
    subtitle:
      "Operious is designed around tenant isolation, encrypted credential handling, fail-closed governance, append-only auditability, and honest compliance roadmap disclosure.",
    intro: [
      "Regulated enterprises cannot evaluate an AI operations platform only by response quality. They need to understand tenant isolation, credential handling, data flow, audit reconstruction, compliance status, and failure behavior. Operious makes those questions central to the product.",
      "The trust posture begins with an architectural premise: the system should deny uncertain execution, isolate tenants by default, preserve operational events, and keep policy authority outside the language model. Security and governance are therefore part of the operating boundary, not a later procurement appendix.",
    ],
    cards: trustLinks.map((link) => ({
      title: link.label,
      body: link.description ?? "",
      href: link.href,
    })),
    sections: [
      {
        title: "Tenant isolation",
        body: [
          "Tenant data is scoped through application services and database-level isolation patterns. Policies, knowledge, credentials, channels, operational events, projected views, and workflow subjects are designed to remain tenant-bound. The tenant context is not a cosmetic filter in the interface. It is part of the access invariant.",
          "Enterprise deployments can review how tenant identifiers, row-level isolation, encryption boundaries, and service-layer checks work together. The point is to make isolation inspectable rather than assumed.",
        ],
      },
      {
        title: "Encryption and credential control",
        body: [
          "Operious is designed for encrypted credential handling using AES-256-GCM and per-tenant key derivation through HKDF where credential storage is required. Channel credentials are treated as tenant assets and should not be reused across tenant boundaries.",
          "Exact key management and residency architecture are reviewed during enterprise deployment because regulated buyers often require specific cloud, region, and operational controls.",
        ],
      },
      {
        title: "Governance fail-closed",
        body: [
          "The most important trust behavior is refusal. When governance cannot prove that an action is permitted, Operious denies execution and preserves the reason. That behavior is safer than letting a model improvise or allowing integration code to act because no one wrote a rule.",
          "Denied actions are part of the audit trail. They show where the system protected the enterprise, where configuration may need adjustment, and where human review is required.",
        ],
      },
      {
        title: "Compliance roadmap",
        body: [
          "Operious is explicit about current and planned posture. HIPAA Business Associate Agreement support is available for healthcare clients where scope and controls are agreed. SOC 2 Type II audit planning is targeted for Q3 2026. ISO 27001 certification and tenant-controlled data residency are roadmap items. Public sector authorization requirements, including FedRAMP paths, require deployment-specific review.",
        ],
      },
    ],
    ctas: [
      { label: "Read security architecture", href: "/trust/architecture" },
      { label: "Request security review", href: "/company/contact?topic=security" },
    ],
  },

  trustArchitecture: {
    eyebrow: "Trust / Architecture",
    title: "Technical security architecture for governed execution.",
    subtitle:
      "The Operious trust model combines AES-256-GCM credential encryption patterns, per-tenant key derivation, row-level tenant isolation, append-only audit events, and static checks against substrate bypass paths.",
    intro: [
      "Security architecture for enterprise AI operations must address more than transport encryption and authentication. The hard question is whether an automated system can access the wrong tenant, reuse the wrong credential, skip governance, mutate state without admission, or leave an audit trail that cannot be reconstructed.",
      "Operious answers those questions at the substrate level. The architecture binds tenant context, governance decisions, execution attempts, and event history into the normal operating path. Controls are designed to be testable, reviewable, and deployment-specific.",
    ],
    sections: [
      {
        title: "Credential encryption with tenant-derived keys",
        body: [
          "Where Operious stores channel credentials, the target design is AES-256-GCM encryption with per-tenant keys derived using HKDF. AES-256-GCM provides authenticated encryption, while HKDF supports deterministic derivation of tenant-scoped key material from approved secret inputs. The operational intent is simple: a credential for one tenant should not be usable from another tenant context.",
          "Credential handling is part of enterprise review because key custody, rotation, residency, and cloud provider controls can vary by deployment. Operious treats those choices as security architecture, not implementation trivia.",
        ],
      },
      {
        title: "Row-level tenant isolation",
        body: [
          "Tenant isolation is enforced through data modeling and service boundaries. Records that belong to a tenant carry tenant context, and service access paths are expected to resolve tenant identity before reading or writing operational state. The database layer can enforce row-level isolation patterns so accidental cross-tenant access is not merely a UI concern.",
          "This matters in a multi-agent system because agents may retrieve knowledge, inspect sessions, write events, and invoke channel adapters. Every one of those actions must carry tenant identity. A missing tenant context is a governance and security failure, not a harmless default.",
        ],
      },
      {
        title: "Append-only audit trail with cryptographic chaining",
        body: [
          "The operational event fabric is designed as an append-only audit spine. Governance decisions, execution attempts, denials, approvals, supervisor findings, and projection updates are written as facts. Where deployment controls enable cryptographic chaining, events can carry tamper-evident relationships that strengthen forensic reconstruction.",
          "The important architectural point is that auditability is not delegated to separate log files. Logs are useful for engineering operations. The event fabric is part of the product state and is used to reconstruct what the organization did.",
        ],
      },
      {
        title: "No cross-substrate bypass paths",
        body: [
          "Operious separates substrates so that cognition, governance, execution, supervision, and arbitration do not collapse into one informal code path. Static analysis and dependency audits are used to identify cross-substrate imports and bypass paths that would let execution avoid governance or tenant controls.",
          "This discipline protects the system from the most common failure of fast-moving AI products: one convenient integration path that calls a tool directly because it was easier than routing through policy. In Operious, those paths are treated as architectural violations.",
        ],
      },
      {
        title: "Execution admission",
        body: [
          "Execution code is designed to require governance admission before invoking external systems or mutating operational state. The admission record links subject, actor, capability, evidence, policy chain, and decision result. Without admission, execution should fail closed.",
          "This gives security and compliance teams a direct review object. They can ask which actions require admission, how admission is issued, how denial is recorded, and how an event connects back to execution.",
        ],
      },
      {
        title: "Deployment review",
        body: [
          "Security architecture becomes real only when it is mapped to a tenant's systems, data classes, integrations, cloud posture, and regulatory obligations. Operious architecture reviews cover channels, credentials, event retention, access roles, encryption posture, logging, data residency needs, and incident response expectations.",
        ],
      },
      {
        title: "Static verification and dependency discipline",
        body: [
          "Operious treats architectural boundaries as testable constraints. Static checks can verify that code does not import across forbidden substrate paths, that governance runtime boundaries are not bypassed, and that tenant-aware services do not quietly call lower-level utilities without context. This is not a replacement for security review, but it reduces the chance that convenience erodes the design.",
          "Dependency discipline also matters in regulated deployments. A smaller, clearer path between cognition, governance, execution, and audit makes it easier for security teams to review how data and authority move through the system.",
        ],
      },
      {
        title: "Failure handling",
        body: [
          "Security architecture must describe failure, not only success. When tenant context is missing, execution should deny. When credential resolution fails, the action should stop. When governance cannot produce admission, the workflow should preserve the denial instead of retrying through an ungoverned path.",
          "These failure records become part of the audit fabric. They help teams distinguish malicious behavior, misconfiguration, missing evidence, and ordinary operational uncertainty.",
          "Security teams can then review not only whether controls exist, but how the system behaves when those controls block work.",
          "That failure behavior is a core part of the security model, especially for systems that can coordinate actions across channels, tools, credentials, and records.",
        ],
      },
    ],
    ctas: [
      { label: "Read compliance posture", href: "/trust/compliance" },
      { label: "Request Security Review", href: "/company/contact?topic=security" },
    ],
  },

  trustCompliance: {
    eyebrow: "Trust / Compliance",
    title: "Honest compliance posture and roadmap.",
    subtitle:
      "Operious communicates what is available now, what is in progress, and what must be reviewed by deployment scope.",
    intro: [
      "Enterprise buyers respect clarity more than exaggerated claims. Compliance posture depends on product controls, deployment architecture, cloud environment, data categories, integrations, subprocessors, operating procedures, and contractual commitments. Operious documents these details during enterprise review.",
      "The current posture is built around GDPR-aligned data handling direction, tenant isolation, encryption patterns, governance fail-closed behavior, and audit reconstruction. Formal certification roadmap items are identified as roadmap items until completed.",
    ],
    sections: [
      {
        title: "Current state",
        body: [
          "Operious is designed for GDPR-aligned data handling, including data minimization, customer-controlled processing terms, and enterprise review of retention and subprocessors. HIPAA Business Associate Agreement support is available for healthcare clients where deployment scope, controls, and responsibilities are agreed in writing.",
          "Security disclosures are maintained through the legal security page. Enterprise customers can request security architecture review, data flow documentation, and deployment-specific control mapping as part of onboarding.",
        ],
      },
      {
        title: "In progress",
        body: [
          "SOC 2 Type II audit planning is targeted for Q3 2026. This is a planning target, not a completed certification claim. ISO 27001 certification is on the roadmap. Tenant-controlled data residency is also on the roadmap and should be discussed during architecture review when regional requirements matter.",
          "Operious will not present roadmap controls as completed attestations. Procurement and compliance teams should evaluate current controls and planned milestones separately.",
        ],
      },
      {
        title: "Healthcare deployments",
        body: [
          "Healthcare clients can evaluate HIPAA BAA availability as part of enterprise contracting. Operious still requires scope review because PHI handling, user roles, integrations, audit exports, and support procedures determine the practical control environment.",
        ],
      },
      {
        title: "Public sector deployments",
        body: [
          "Public sector requirements may include FOIA-compatible records, accessibility, procurement controls, public cloud requirements, and FedRAMP pathways. FedRAMP-related work is roadmap-dependent and must be evaluated by deployment scope. Operious does not claim authorization before it exists.",
        ],
      },
      {
        title: "What to expect in review",
        body: [
          "An enterprise review should cover data categories, retention, access roles, tenant isolation, encryption, event export, incident response, subprocessors, residency, support access, and workflow-specific regulatory obligations. Operious is built to make those questions concrete and traceable.",
        ],
      },
      {
        title: "Data residency roadmap",
        body: [
          "Tenant-controlled data residency is on the roadmap because regulated buyers often need region-specific processing and storage commitments. The current review process should identify residency requirements early so architecture, subprocessors, support access, and export paths can be evaluated honestly.",
          "Operious will not imply that all residency models are already available. Where residency is a requirement, the deployment should proceed only when the agreed operating model satisfies the buyer's legal and security review.",
        ],
      },
      {
        title: "Compliance evidence",
        body: [
          "Compliance review is strongest when evidence is generated by normal product operation. Governance decisions, denied actions, admission records, tenant-scoped events, and audit exports can help enterprise teams evaluate whether the controls operate continuously rather than existing only as documentation.",
          "As roadmap certifications mature, Operious will connect formal attestations to the architecture buyers can inspect today. The near-term promise is clarity about current controls and precision about what remains in progress.",
          "This distinction protects both sides of the enterprise review. Buyers see the current operating facts, and Operious avoids implying that planned certifications are already complete.",
          "The result is a compliance conversation grounded in evidence instead of broad claims.",
        ],
      },
      {
        title: "Roadmap discipline",
        body: [
          "Roadmap discipline is part of trust. SOC 2 Type II, ISO 27001, data residency controls, and public sector authorization paths should be discussed with dates, dependencies, and current limits. Operious marks these items clearly so buyers can make informed decisions.",
          "When a control is not yet certified, the right answer is to say so and explain the path. Enterprise buyers can work with roadmap clarity. They should not be asked to rely on inflated claims.",
        ],
      },
    ],
    ctas: [{ label: "Request compliance review", href: "/company/contact?topic=compliance" }],
  },

  insights: {
    eyebrow: "Insights",
    title: "Technical writing on governed AI operations.",
    subtitle:
      "Articles for operations, compliance, security, and technology leaders evaluating whether AI can be made accountable enough for regulated enterprise work.",
    intro: [
      "The central enterprise AI question has changed. It is not whether models can produce useful language. They can. The question is whether an organization can authorize, constrain, reconstruct, and defend the decisions made around that language.",
      "Operious writing focuses on architectural primitives: constitutional governance, reconstructible truth, tenant isolation, append-only event fabrics, bounded agents, multilingual operations, and the difference between a model wrapper and an operating substrate.",
    ],
    cards: insightCards,
    sections: [
      {
        title: "What these articles are for",
        body: [
          "These essays are written for enterprise teams that have already seen the first wave of AI tooling and are asking harder questions. They want automation, but they also want policy control, regulator-facing evidence, language coverage, and a deployment model that does not turn every exception into a trust exercise.",
        ],
      },
      {
        title: "A consistent thesis",
        body: [
          "AI is valuable in regulated operations when it is placed inside deterministic infrastructure. Models should interpret, retrieve, classify, summarize, and draft. Governance should enforce. Execution should require admission. Audit truth should live in an event fabric. Tenant policy should remain tenant controlled.",
        ],
      },
    ],
  },

  articleConstitutionalGovernance: {
    eyebrow: "Insights",
    title: "Why regulated AI systems need constitutional governance.",
    subtitle:
      "The difference between policy-as-prompt and policy-as-runtime-enforcement is the difference between an assistant that tries to behave and infrastructure that can be audited.",
    intro: [
      "Every regulated enterprise already has a constitution, even if it is not written in one place. It appears in refund authority, complaint handling rules, patient communication limits, insurance adjuster boundaries, fraud escalation policy, data retention obligations, public records rules, and approval chains. The question is whether an AI system can execute under that constitution or merely be reminded that the constitution exists.",
      "Most AI systems choose reminder. They place policy in prompts, instructions, guidelines, or human review queues. Operious chooses runtime enforcement. Policy becomes an admission layer between agent cognition and operational execution.",
    ],
    sections: [
      {
        title: "The policy-as-prompt failure",
        body: [
          "Policy-as-prompt is attractive because it is fast. A team can write a system message that says do not approve refunds above a threshold, do not disclose PHI, do not make coverage determinations, or do not provide regulatory advice. The model may follow that instruction many times. It may even follow it most of the time.",
          "But regulated operations are not governed by most of the time. A prompt does not make an unauthorized tool call impossible. It does not prove which policy version was applied. It does not bind the actor, customer, evidence, and target system into a durable record. It does not explain why an action was denied before execution.",
        ],
      },
      {
        title: "Runtime enforcement",
        body: [
          "Runtime enforcement means policy has its own execution path. An agent proposes an action. The system builds a governance subject. The policy chain evaluates the subject. The result is permit, deny, or review. Execution code cannot proceed unless a permit creates an admission token.",
          "This architecture moves the enterprise from trust the prompt to inspect the control plane. Compliance teams can ask what the governance subject contained, which evaluator ran, what evidence was available, what policy version applied, and where the decision was stored.",
        ],
      },
      {
        title: "The subject of governance",
        body: [
          "A governance subject is the structured object being evaluated. It includes tenant, actor, role, capability, workflow, target, requested action, evidence, channel, language context, policy version, and any domain-specific facts. In hardware support, the subject may include warranty state and defect category. In healthcare, it may include PHI scope and role authorization. In public sector workflows, it may include jurisdiction and public records requirements.",
          "This structure is what separates governance from vague safety language. A policy evaluator can inspect the subject and make a deterministic decision. A later replay can reconstruct why that decision occurred.",
        ],
      },
      {
        title: "Admission tokens",
        body: [
          "An admission token binds a permitted action to the governance decision that allowed it. It is issued only after the policy chain returns permit. Tool execution requires the token. If the token is missing, expired, mismatched, or tied to a different subject, execution fails.",
          "The token is useful because it creates a durable bridge between policy and action. The enterprise can show that the outbound message, case update, refund request, routing decision, or external tool invocation had an authorizing governance event.",
        ],
        code: `subject = {
    tenant_id,
    actor_id,
    capability: "send_customer_message",
    target: case_id,
    evidence: evidence_bundle_id,
    policy_version: "warranty-response-v12"
}

decision = governance.evaluate(subject)

if decision.result == "permit":
    token = governance.issue_admission_token(subject, decision)
    execution.send_message(token, payload)
else:
    events.append("governance_denied", subject, decision.reason)`,
      },
      {
        title: "Fail-closed is the enterprise default",
        body: [
          "Fail-open systems assume action is allowed unless a rule blocks it. That model is dangerous in regulated operations because missing policy becomes permission. Operious takes the opposite stance. Empty policy chains deny. Missing tenant context denies. Missing evidence denies. Ambiguity denies or routes to review.",
          "This default can feel strict, but strictness is the point. A denied action can be reviewed, corrected, and configured. An unauthorized action may become a customer promise, compliance breach, incorrect financial outcome, or public accountability problem.",
        ],
      },
      {
        title: "Governance failure as evidence",
        body: [
          "Denied actions should not disappear. They reveal how the operating system protected the enterprise and where the deployment may need refinement. If a workflow repeatedly fails because evidence is missing, the intake process may need a better collection step. If a policy denies too often, the tenant may need an approved exception path.",
          "Operious records governance failures as first-class events. This makes refusal measurable without turning refusal into a silent runtime error.",
        ],
      },
      {
        title: "Human review is part of the constitution",
        body: [
          "Constitutional governance does not eliminate people. It clarifies when people are required. Some actions should always require human review. Others should require review only when evidence is incomplete, language confidence is low, policy is ambiguous, or authority limits are reached.",
          "The important distinction is that the system should know why it escalated. Human review should be an admitted path with evidence, not a panic button after the model becomes uncertain.",
        ],
      },
      {
        title: "Policy versioning and change control",
        body: [
          "Regulated operations do not have one permanent policy. Warranty rules change. Complaint procedures change. Healthcare communication rules change. Public-sector routing instructions change. A governed AI system must know which version was active when an action was admitted or denied.",
          "Operious treats policy versioning as part of the governance record. When a tenant updates a policy chain, the new version can be tested and later distinguished from prior decisions. This prevents a common audit failure where the organization can show today's rule but cannot prove which rule controlled yesterday's decision.",
        ],
      },
      {
        title: "Governance as an audit surface",
        body: [
          "A mature governance layer creates an audit surface that compliance teams can inspect directly. They can review denied actions, admitted actions, policy-chain outcomes, evidence gaps, escalation triggers, and execution tokens. They do not have to infer governance from a transcript.",
          "That audit surface also gives operations leaders a management tool. If a workflow produces many denials, the organization can decide whether the policy is too strict, evidence collection is weak, or automation is being asked to do work that should remain human-led.",
        ],
      },
      {
        title: "The operational constitution must be tenant-owned",
        body: [
          "A vendor should not silently own the rules that define a regulated enterprise's operational behavior. The tenant must control refund authority, escalation thresholds, role permissions, communication templates, evidence requirements, and domain-specific exceptions. Otherwise the AI system becomes an external policy authority rather than infrastructure.",
          "Operious provides the runtime and control plane, but the operating constitution is tenant-owned. That is why governance is configured, versioned, tested, and inspected as part of deployment rather than hidden inside model behavior.",
        ],
      },
      {
        title: "Why this is different from guardrails",
        body: [
          "Guardrails often describe output filters, topic restrictions, or post-generation checks. Those are useful, but they are not equivalent to constitutional governance. A guardrail can catch unsafe text. It may not stop an unauthorized tool call, preserve a denial record, or prove which business policy admitted an action.",
          "Constitutional governance reaches deeper into the execution path. It is concerned with what the organization is allowed to do, not only what the model is allowed to say.",
        ],
      },
      {
        title: "Why this changes procurement",
        body: [
          "Operations leaders should ask vendors whether policy lives in prompts or runtime enforcement. They should ask whether execution can occur without admission. They should ask whether denied actions are recorded. They should ask whether a decision can be replayed against the policy version that existed at the time.",
          "These questions separate AI productivity tools from governed execution infrastructure. Operious is built for buyers who need that separation before they put automation inside regulated workflows.",
          "The procurement test is not how impressive the demo appears when the model is cooperating. The test is what the system does when evidence is missing, the policy is silent, the customer language is ambiguous, or the proposed action would exceed authority. Constitutional governance should make those cases inspectable and boring.",
        ],
      },
    ],
    ctas: [{ label: "Explore governance", href: "/platform/governance" }],
  },

  articleReconstructibleTruth: {
    eyebrow: "Insights",
    title: "Reconstructible truth is the audit primitive AI operations are missing.",
    subtitle:
      "Most AI vendors can show conversation history. Regulated enterprises need to replay the decision from state, evidence, policy, and execution records.",
    intro: [
      "The auditability problem in AI operations is often misunderstood. Storing prompts and completions is useful, but it is not the same as reconstructing an organizational decision. A prompt transcript may show what the model saw. It may not show which policy version was active, which system-of-record facts were available, which evidence was missing, why execution was denied, or whether a projection was stale.",
      "Operious is built around reconstructible organizational truth. A decision should be replayable as an event-backed state transition. The enterprise should be able to answer what happened, why it happened, what the system knew, what policy applied, and whether the same inputs would produce the same governance result.",
    ],
    sections: [
      {
        title: "The limits of ordinary logs",
        body: [
          "Logs are usually designed for engineering operations. They help teams debug latency, failures, exceptions, and infrastructure behavior. They are not usually designed to become the durable source of operational truth. They may be sampled, overwritten, unstructured, separated across systems, or missing the business context a regulator cares about.",
          "In AI systems, the problem is worse because the model output can sound like an explanation. A confident rationale generated after the fact is not the same as evidence. An enterprise needs the actual state and policy path that produced the action.",
        ],
      },
      {
        title: "Why most vendors cannot reconstruct decisions",
        body: [
          "Many AI platforms are wrappers around model calls and tool integrations. They can show the prompt, the completion, and perhaps the tool result. They often cannot show the tenant policy version, deterministic subject identity, evidence bundle, governance denial, admission token, supervisor finding, and projection update as a connected chain.",
          "They also struggle when state changes after the decision. A customer record may be updated, a policy document may be revised, a model may be replaced, or a support queue may be reorganized. If the system did not preserve the decision inputs, later review becomes a narrative exercise.",
        ],
      },
      {
        title: "UUID5 deterministic identity",
        body: [
          "Deterministic identity helps make replay possible. UUID5 creates identifiers from a namespace and a name. In Operious, stable operational facts can become the basis for stable identities: tenant, workflow, subject, version, event type, and canonical business keys. This reduces ambiguity when reconstructing a decision across projections and traces.",
          "A deterministic identifier is not a full audit system by itself. It is a useful primitive. It lets the event fabric, governance records, supervisor findings, and derived views agree about what object they are describing.",
        ],
      },
      {
        title: "The event fabric as audit spine",
        body: [
          "Operious treats operational_events as the live audit spine. Events are appended for governance evaluation, denied proposals, admission tokens, execution attempts, tool results, supervisor findings, escalation, and projection updates. Derived views are useful, but the event fabric is what makes reconstruction possible.",
          "This is different from logging because events are part of the product's operational model. A decision is not complete until its governance and execution facts are recorded. Auditability is therefore built into normal work rather than assembled only after an incident.",
        ],
      },
      {
        title: "Worked example: denied refund",
        body: [
          "Consider a customer requesting a refund for a device outside the standard return window. The model may summarize the request and identify a possible exception. Operious builds a governance subject with tenant, customer region, product, purchase date, warranty status, defect category, requested action, agent capability, and policy version.",
          "The policy chain evaluates the subject. The warranty rule permits troubleshooting and replacement review for certain defects but denies automated refund outside the window unless a supervisor exception exists. No exception exists. Governance returns deny. The denial event records policy version, evidence, reason, and subject identity. The Escalation Agent routes the case for human review if the defect category requires it.",
          "Months later, the customer challenges the denial. The enterprise can replay the case. It can show the source message, product facts, warranty state, policy version, denied refund decision, allowed next steps, and escalation path. The explanation does not depend on model memory or a freshly generated rationale.",
        ],
      },
      {
        title: "Replay as a trust signal",
        body: [
          "The replay test is simple: can the vendor reconstruct a decision from preserved inputs and deterministic rules. If the answer is no, the buyer is being asked to trust a black box. If the answer is yes, the buyer can examine the operating substrate.",
          "This is why replay matters before deployment, not only after an incident. It is a trust signal for procurement, compliance, security, operations, and legal teams.",
        ],
      },
      {
        title: "Model output versus organizational decision",
        body: [
          "A model output is a generated artifact. An organizational decision is an authorized state transition made under enterprise policy. Operious keeps those categories separate. The model may provide interpretation. Governance determines whether the organization may act.",
          "This separation allows enterprises to use LLMs where they are strong without handing them the authority to become the final record of truth.",
        ],
      },
      {
        title: "Projection drift and replay",
        body: [
          "Derived views are useful until they drift from the facts that created them. A queue dashboard may show the current owner, status, and next step, but it may not preserve why that state was reached. If the projection changes later, an ordinary audit trail can lose the path.",
          "Operious treats projections as rebuildable views over events. Replay does not depend on the current dashboard. It depends on preserved events, deterministic identities, and policy records that describe how the state changed.",
        ],
      },
      {
        title: "Evidence custody",
        body: [
          "AI auditability also requires evidence custody. If a model summarized a document, which version of the document was used. If a policy was retrieved, which chunk and version were presented. If a customer message was translated, was the source language preserved. These details determine whether a decision can be defended.",
          "Operious records evidence references as part of the decision path. That makes the evidence inspectable without treating a generated summary as the only artifact that matters.",
        ],
      },
      {
        title: "Cryptographic certainty and practical deployment",
        body: [
          "Cryptographic certainty does not mean every enterprise review needs a blockchain or a public ledger. It means the system can preserve event identity, ordering, hashes or chained references where configured, and enough input state to detect tampering or inconsistency. The deployment should make the chosen guarantees explicit.",
          "Operious is designed so stronger cryptographic chaining can reinforce the event fabric without changing the basic operating principle: decisions are reconstructed from preserved state and deterministic governance, not from post-hoc narration.",
        ],
      },
      {
        title: "Replay changes incident response",
        body: [
          "When an incident occurs, teams often lose time collecting screenshots, logs, chat transcripts, system records, and human recollections. Replay changes the starting point. The organization can begin with the decision subject, the event sequence, the policy version, and the execution admission or denial.",
          "That does not remove the need for investigation. It gives the investigation a coherent factual base. For regulated operations, that base is the difference between a disciplined response and a scramble.",
        ],
      },
      {
        title: "What buyers should require",
        body: [
          "Buyers should require event-backed decisions, policy-version attribution, tenant-scoped identity, denied-action persistence, replayable projections, and clear distinction between model proposal and execution. These are not decorative features. They are the controls that let AI operations survive regulatory and internal scrutiny.",
          "They should also require a practical replay exercise before production. Select a denied case, an escalated case, and an admitted case. Ask the vendor to reconstruct each one from preserved state. The answer will reveal whether auditability is architecture or aspiration.",
        ],
      },
    ],
    ctas: [{ label: "Explore replay", href: "/platform/replay" }],
  },

  articleBeyondWrappers: {
    eyebrow: "Insights",
    title: "Beyond LLM wrappers: what separates infrastructure from interfaces.",
    subtitle:
      "An AI platform for regulated operations must provide authority, state, governance, execution, supervision, arbitration, and replay. A model call with tools is not enough.",
    intro: [
      "The AI software market is full of products that call a model, connect to tools, and describe themselves as platforms. Some are valuable. Many improve productivity. But regulated enterprise operations require more than a helpful interface over an LLM.",
      "The distinction is architectural. A wrapper treats the model as the center and adds operational behavior around it. Infrastructure treats the operating system as the center and places the model inside bounded roles. Operious is built for the second category.",
    ],
    sections: [
      {
        title: "What a wrapper usually contains",
        body: [
          "A wrapper often has a prompt, model call, retrieval layer, tool registry, workflow canvas, and chat interface. It may also offer approval buttons or logging. These features can be useful for internal tasks, but they do not automatically create deterministic governance, tenant-controlled execution, or forensic reconstruction.",
          "The wrapper pattern becomes risky when it enters production operations. The system may call tools directly, rely on prompt instructions for policy, treat logs as audit trails, or store tenant-specific authority in application code that was not designed for regulated review.",
        ],
      },
      {
        title: "The seven substrates of an operating system",
        body: [
          "An actual multi-agent operating system needs distinct substrates. Boundary defines tenant, channel, and credential limits. Coordination manages agent collaboration. Governance enforces legality. Session maintains context. Execution invokes systems only after admission. Supervisor evaluates workflow integrity. Arbitration resolves conflict and deadlock.",
          "These substrates exist because they protect different failure modes. Collapsing them into one agent loop makes demos easier and production review harder.",
        ],
      },
      {
        title: "Where LLMs are appropriate",
        body: [
          "LLMs are useful for cognition. They can classify messages, summarize evidence, draft responses, translate with review, extract structured facts, retrieve relevant knowledge, and propose next actions. These capabilities can materially improve operational throughput when they are placed inside the right control plane.",
          "Operious uses language models in those roles. It does not pretend they are useless. It also does not confuse usefulness with authority.",
        ],
      },
      {
        title: "Where LLMs must not have authority",
        body: [
          "Models should not own governance. They should not decide tenant boundaries. They should not become the source of audit truth. They should not execute state changes without deterministic admission. They should not silently redefine policy because a prompt was phrased differently.",
          "Authority belongs in runtime controls that can be tested, versioned, replayed, and inspected. This is the central difference between Operious and a wrapper architecture.",
        ],
      },
      {
        title: "Wrapper failure modes",
        body: [
          "Wrapper systems fail in predictable ways. They add a tool because a customer wants an integration, then call it directly from an agent loop. They add policy text to a prompt, then cannot prove the rule ran. They add logs, then discover the logs do not contain the evidence needed for regulated review. They add approval buttons, then still allow unsupported draft language to reach a customer.",
          "These failures are not signs that the teams are careless. They are signs that the architecture began with the wrong center of gravity. A model-centric system keeps rediscovering enterprise controls after the fact.",
        ],
      },
      {
        title: "Integration truth",
        body: [
          "Enterprise integrations are where the difference becomes visible. Reading a case is not the same as modifying a case. Drafting a message is not the same as sending it. Suggesting a refund is not the same as authorizing it. Infrastructure must distinguish these actions and govern each one.",
          "Operious treats integration actions as capabilities with legality gates. This lets the tenant decide which actions are read-only, which require review, which can be admitted automatically, and which must never be automated.",
        ],
      },
      {
        title: "Tenant isolation as infrastructure",
        body: [
          "Wrappers often treat tenant configuration as product settings. Infrastructure treats tenant context as a security and governance invariant. Every retrieval, policy decision, credential use, event write, and execution attempt must carry tenant scope.",
          "This matters because regulated enterprises need to know not only that data is logically separated, but that the system has no ordinary path to cross tenant boundaries during agent work.",
        ],
      },
      {
        title: "Auditability as infrastructure",
        body: [
          "A wrapper may log what happened. Infrastructure models what happened as product state. Operious uses an append-only event fabric so governance, execution, denial, escalation, and supervisor findings become reconstructible facts.",
          "The difference appears during review. Logs require interpretation. Event-backed reconstruction can show the decision path.",
        ],
      },
      {
        title: "Why breadth can mislead buyers",
        body: [
          "Feature breadth is easy to market: more connectors, more agents, more templates, more dashboards. Architectural seriousness is harder to demonstrate but more important for regulated operations. Buyers should ask what happens when the model is wrong, policy is missing, evidence is incomplete, language confidence is low, or two agents conflict.",
          "Operious is intentionally positioned on architectural seriousness. The wedge is AI automation plus deterministic auditability plus tenant-controlled governance in the same system.",
        ],
      },
      {
        title: "Operational onboarding",
        body: [
          "Infrastructure also changes onboarding. A wrapper onboarding process asks for prompts, tools, and example conversations. A governed operating system asks for policy chains, evidence requirements, authority limits, escalation paths, tenant boundaries, knowledge versions, and replay expectations.",
          "That process may feel more rigorous, but it produces a safer production system. The buyer is not merely configuring a model. The buyer is defining an executable operating doctrine.",
        ],
      },
      {
        title: "Architecture as procurement evidence",
        body: [
          "Procurement teams often receive polished demos and broad claims. Architecture gives them something firmer to evaluate. If a vendor can describe boundaries, governance admission, replay, tenant isolation, and denial persistence, the buyer can map those primitives to risk.",
          "This is why Operious favors architectural seriousness over feature breadth. Features can be added. A missing control plane is much harder to retrofit after an AI product is already embedded in operations.",
        ],
      },
      {
        title: "Infrastructure has operational memory",
        body: [
          "A wrapper often treats each interaction as the center of the product. Infrastructure remembers the organization. It knows the tenant, policy versions, workflow identity, event history, supervisor findings, and projected state. This memory is structured, not merely conversational.",
          "Operational memory matters because enterprise work is rarely one-turn. A customer may return with new evidence, a claim may move across teams, a shipment may change status, and a patient intake may require follow-up. Infrastructure keeps those transitions governed.",
        ],
      },
      {
        title: "The cost of retrofitting seriousness",
        body: [
          "Teams sometimes believe they can start with a wrapper and add governance later. That is possible in narrow cases, but it is expensive when execution paths, data models, and integrations were not built for admission control or replay. The hardest controls are the ones that must exist before an action happens.",
          "Operious starts with those controls because regulated operations cannot depend on future refactors for present accountability.",
        ],
      },
      {
        title: "The buyer test",
        body: [
          "Ask a vendor to replay a denied action. Ask what prevents tool execution without governance admission. Ask how tenant credentials are scoped. Ask whether empty policy chains allow or deny. Ask whether the audit trail is a product state or a log export. The answers will reveal whether the system is infrastructure or an interface.",
          "The enterprise does not need a vendor to promise seriousness. It needs the architecture to demonstrate it. Operious is built so that demonstration can happen at the level of policy, event history, tenant boundary, and execution path.",
          "That demonstration is the point at which AI becomes suitable for real operational ownership, because the buyer can see the control plane before trusting the interface.",
        ],
      },
    ],
    ctas: [{ label: "Read platform overview", href: "/platform" }],
  },

  articleAuditTrailProduct: {
    eyebrow: "Insights",
    title: "For regulated enterprises, the audit trail is a product feature.",
    subtitle:
      "Auditability is not a compliance afterthought. It is part of the operational promise a governed AI system makes to its buyers.",
    intro: [
      "Many software teams treat audit trails as artifacts for compliance teams to request later. The product works, users get value, and logs are retained somewhere in case an auditor asks. That model is not enough for AI operations in regulated enterprises.",
      "When an AI system participates in customer, patient, member, citizen, or partner workflows, the audit trail is part of the product. It is how the enterprise proves that automation followed policy, preserved tenant boundaries, escalated correctly, and refused unsafe execution.",
    ],
    sections: [
      {
        title: "The operational promise",
        body: [
          "A regulated operations platform promises more than speed. It promises that work is handled under policy. If the system cannot show the policy path, then the promise is incomplete. Customers, regulators, auditors, and internal risk teams may all ask why a decision occurred.",
          "Operious treats that question as a product requirement. The system is designed so every admitted or denied action can be connected to evidence, policy, actor, tenant, and execution result.",
        ],
      },
      {
        title: "Log files are not enough",
        body: [
          "Log files are built for debugging. They help engineers understand exceptions, latency, infrastructure events, and runtime behavior. They may be noisy, incomplete, sampled, or difficult to connect to business objects. A log line saying a message was sent does not necessarily prove the policy that allowed it.",
          "An event fabric is different. It models operational facts as durable product state. Governance decisions, execution attempts, denials, admissions, supervisor findings, and projection changes become linked events that can be reconstructed.",
        ],
      },
      {
        title: "The operational_events fabric",
        body: [
          "In Operious, operational_events is the live audit spine. It is where the system records what happened in the language of the operating domain. A denial is an event. An admission token is an event. A supervisor finding is an event. A projection update is derived from events.",
          "This design lets the enterprise move from after-the-fact explanation to built-in accountability. The audit trail is present because the product cannot operate correctly without it.",
        ],
      },
      {
        title: "Auditability changes product design",
        body: [
          "When auditability is a product feature, designers and engineers make different choices. Buttons need meaningful destinations. Empty states must explain real integration status. Actions must carry identifiers. Policy versions must be visible. Export paths must preserve evidence. Denied actions must be inspectable.",
          "These choices may feel operationally strict, but they create trust. A buyer can see that the interface is not hiding the control plane.",
        ],
      },
      {
        title: "The audit trail helps operations too",
        body: [
          "Audit trails are not only for external review. They help supervisors understand why work stopped, which policies create friction, where evidence collection fails, and which cases require human expertise. A denied event can be a useful operational signal.",
          "This is why Operious treats denials and failures as data, not as exceptions to suppress. The system should show when governance is protecting the organization and when configuration needs improvement.",
        ],
      },
      {
        title: "Designing for auditors before incidents",
        body: [
          "The worst time to design an audit trail is after a disputed decision. By then, state has changed, people have moved on, policy may have been revised, and logs may not contain the required context. Regulated enterprises need audit design before automation goes live.",
          "Operious builds the audit path into normal workflow execution. The event fabric captures decisions as they happen, which means later review starts from preserved facts rather than reconstructed memory.",
        ],
      },
      {
        title: "Customer experience and auditability",
        body: [
          "Auditability also improves customer experience. When a customer asks why a request was denied or escalated, the organization can answer with a consistent explanation tied to policy and evidence. Without that record, frontline teams often improvise explanations that create more inconsistency.",
          "A governed audit trail therefore supports both compliance and trust. It lets the enterprise speak clearly about its own decision.",
        ],
      },
      {
        title: "Regulated buyer expectations",
        body: [
          "A Chief Compliance Officer wants to know whether policy can be proven. A VP of Customer Operations wants to know whether automation can scale without uncontrolled exceptions. A CTO wants to know whether the system has real tenant boundaries. A Head of Customer Experience wants consistent multilingual responses. The event fabric supports all of these concerns.",
        ],
      },
      {
        title: "From compliance cost to product advantage",
        body: [
          "Treating auditability as a product feature changes the enterprise sale. Instead of presenting logs as a compliance concession, the vendor can show audit reconstruction as a reason to adopt. The buyer gets automation and a stronger operating record.",
          "Operious is built around that advantage. The audit trail is not bolted on because the audit trail is part of the governed execution model.",
        ],
      },
      {
        title: "Exportability and evidence packaging",
        body: [
          "An audit trail becomes more valuable when it can be exported and packaged for the teams that need it. Compliance may need a policy-centered view. Operations may need queue and escalation evidence. Security may need tenant and credential access context. Legal may need a chronological record of customer communications and decisions.",
          "Because Operious models events as product state, the same fabric can support multiple review views without inventing separate sources of truth.",
        ],
      },
      {
        title: "The management signal",
        body: [
          "A live audit spine also creates management signal. It shows which policies stop execution, which workflows depend on human review, which language contexts create uncertainty, and which knowledge documents are frequently used. These are operational insights, not just compliance artifacts.",
          "That is why the audit trail should be treated as a product feature. It helps the enterprise operate better while making the system more defensible.",
        ],
      },
      {
        title: "Designing the user interface around audit truth",
        body: [
          "If auditability is a product feature, the interface should make audit truth visible. Operators should see when an action is pending governance, why a denial occurred, which evidence is missing, and what can be replayed. Supervisors should not need a separate forensic tool for ordinary review.",
          "This design principle affects every button and empty state. A disabled or unavailable action should explain the real integration or governance condition. A successful action should lead to a traceable outcome. Operious product surfaces are intended to expose the control plane rather than decorate it.",
        ],
      },
      {
        title: "Audit trail as customer assurance",
        body: [
          "Enterprises can also use auditability as assurance to their own customers. A company that can explain how a case was handled, which policy applied, and why escalation occurred builds more trust than one that simply says the AI handled it.",
          "The audit trail becomes part of the service promise. It tells customers and regulators that automation did not erase institutional accountability.",
        ],
      },
      {
        title: "The product conclusion",
        body: [
          "A regulated enterprise should not have to choose between automation and a defensible operating record. The audit trail is the mechanism that makes both possible. It gives automation a memory, a policy path, and a way to answer for itself.",
          "That is why Operious treats the event fabric as a core product surface. Without it, AI operations become faster but less accountable. With it, speed and accountability can reinforce each other.",
          "The audit trail is not paperwork after the product. It is part of the product's operational behavior and a primary way the enterprise preserves accountability while increasing automation across real production queues, exception paths, supervisor workflows, customer disputes, internal appeals, quality reviews, legal inquiries, remediation work, executive review, and regulated review cycles.",
        ],
      },
    ],
    ctas: [{ label: "Explore trust posture", href: "/trust" }],
  },

  articleMultiLanguage: {
    eyebrow: "Insights",
    title: "Multi-language operations need governance, not translation gloss.",
    subtitle:
      "The Arabic-language gap in customer operations shows why language must be treated as operational evidence rather than a thin localization layer.",
    intro: [
      "Many AI operations products handle English reasonably well and perform acceptably in common Romance-language workflows. They often struggle with Arabic, and they can fail more sharply with Arabic dialects, mixed-script messages, region-specific service language, and customer expressions that do not map cleanly to formal translation.",
      "This gap is well known to leaders who operate large outsourced and in-house customer operations across the Middle East and North Africa. The problem is not simply that translation quality varies. The problem is that language changes evidence, intent, policy selection, escalation, and customer trust.",
    ],
    sections: [
      {
        title: "Why Arabic is operationally hard",
        body: [
          "Arabic is not one uniform support surface. Customers may use Modern Standard Arabic, Gulf dialects, Levantine dialects, Egyptian Arabic, Maghrebi dialects, Arabizi, English code switching, or local product terminology. The same phrase can carry different urgency, politeness, or complaint meaning depending on region and context.",
          "An AI system that translates everything into generic English and then reasons over the translation can lose the evidence that mattered. A support decision may depend on the original wording, regional policy, warranty language, or cultural expectation.",
        ],
      },
      {
        title: "Where current platforms fail",
        body: [
          "Many platforms treat language as a preprocessing step. Translate the message, classify the English output, generate an answer, translate it back. That may work for simple questions. It is fragile when the workflow involves refunds, disputes, healthcare intake, public services, or defect categorization.",
          "The failure mode is subtle. The answer may be fluent, but the operational decision may be wrong. The system may miss dialectal complaint signals, fail to escalate sensitive requests, or apply the wrong regional policy.",
        ],
      },
      {
        title: "Dialect and policy are linked",
        body: [
          "Dialect is not only a linguistic problem. It can be a policy problem. A message from a customer in one market may refer to a local product name, service plan, warranty promise, or complaint convention that does not exist in another market. If the system flattens that message into generic English, it may select the wrong policy path.",
          "Operious preserves region, tenant, channel, and source-language context so policy selection can be governed. The system can treat low confidence as a reason to ask for clarification or route to a reviewer rather than forcing a brittle answer.",
        ],
      },
      {
        title: "Mixed-script operations",
        body: [
          "Real customer messages often include Arabic, English, numbers, product SKUs, screenshots, transliteration, and local shorthand in the same thread. A simple translation step can lose which token was a product name, which phrase was a complaint marker, and which part of the message contained the actual request.",
          "A governed multilingual workflow should preserve the original text, the extracted facts, the translation artifacts, and the confidence signals. Supervisors should be able to inspect the chain instead of seeing only the final generated response.",
        ],
      },
      {
        title: "Language as evidence",
        body: [
          "Operious treats language as part of the governance subject. Source language, dialect signals, translation artifacts, model confidence, channel, region, and policy context can be preserved in the event trace. This allows supervisors to review not only what answer was sent, but what linguistic evidence shaped the decision.",
          "This is important for auditability. If a customer challenges a decision, the enterprise should not be limited to an English paraphrase produced by an intermediate model. It should be able to inspect the source text and the operational interpretation.",
        ],
      },
      {
        title: "Governed escalation for language uncertainty",
        body: [
          "A serious multi-language system should know when not to continue. Low language confidence, dialect ambiguity, region-policy mismatch, sensitive complaint indicators, or incomplete translation evidence should trigger escalation. Operious can encode these as governance conditions rather than hoping the model self-polices.",
          "This is one of the clearest examples of LLM proposes, governance enforces. The model may identify possible intent. Governance determines whether that confidence is sufficient for execution.",
        ],
      },
      {
        title: "Operational design for multilingual teams",
        body: [
          "Multilingual operations need more than translated macros. They need tenant-owned terminology, region-specific policy, approved response patterns, escalation thresholds, and supervisor review in context. Operious lets those elements become part of the deployment constitution.",
          "This also supports quality teams. They can inspect where language uncertainty causes denials, where human review is frequent, and which procedures need clearer regional variants.",
        ],
      },
      {
        title: "Arabic operations and fairness",
        body: [
          "Language gaps create uneven service. Customers writing in Arabic or dialectal Arabic should not receive lower-quality decisions simply because the automation stack was tuned around English. They also should not be pushed into unnecessary human queues because the system lacks a disciplined way to represent uncertainty.",
          "The answer is not blind automation. The answer is governed automation: preserve language evidence, use tenant-approved terminology, escalate when confidence is insufficient, and make the decision path inspectable.",
        ],
      },
      {
        title: "Supervisor review in context",
        body: [
          "A multilingual supervisor needs more than a translated transcript. They need the source message, detected language signals, extracted facts, retrieved policy, proposed response, confidence, and governance decision. Operious can preserve these elements so review happens in operational context.",
          "This is especially important when customer experience and compliance meet. A phrase that looks harmless in translation may carry complaint weight in the source dialect. The trace should make that review possible.",
        ],
      },
      {
        title: "Operational knowledge by region",
        body: [
          "Language quality also depends on regional operational knowledge. A warranty phrase in one market, a payment term in another, or a public-service category in a third may carry meaning that a generic model does not know. Translating the words is not the same as applying the correct operating doctrine.",
          "Operious can bind retrieval to tenant-approved regional knowledge. The response path can show which procedure was used, which language evidence was preserved, and why the system selected or rejected a proposed action.",
        ],
      },
      {
        title: "Measuring multilingual readiness",
        body: [
          "A serious readiness test should include dialectal messages, mixed-script threads, low-context complaints, product-specific terminology, and region-specific policy. It should measure not only fluency, but correct classification, escalation, policy selection, and audit reconstruction.",
          "This is where many AI operations tools reveal their weakness. They can produce fluent text, but they cannot prove that the operational decision behind the text was governed.",
        ],
      },
      {
        title: "Why this matters commercially",
        body: [
          "Large enterprises cannot scale global operations if AI quality drops in the markets where multilingual support is most needed. A system that works only for English and a few nearby language families creates an uneven customer experience and a hidden compliance risk.",
          "Operious positions language coverage as an operational governance problem. The goal is not merely to sound fluent. The goal is to make the right governed decision in the customer's language context.",
        ],
      },
      {
        title: "A practical test",
        body: [
          "Ask whether a platform preserves source language in the trace. Ask whether dialect uncertainty can force escalation. Ask whether regional policies can be selected from language and tenant context. Ask whether supervisors can review the translation path. These questions reveal whether language is a first-class operational concern or just a UI feature.",
          "For Arabic-language operations, this test should include dialectal requests, mixed-script messages, region-specific policies, and cases that require refusal. Fluency alone is not enough. The platform must show that language evidence shaped a governed decision.",
          "That is the difference between translation coverage and operational readiness, especially in markets where customer trust depends on tone, dialect, evidence, escalation, region, and correct policy context.",
        ],
      },
    ],
    ctas: [
      { label: "Schedule a language operations review", href: "/company/contact?topic=multi-language" },
    ],
  },

  pricing: {
    eyebrow: "Pricing",
    title: "Custom pricing for governed operational deployment.",
    subtitle:
      "Operious pricing is based on deployment scope, monthly ticket volume, operational domains, integrations, compliance requirements, and support commitments. Public dollar amounts are not published.",
    intro: [
      "Regulated enterprise operations do not fit a generic self-serve price grid. The implementation effort depends on the domain, systems of record, channel adapters, tenant policies, knowledge corpus, audit requirements, and compliance posture. Operious prices engagements after architecture review so the proposal reflects the work actually being governed.",
      "The tiers below are designed to make evaluation scope clear. They are not metered consumer plans. Each tier is quoted commercially after the buyer and Operious agree on deployment assumptions.",
    ],
    cards: [
      {
        title: "Foundation",
        meta: "Contact for pricing",
        body: "For pilots and proof-of-value engagements.",
        href: "/company/contact?tier=foundation",
        items: [
          "Up to 5,000 tickets per month.",
          "One operational domain.",
          "60-day pilot terms.",
          "Architecture review and success criteria defined before kickoff.",
        ],
      },
      {
        title: "Operational",
        meta: "Contact for pricing",
        body: "For production deployments at single-domain scale.",
        href: "/company/contact?tier=operational",
        items: [
          "Up to 50,000 tickets per month.",
          "Single tenant production deployment.",
          "Full governance and audit layer.",
          "Integration plan for approved systems of record.",
        ],
      },
      {
        title: "Enterprise",
        meta: "Contact for pricing",
        body: "For multi-domain, multi-tenant production.",
        href: "/company/contact?tier=enterprise",
        items: [
          "Unlimited volume by commercial agreement.",
          "Dedicated SLA.",
          "Custom compliance attestations and review support.",
          "Multi-domain operating model and executive governance cadence.",
        ],
      },
    ],
    sections: [
      {
        title: "Foundation",
        body: [
          "Foundation is designed for pilots and proof-of-value engagements. The scope is intentionally narrow: one operational domain, up to 5,000 tickets per month, and 60-day pilot terms. A good pilot proves whether Operious can encode the tenant's operating doctrine, integrate with the necessary systems, and reconstruct decisions under review.",
          "Foundation is not a toy version of the product. It includes the architectural pieces required to evaluate governance and replay. The difference is scale and production scope.",
        ],
      },
      {
        title: "Operational",
        body: [
          "Operational is for single-domain production deployments. It supports up to 50,000 tickets per month, a single tenant, and the full governance and audit layer. This tier is appropriate when one regulated workflow family is ready for production automation and the enterprise needs a controlled operating model.",
          "The engagement includes workflow mapping, policy-chain configuration, knowledge ingestion, integration planning, audit export review, and production readiness criteria.",
        ],
      },
      {
        title: "Enterprise",
        body: [
          "Enterprise is for multi-domain, multi-tenant production. Volume is governed by commercial agreement rather than a public limit. This tier includes dedicated SLA commitments, custom compliance review, executive operating cadence, and broader architecture work across domains or business units.",
          "Enterprise buyers often need data residency planning, security architecture review, procurement documentation, custom channel adapters, and compliance attestations. Those requirements shape the final proposal.",
        ],
      },
      {
        title: "Why no public dollar amount",
        body: [
          "Publishing a generic price would hide the variables that matter: regulated data scope, integration complexity, governance depth, audit obligations, deployment geography, and support expectations. Operious provides pricing after architecture review so the buyer can compare scope honestly.",
        ],
      },
    ],
    ctas: [{ label: "Request pricing review", href: "/company/contact?topic=pricing" }],
  },

  company: {
    eyebrow: "Company",
    title: "Operious was founded to close the trust gap in enterprise AI operations.",
    subtitle:
      "Founded in 2026 by Imad Baraja, Operious is built from the conviction that regulated enterprises need governed execution infrastructure, not another model wrapper.",
    intro: [
      "Operious was founded in 2026 by Imad Baraja, who spent his early career inside enterprise customer operations and built Operious to address the architectural gaps he observed there. The pattern was clear: operational teams needed automation, but the available AI tools could not provide deterministic governance, tenant-controlled policy, or audit reconstruction strong enough for regulated work.",
      "The company exists to make enterprise AI operations accountable. That means treating policy, authority, evidence, tenant isolation, and replay as product primitives rather than procurement footnotes.",
    ],
    cards: companyLinks.map((link) => ({
      title: link.label,
      body: link.description ?? "",
      href: link.href,
    })),
    sections: [
      {
        title: "The founder story",
        body: [
          "Inside enterprise customer operations, the gaps are practical rather than theoretical. Teams spend heavily on labor that does not scale cleanly. Knowledge lives in people, documents, queues, and exceptions. Audit trails are often spread across systems that were never designed to reconstruct an automated decision. Language coverage varies by market. Compliance teams are asked to trust tools that cannot explain their own execution path.",
          "Operious was created to address those gaps architecturally. The answer is not a better chatbot. The answer is an operating substrate that lets agents help while governance controls what may happen.",
        ],
      },
      {
        title: "The mission",
        body: [
          "Operious builds governed execution infrastructure for regulated enterprise operations. The mission is to let operations leaders automate Tier 1 and Tier 2 workflows without surrendering policy control, audit defensibility, or tenant ownership of operational truth.",
          "That mission cuts across hardware, financial services, healthcare, insurance, telecommunications, logistics, and public sector domains. Each domain has different policies, but all need a system that can prove why it acted.",
        ],
      },
      {
        title: "The architectural conviction",
        body: [
          "AI should be useful where it is strong and constrained where it is risky. Models are valuable for cognition, classification, retrieval support, summarization, and drafting. They should not be the source of governance, execution authority, tenant isolation, or audit truth.",
          "Operious is built around this conviction: every decision is governed, every action is reconstructible, and every byte of operational state is tenant-isolated.",
        ],
      },
    ],
    ctas: [{ label: "Book an Architecture Review", href: "/company/contact?topic=architecture-review" }],
  },

  privacy: {
    eyebrow: "Legal",
    title: "Privacy policy.",
    subtitle: "Last updated: May 2026.",
    intro: [
      "This Privacy Policy describes how Operious AI, Inc. handles personal information in connection with its website, enterprise evaluations, communications, and governed execution services. Enterprise customers may have additional terms in a written agreement, data processing addendum, or business associate agreement where applicable.",
      "Operious is designed for regulated enterprise environments. Customer operational data is processed according to the customer's instructions and the applicable agreement. This public policy is intended to describe baseline website and service handling, not to replace deployment-specific contractual terms.",
    ],
    sections: [
      {
        title: "Information we collect",
        body: [
          "We may collect contact information such as name, company, role, email address, phone number, and business communication content when a person requests access, submits a form, attends a meeting, or communicates with Operious. We may collect website usage information such as device type, browser, pages visited, referral source, and approximate location where permitted.",
          "During enterprise evaluations or production deployments, Operious may process tenant-provided operational data, configuration, policies, knowledge documents, workflow events, and user activity records as authorized by the customer.",
        ],
      },
      {
        title: "How we use information",
        body: [
          "We use information to respond to requests, evaluate enterprise fit, provide and improve services, secure the platform, support customers, conduct compliance review, maintain audit trails, and communicate about Operious. We do not use customer operational data to train public foundation models.",
          "Where analytics or optional cookies are used on the website, users can manage preferences through the cookie banner. Essential cookies may be required for security and core site functionality.",
        ],
      },
      {
        title: "Enterprise data",
        body: [
          "Customer operational data remains controlled by the customer. Processing terms, retention, deletion, data residency, subprocessors, audit exports, and security controls are governed by the applicable enterprise agreement. Operious processes such data to provide the contracted service and related support.",
        ],
      },
      {
        title: "Sharing and subprocessors",
        body: [
          "Operious may share information with service providers that support hosting, security, communications, analytics, customer support, or enterprise operations. Subprocessor commitments for customer data are handled through enterprise agreements and customer review where required.",
        ],
      },
      {
        title: "Security",
        body: [
          "Operious uses administrative, technical, and organizational safeguards designed to protect information. No system can be guaranteed perfectly secure, but Operious designs its service around tenant isolation, encrypted credential handling, governed execution, and auditability.",
        ],
      },
      {
        title: "Privacy rights and contact",
        body: [
          "Depending on location, individuals may have rights to access, correct, delete, restrict, or object to certain processing of personal information. Requests can be sent to info@operious.com. Enterprise users may also need to contact their employer or the relevant customer administrator because Operious often acts as a processor or service provider.",
        ],
      },
    ],
  },

  terms: {
    eyebrow: "Legal",
    title: "Terms of service.",
    subtitle: "Last updated: May 2026.",
    intro: [
      "These Terms of Service govern access to the Operious website, public materials, and non-production evaluation experiences unless a separate written agreement applies. Production use of Operious requires a written enterprise agreement covering scope, security, data handling, service levels, support, and compliance obligations.",
      "By accessing the website or evaluation materials, users agree to use them only for lawful business purposes and in a manner consistent with these terms.",
    ],
    sections: [
      {
        title: "Website and evaluation use",
        body: [
          "Operious provides website content, product descriptions, technical materials, demonstrations, and evaluation environments for enterprise review. These materials are informational and may change as the product develops. They do not create a production service commitment unless incorporated into a written agreement.",
        ],
      },
      {
        title: "Accounts and access",
        body: [
          "Access to private evaluation or production environments may require authentication and authorization. Users are responsible for protecting credentials, using access only for authorized business purposes, and notifying Operious of suspected unauthorized use.",
        ],
      },
      {
        title: "Acceptable use",
        body: [
          "Users may not attempt to bypass tenant isolation, interfere with service operations, probe systems without authorization, reverse engineer security controls, upload unlawful content, violate third-party rights, or use Operious in a way that breaches applicable law or contractual obligations.",
        ],
      },
      {
        title: "Customer data and enterprise agreements",
        body: [
          "Customer operational data, confidentiality, security obligations, data processing terms, and production service levels are governed by the applicable written agreement. If these public terms conflict with a signed enterprise agreement, the enterprise agreement controls for that customer.",
        ],
      },
      {
        title: "Intellectual property",
        body: [
          "Operious and its materials, software, designs, documentation, trademarks, and related intellectual property are owned by Operious or its licensors. Users receive only the rights expressly granted for website access or evaluation use.",
        ],
      },
      {
        title: "Disclaimers and limitation",
        body: [
          "Website and evaluation materials are provided as is and as available. Operious does not provide public warranties through the website. Contractual warranties, indemnities, support commitments, and liability terms are only those stated in a written agreement.",
        ],
      },
      {
        title: "Contact",
        body: [
          "Questions about these terms can be sent to info@operious.com. Security matters should be sent to security@operious.com.",
        ],
      },
    ],
  },

  security: {
    eyebrow: "Legal",
    title: "Security disclosures.",
    subtitle: "Last updated: May 2026.",
    intro: [
      "Operious welcomes responsible security research and treats credible reports as part of maintaining trustworthy enterprise infrastructure. This page describes how to report vulnerabilities and what researchers can expect.",
      "Security review for enterprise customers is handled through the applicable procurement, legal, and architecture review process. Responsible disclosure reports can be sent directly to security@operious.com.",
    ],
    sections: [
      {
        title: "Responsible disclosure",
        body: [
          "Please include affected systems, reproduction steps, impact, relevant screenshots or logs, and contact information. Avoid accessing customer data, modifying records, degrading service availability, or performing destructive testing. Operious will acknowledge credible reports and prioritize remediation according to severity and exploitability.",
        ],
      },
      {
        title: "In-scope issues",
        body: [
          "Examples of in-scope issues include authentication defects, authorization bypass, tenant isolation failures, credential exposure, unauthorized data access, governance bypass paths, remote code execution, and vulnerabilities that materially affect production service integrity.",
        ],
      },
      {
        title: "Out-of-scope issues",
        body: [
          "Out-of-scope issues may include denial-of-service testing without approval, spam, social engineering, physical attacks, reports without security impact, automated scanner output without validation, or vulnerabilities in third-party services outside Operious control.",
        ],
      },
      {
        title: "Operating commitments",
        body: [
          "Operious prioritizes vulnerabilities based on severity, customer impact, exploitability, affected deployment scope, and available mitigations. Enterprise customers receive security handling terms through their written agreement.",
        ],
      },
      {
        title: "Security architecture review",
        body: [
          "Enterprise buyers can request review of tenant isolation, encryption, credential handling, event auditability, access controls, subprocessors, deployment topology, and compliance roadmap. These reviews are part of the architecture process for regulated deployments.",
        ],
      },
    ],
    ctas: [{ label: "Request security review", href: "/company/contact?topic=security" }],
  },
};
