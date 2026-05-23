export type SiteLink = {
  label: string;
  href: string;
  description?: string;
};

export type LinkGroup = {
  label: string;
  links: SiteLink[];
};

export const commandCenterUrl =
  process.env.NEXT_PUBLIC_COMMAND_CENTER_URL ?? "https://command.operious.ai";

export const platformLinks: SiteLink[] = [
  {
    label: "Platform overview",
    href: "/platform",
    description: "The governed execution architecture behind Operious.",
  },
  {
    label: "Constitutional governance",
    href: "/platform/governance",
    description: "Policy enforcement, fail-closed defaults, and admission tokens.",
  },
  {
    label: "Forensic replay",
    href: "/platform/replay",
    description: "Reconstruct operational decisions from source state and events.",
  },
  {
    label: "Multi-agent system",
    href: "/platform/agents",
    description: "Deterministic coordination for specialized operational agents.",
  },
];

export const industryLinks: SiteLink[] = [
  {
    label: "Industries overview",
    href: "/industries",
    description: "Operational domains where auditability is a deployment requirement.",
  },
  {
    label: "Hardware",
    href: "/industries/hardware",
    description: "Warranty, returns, defect categorization, and multilingual support.",
  },
  {
    label: "Financial services",
    href: "/industries/financial-services",
    description: "Disputes, fraud-adjacent triage, and regulator-grade trails.",
  },
  {
    label: "Healthcare",
    href: "/industries/healthcare",
    description: "PHI-aware intake, patient communication, and governed routing.",
  },
  {
    label: "Insurance",
    href: "/industries/insurance",
    description: "FNOL, claims triage, policy questions, and escalation control.",
  },
  {
    label: "Telecommunications",
    href: "/industries/telecom",
    description: "Service interruption, billing, SIM, and device provisioning workflows.",
  },
  {
    label: "Logistics",
    href: "/industries/logistics",
    description: "Shipment exceptions, documentation, and delivery dispute resolution.",
  },
  {
    label: "Public sector",
    href: "/industries/public-sector",
    description: "Citizen requests, jurisdictional policy, and FOIA-compatible logs.",
  },
];

export const trustLinks: SiteLink[] = [
  {
    label: "Trust overview",
    href: "/trust",
    description: "Security, compliance, and governance posture.",
  },
  {
    label: "Security architecture",
    href: "/trust/architecture",
    description: "Tenant isolation, encrypted credentials, and audit event fabric.",
  },
  {
    label: "Compliance roadmap",
    href: "/trust/compliance",
    description: "Current posture and honest certification planning.",
  },
  {
    label: "Security disclosures",
    href: "/legal/security",
    description: "Responsible disclosure and operating security commitments.",
  },
];

export const insightLinks: SiteLink[] = [
  {
    label: "Insights index",
    href: "/insights",
    description: "Articles on governed AI operations and deterministic execution.",
  },
  {
    label: "Constitutional AI governance",
    href: "/insights/constitutional-ai-governance",
    description: "Why policy must execute at runtime instead of living in prompts.",
  },
  {
    label: "Reconstructible truth",
    href: "/insights/reconstructible-truth",
    description: "The forensic auditability problem in AI operations.",
  },
  {
    label: "Beyond LLM wrappers",
    href: "/insights/beyond-llm-wrappers",
    description: "What separates execution infrastructure from model orchestration.",
  },
  {
    label: "Audit trail as product",
    href: "/insights/audit-trail-as-product",
    description: "Why regulated enterprises need the event fabric to be first-class.",
  },
  {
    label: "Multi-language operations",
    href: "/insights/multi-language-operations",
    description: "Language coverage as an operational governance problem.",
  },
];

export const companyLinks: SiteLink[] = [
  {
    label: "Company",
    href: "/company",
    description: "The mission and operating conviction behind Operious.",
  },
  {
    label: "Request access",
    href: "/company/contact",
    description: "Start an enterprise architecture review.",
  },
  {
    label: "Pricing",
    href: "/pricing",
    description: "Pilot, operational, and enterprise engagement models.",
  },
];

export const legalLinks: SiteLink[] = [
  { label: "Privacy policy", href: "/legal/privacy" },
  { label: "Terms of service", href: "/legal/terms" },
  { label: "Security disclosures", href: "/legal/security" },
];

export const headerGroups: LinkGroup[] = [
  { label: "Platform", links: platformLinks },
  { label: "Industries", links: industryLinks },
  { label: "Trust", links: trustLinks },
  { label: "Insights", links: insightLinks },
  { label: "Company", links: companyLinks },
];

export const footerGroups: LinkGroup[] = [
  { label: "Platform", links: platformLinks },
  { label: "Industries", links: industryLinks },
  { label: "Trust", links: trustLinks },
  { label: "Insights", links: insightLinks },
  { label: "Company", links: companyLinks },
  { label: "Legal", links: legalLinks },
];

export const requiredRoutes = [
  "/",
  "/platform",
  "/platform/governance",
  "/platform/replay",
  "/platform/agents",
  "/industries",
  "/industries/hardware",
  "/industries/financial-services",
  "/industries/healthcare",
  "/industries/insurance",
  "/industries/telecom",
  "/industries/logistics",
  "/industries/public-sector",
  "/trust",
  "/trust/architecture",
  "/trust/compliance",
  "/insights",
  "/insights/constitutional-ai-governance",
  "/insights/reconstructible-truth",
  "/insights/beyond-llm-wrappers",
  "/insights/audit-trail-as-product",
  "/insights/multi-language-operations",
  "/pricing",
  "/company",
  "/company/contact",
  "/legal/privacy",
  "/legal/terms",
  "/legal/security",
] as const;
