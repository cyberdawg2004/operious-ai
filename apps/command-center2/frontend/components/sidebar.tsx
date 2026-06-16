"use client";

import { useState } from "react";
import { useUser } from "@auth0/nextjs-auth0/client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { dashboardRoutes } from "@/lib/dashboard-routes";
import { cn } from "@/lib/utils";
import { Logo } from "./logo";
import { useTheme } from "./theme-provider";
import {
  Activity,
  AlertTriangle,
  Building2,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Inbox,
  LayoutDashboard,
  LayoutList,
  MessageSquare,
  Network,
  Brain,
  BookOpen,
  Gavel,
  GitBranch,
  Radio,
  Plug,
  Users,
  FileSearch,
  Settings,
  ShieldAlert,
  LifeBuoy,
  LogOut,
  Sun,
  Moon,
  X,
} from "lucide-react";

interface NavItem {
  id: string;
  href: string;
  label: string;
  icon: React.ElementType;
  group: "operations" | "intelligence" | "platform" | "system";
  /** When set, the item is surfaced only to principals holding this capability. */
  requiresCapability?: string;
}

const navItems: NavItem[] = [
  { id: "overview", href: dashboardRoutes.overview, label: "Command Overview", icon: LayoutDashboard, group: "operations" },
  { id: "attention", href: dashboardRoutes.attention, label: "Needs Your Attention", icon: Inbox, group: "operations" },
  { id: "operations", href: dashboardRoutes.operations, label: "Operations Queue", icon: LayoutList, group: "operations" },
  { id: "conversations", href: dashboardRoutes.conversations, label: "Conversations", icon: MessageSquare, group: "operations" },
  { id: "queue-status", href: dashboardRoutes["queue-status"], label: "Queue Status", icon: Activity, group: "operations" },
  { id: "dlq-inspector", href: dashboardRoutes["dlq-inspector"], label: "Failed Operations", icon: AlertTriangle, group: "operations" },
  { id: "fraud", href: dashboardRoutes.fraud, label: "Fraud Monitoring", icon: ShieldAlert, group: "operations" },
  { id: "trace", href: dashboardRoutes.trace, label: "Decision History", icon: Network, group: "operations" },
  { id: "supervisor", href: dashboardRoutes.supervisor, label: "Quality Reviews", icon: ShieldAlert, group: "operations" },
  { id: "escalations", href: dashboardRoutes.escalations, label: "Escalations", icon: LifeBuoy, group: "operations", requiresCapability: "tenant.operations.read" },
  { id: "case-approvals", href: dashboardRoutes["case-approvals"], label: "Case Approvals", icon: ClipboardCheck, group: "operations", requiresCapability: "tenant.approvals.read" },
  { id: "approvals", href: dashboardRoutes.approvals, label: "Approval Inbox", icon: Inbox, group: "intelligence" },
  { id: "cognition", href: dashboardRoutes.cognition, label: "AI Recommendations", icon: Brain, group: "intelligence" },
  { id: "knowledge", href: dashboardRoutes.knowledge, label: "Knowledge Base", icon: BookOpen, group: "intelligence" },
  { id: "governance", href: dashboardRoutes.governance, label: "Governance", icon: Gavel, group: "platform" },
  { id: "crisis", href: dashboardRoutes.crisis, label: "Crisis History", icon: ShieldAlert, group: "platform" },
  { id: "topology", href: dashboardRoutes.topology, label: "Workforce Map", icon: GitBranch, group: "platform" },
  { id: "channels", href: dashboardRoutes.channels, label: "Channels", icon: Radio, group: "platform" },
  { id: "connectors", href: dashboardRoutes.connectors, label: "Connector Config", icon: Plug, group: "platform" },
  { id: "action-policy", href: dashboardRoutes["action-policy"], label: "Action Policy", icon: Gavel, group: "platform" },
  { id: "config-approvals", href: dashboardRoutes["config-approvals"], label: "Configuration Approvals", icon: Inbox, group: "platform" },
  { id: "onboarding", href: dashboardRoutes.onboarding, label: "Configure Tenant", icon: Building2, group: "platform" },
  { id: "team", href: dashboardRoutes.team, label: "Team & Roles", icon: Users, group: "system" },
  { id: "audit", href: dashboardRoutes.audit, label: "Audit & Exports", icon: FileSearch, group: "system" },
  { id: "settings", href: dashboardRoutes.settings, label: "Settings", icon: Settings, group: "system" },
];

