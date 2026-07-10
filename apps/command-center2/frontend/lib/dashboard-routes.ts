export const dashboardRoutes = {
  overview: "/dashboard/overview",
  attention: "/dashboard/attention",
  operations: "/dashboard/queue",
  conversations: "/dashboard/conversations",
  inbox: "/dashboard/inbox",
  assistant: "/dashboard/assistant",
  // queue-status has no standalone page — Operations Queue shows queue health
  "queue-status": "/dashboard/queue",
  "dlq-inspector": "/dashboard/dlq",
  fraud: "/dashboard/fraud",
  trace: "/dashboard/traces",
  supervisor: "/dashboard/supervisor",
  // escalations, case-approvals, and approvals live as tabs inside /attention
  escalations: "/dashboard/attention",
  "case-approvals": "/dashboard/attention",
  approvals: "/dashboard/attention",
  cognition: "/dashboard/cognition",
  knowledge: "/dashboard/knowledge",
  governance: "/dashboard/governance",
  crisis: "/dashboard/crisis",
  topology: "/dashboard/topology",
  channels: "/dashboard/channels",
  connectors: "/dashboard/connectors",
  "action-policy": "/dashboard/action-policy",
  "config-approvals": "/dashboard/config-approvals",
  onboarding: "/dashboard/onboarding",
  team: "/dashboard/team",
  audit: "/dashboard/audit",
  settings: "/dashboard/settings",
} as const;

export type DashboardViewId = keyof typeof dashboardRoutes;
