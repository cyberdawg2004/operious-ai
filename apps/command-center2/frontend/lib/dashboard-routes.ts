export const dashboardRoutes = {
  operations: "/dashboard/queue",
  conversations: "/dashboard/conversations",
  "queue-status": "/dashboard/queue-status",
  "dlq-inspector": "/dashboard/dlq",
  trace: "/dashboard/traces",
  approvals: "/dashboard/approvals",
  cognition: "/dashboard/cognition",
  knowledge: "/dashboard/knowledge",
  governance: "/dashboard/governance",
  topology: "/dashboard/topology",
  channels: "/dashboard/channels",
  team: "/dashboard/team",
  audit: "/dashboard/audit",
  settings: "/dashboard/settings",
} as const;

export type DashboardViewId = keyof typeof dashboardRoutes;