/**
 * Daily-work surfaces for support managers — kept small and always visible
 * so the primary view never feels cluttered with admin/config screens.
 */
const PRIMARY_ITEM_IDS = ["operations", "attention", "knowledge", "cognition"];

const adminGroupLabels: Record<NavItem["group"], string> = {
  operations: "Monitoring",
  intelligence: "Intelligence",
  platform: "Platform",
  system: "System",
};

const adminGroupOrder: NavItem["group"][] = ["operations", "intelligence", "platform", "system"];

interface SidebarProps {
  collapsed?: boolean;
  tenantName?: string;
  userName?: string;
  userRole?: string;
  onTenantClick?: () => void;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
  className?: string;
  approvalCount?: number | null;
  crisisActive?: boolean;
  fraudActive?: boolean;
  capabilities?: string[] | null;
}

export function Sidebar({
  collapsed = false,
  tenantName = "Tenant scope not configured",
  userName = "Unverified operator",
  userRole = "Principal scope not configured",
  onTenantClick,
  mobileOpen = false,
  onMobileClose,
  className,
  approvalCount = null,
  crisisActive = false,
  fraudActive = false,
  capabilities = null,
}: SidebarProps) {
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const { user, isLoading } = useUser();
  const resolvedUserName =
    !isLoading && user
      ? user.name || user.email || user.nickname || "Authenticated operator"
      : userName;
  const resolvedUserRole =
    !isLoading && user ? user.email || "Authenticated session" : userRole;
  const initials = resolvedUserName
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const clearLocalAuthorityCache = () => {
    window.localStorage.removeItem("operious_tenant_id");
    window.localStorage.removeItem("operious_principal_id");
    window.localStorage.removeItem("operious_operator_label");
  };

  const visibleItems = navItems.filter(
    (item) =>
      !item.requiresCapability || (capabilities ?? []).includes(item.requiresCapability)
  );
  const primaryItems = PRIMARY_ITEM_IDS
    .map((id) => visibleItems.find((item) => item.id === id))
    .filter((item): item is NavItem => Boolean(item));
  const adminItems = visibleItems.filter((item) => !PRIMARY_ITEM_IDS.includes(item.id));
  const activeIsAdmin = adminItems.some((item) => item.href === pathname);
  const [adminOpen, setAdminOpen] = useState(activeIsAdmin);

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-50 flex h-dvh w-[260px] shrink-0 flex-col",
        "bg-[var(--surface)] border-r border-[var(--border-subtle)]",
        "overscroll-contain transition-[transform,width] duration-200 ease-out will-change-transform",
        mobileOpen ? "translate-x-0" : "-translate-x-full",
        collapsed ? "lg:w-[68px]" : "lg:w-[240px]",
        "lg:sticky lg:top-0 lg:z-30 lg:h-screen lg:translate-x-0",
        className
      )}
      aria-label="Primary command navigation"
    >
      {/* Top — logo + tenant */}
      <div className={cn("px-4 pb-3 pt-4", collapsed && "lg:px-3")}>
        <div className="flex items-center justify-between gap-3">
          <Link
            href={dashboardRoutes.overview}
            className="flex items-center gap-2"
            aria-label="Operious home"
          >
            <Logo
              variant={collapsed ? "mark" : "lockup"}
              tone={theme === "dark" ? "dark" : "light"}
              height={collapsed ? 28 : 24}
            />
          </Link>
          <button
            type="button"
            className="flex h-9 w-9 items-center justify-center rounded-md border border-border-subtle text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary lg:hidden"
            onClick={onMobileClose}
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>

        <button
          onClick={onTenantClick}
          className={cn(
            "mt-4 flex h-9 w-full items-center gap-2 rounded-lg border border-border-subtle bg-surface-raised px-2.5 transition-all duration-200",
            "hover:border-border-defined hover:bg-surface",
            collapsed && "lg:justify-center lg:px-0"
          )}
          title={tenantName}
        >
          <Building2 size={13} strokeWidth={1.8} className="shrink-0 text-ink-tertiary" />
          <span
            className={cn(
              "flex-1 truncate text-left text-[12.5px] font-medium text-ink-primary",
              collapsed && "lg:hidden"
            )}
          >
            {tenantName}
          </span>
          <ChevronDown
            size={11}
            strokeWidth={1.8}
            className={cn("shrink-0 text-ink-tertiary", collapsed && "lg:hidden")}
          />
        </button>
      </div>

      {/* Navigation */}
      <nav className={cn("flex-1 overflow-y-auto px-3 py-3", collapsed && "lg:px-2")}>
        {/* Primary — daily manager work */}
        <div>
          {!collapsed && (
            <h4 className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-quaternary">
              Daily Work
            </h4>
          )}
          <ul className="space-y-1">
            {primaryItems.map((item) => (
              <NavLink
                key={item.id}
                item={item}
                pathname={pathname}
                collapsed={collapsed}
                hoveredItem={hoveredItem}
                setHoveredItem={setHoveredItem}
                onMobileClose={onMobileClose}
                approvalCount={approvalCount}
                crisisActive={crisisActive}
                fraudActive={fraudActive}
                size="lg"
              />
            ))}
          </ul>
        </div>

        {/* Admin — secondary, collapsible */}
        <div className="mt-5">
          <button
            type="button"
            onClick={() => setAdminOpen((open) => !open)}
            className={cn(
              "mb-1.5 flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-quaternary transition-colors hover:text-ink-tertiary",
              collapsed && "lg:justify-center"
            )}
            aria-expanded={adminOpen}
          >
            <ChevronRight
              size={12}
              strokeWidth={2}
              className={cn("transition-transform duration-150", adminOpen && "rotate-90")}
            />
            {!collapsed && <span>Admin &amp; Configuration</span>}
          </button>

          {adminOpen &&
            adminGroupOrder.map((groupKey) => {
              const groupItems = adminItems.filter((item) => item.group === groupKey);
              if (groupItems.length === 0) return null;
              return (
                <div key={groupKey} className="mb-3">
                  {!collapsed && (
                    <h5 className="mb-1 px-2 text-[10px] font-medium uppercase tracking-[0.12em] text-ink-quaternary">
                      {adminGroupLabels[groupKey]}
                    </h5>
                  )}
                  <ul className="space-y-0.5">
                    {groupItems.map((item) => (
                      <NavLink
                        key={item.id}
                        item={item}
                        pathname={pathname}
                        collapsed={collapsed}
                        hoveredItem={hoveredItem}
                        setHoveredItem={setHoveredItem}
                        onMobileClose={onMobileClose}
                        approvalCount={approvalCount}
                        crisisActive={crisisActive}
                        fraudActive={fraudActive}
                        size="sm"
                      />
                    ))}
                  </ul>
                </div>
              );
            })}
        </div>
      </nav>

      {/* Footer — profile + theme */}
      <div
        className={cn(
          "border-t border-border-subtle px-3 pb-3 pt-3",
          collapsed && "lg:px-2"
        )}
      >
        <button
          type="button"
          onClick={() => {
            clearLocalAuthorityCache();
            const logoutUrl = new URL("/api/auth/logout", window.location.origin);
            logoutUrl.searchParams.set("returnTo", window.location.origin);
            window.location.assign(logoutUrl.toString());
          }}
          className={cn(
            "group flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors duration-150",
            "hover:bg-surface-raised",
            collapsed && "lg:justify-center lg:px-0"
          )}
          title="Sign out"
        >
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-raised text-[10.5px] font-semibold text-ink-secondary ring-1 ring-border-subtle">
            {initials}
          </div>
          <div className={cn("min-w-0 flex-1", collapsed && "lg:hidden")}>
            <p className="truncate text-[12px] font-medium text-ink-primary">
              {resolvedUserName}
            </p>
            <p className="truncate text-[10.5px] text-ink-tertiary">
              {resolvedUserRole}
            </p>
          </div>
          <LogOut
            size={13}
            strokeWidth={1.8}
            className={cn(
              "shrink-0 text-ink-quaternary transition-colors group-hover:text-ink-secondary",
              collapsed && "lg:hidden"
            )}
          />
        </button>

        <button
          onClick={toggleTheme}
          className={cn(
            "mt-1 flex h-8 w-full items-center justify-between gap-2 rounded-lg px-2 text-[11px] text-ink-tertiary transition-colors duration-150 hover:bg-surface-raised hover:text-ink-secondary",
            collapsed && "lg:justify-center lg:px-0"
          )}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          <span className={cn("font-medium uppercase tracking-[0.1em]", collapsed && "lg:hidden")}>
            {theme === "dark" ? "Dark" : "Light"}
          </span>
          {theme === "dark" ? (
            <Moon size={12} strokeWidth={1.8} />
          ) : (
            <Sun size={12} strokeWidth={1.8} />
          )}
        </button>
      </div>
    </aside>
  );
}

function NavLink({
  item,
  pathname,
  collapsed,
  hoveredItem,
  setHoveredItem,
  onMobileClose,
  approvalCount,
  crisisActive,
  fraudActive,
  size,
}: {
  item: NavItem;
  pathname: string | null;
  collapsed: boolean;
  hoveredItem: string | null;
  setHoveredItem: (id: string | null) => void;
  onMobileClose?: () => void;
  approvalCount: number | null;
  crisisActive: boolean;
  fraudActive: boolean;
  size: "lg" | "sm";
}) {
  const isActive = pathname === item.href;
  const isHovered = hoveredItem === item.id;
  const Icon = item.icon;
  const isLarge = size === "lg";

  return (
    <li>
      <Link
        href={item.href}
        onClick={onMobileClose}
        onMouseEnter={() => setHoveredItem(item.id)}
        onMouseLeave={() => setHoveredItem(null)}
        className={cn(
          "relative flex w-full items-center gap-2.5 rounded-lg px-2 transition-colors duration-150",
          isLarge ? "h-9" : "h-8",
          isActive
            ? "nav-active"
            : "text-ink-secondary hover:bg-surface-raised hover:text-ink-primary",
          collapsed && "lg:justify-center lg:px-0",
          isHovered && !isActive && "bg-surface-raised"
        )}
        title={item.label}
      >
        <Icon
          size={isLarge ? 16 : 15}
          strokeWidth={1.7}
          className={cn(
            "shrink-0 transition-colors duration-150",
            isActive ? "text-gold-primary" : "text-ink-tertiary"
          )}
        />
        <span
          className={cn(
            "truncate font-medium",
            isLarge ? "text-[13px]" : "text-[12.5px]",
            collapsed && "lg:hidden"
          )}
        >
          {item.label}
        </span>
        {item.id === "attention" && approvalCount !== null && approvalCount > 0 && (
          <span
            className={cn(
              "ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-gold-primary px-1.5 text-[10px] font-semibold text-white",
              collapsed && "lg:hidden"
            )}
          >
            {approvalCount > 99 ? "99+" : approvalCount}
          </span>
        )}
        {(item.id === "governance" || item.id === "crisis") && crisisActive && (
          <span
            className={cn(
              "ml-auto h-2 w-2 rounded-full bg-red-alert",
              collapsed && "lg:absolute lg:right-2 lg:top-2"
            )}
            aria-label="Active crisis deployment"
          />
        )}
        {item.id === "fraud" && fraudActive && (
          <span
            className={cn(
              "ml-auto h-2 w-2 rounded-full bg-red-alert",
              collapsed && "lg:absolute lg:right-2 lg:top-2"
            )}
            aria-label="Semantic circuit tripped"
          />
        )}
      </Link>
    </li>
  );
}
