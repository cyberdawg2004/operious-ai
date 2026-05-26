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
  LayoutList,
  Network,
  Brain,
  BookOpen,
  Gavel,
  GitBranch,
  Radio,
  Users,
  FileSearch,
  Settings,
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
}

const navItems: NavItem[] = [
  { id: "operations", href: dashboardRoutes.operations, label: "Operations Queue", icon: LayoutList, group: "operations" },
  { id: "queue-status", href: dashboardRoutes["queue-status"], label: "Queue Status", icon: Activity, group: "operations" },
  { id: "dlq-inspector", href: dashboardRoutes["dlq-inspector"], label: "DLQ Inspector", icon: AlertTriangle, group: "operations" },
  { id: "trace", href: dashboardRoutes.trace, label: "Trace Inspector", icon: Network, group: "operations" },
  { id: "cognition", href: dashboardRoutes.cognition, label: "Cognition Hub", icon: Brain, group: "intelligence" },
  { id: "knowledge", href: dashboardRoutes.knowledge, label: "Knowledge Base", icon: BookOpen, group: "intelligence" },
  { id: "governance", href: dashboardRoutes.governance, label: "Governance", icon: Gavel, group: "platform" },
  { id: "topology", href: dashboardRoutes.topology, label: "Topology", icon: GitBranch, group: "platform" },
  { id: "channels", href: dashboardRoutes.channels, label: "Channels", icon: Radio, group: "platform" },
  { id: "team", href: dashboardRoutes.team, label: "Team & Roles", icon: Users, group: "system" },
  { id: "audit", href: dashboardRoutes.audit, label: "Audit & Exports", icon: FileSearch, group: "system" },
  { id: "settings", href: dashboardRoutes.settings, label: "Settings", icon: Settings, group: "system" },
];

const groupLabels: Record<NavItem["group"], string> = {
  operations: "Operations",
  intelligence: "Intelligence",
  platform: "Platform",
  system: "System",
};

const groupOrder: NavItem["group"][] = ["operations", "intelligence", "platform", "system"];

interface SidebarProps {
  collapsed?: boolean;
  tenantName?: string;
  userName?: string;
  userRole?: string;
  onTenantClick?: () => void;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
  className?: string;
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

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-50 flex h-dvh w-[260px] shrink-0 flex-col",
        "bg-[var(--surface)] border-r border-[var(--border-subtle)]",
        "overscroll-contain transition-[transform,width] duration-200 ease-out will-change-transform",
        mobileOpen ? "translate-x-0" : "-translate-x-full",
        collapsed ? "lg:w-[68px]" : "lg:w-[232px]",
        "lg:sticky lg:top-0 lg:z-30 lg:h-screen lg:translate-x-0",
        className
      )}
      aria-label="Primary command navigation"
    >
      {/* Top — logo + tenant */}
      <div className={cn("px-4 pb-3 pt-4", collapsed && "lg:px-3")}>
        <div className="flex items-center justify-between gap-3">
          <Link
            href={dashboardRoutes.operations}
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
            "mt-4 flex h-9 w-full items-center gap-2 rounded-md border border-border-subtle bg-surface-raised px-2.5 transition-all duration-200",
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
        {groupOrder.map((groupKey, groupIdx) => {
          const groupItems = navItems.filter((item) => item.group === groupKey);
          if (groupItems.length === 0) return null;
          return (
            <div key={groupKey} className={cn(groupIdx > 0 && "mt-5")}>
              {!collapsed && (
                <h4 className="mb-1.5 px-2 font-technical text-[10px] font-semibold uppercase tracking-[0.18em] text-ink-quaternary">
                  {groupLabels[groupKey]}
                </h4>
              )}
              <ul className="space-y-0.5">
                {groupItems.map((item) => {
                  const isActive = pathname === item.href;
                  const isHovered = hoveredItem === item.id;
                  const Icon = item.icon;

                  return (
                    <li key={item.id}>
                      <Link
                        href={item.href}
                        onClick={onMobileClose}
                        onMouseEnter={() => setHoveredItem(item.id)}
                        onMouseLeave={() => setHoveredItem(null)}
                        className={cn(
                          "relative flex h-8 w-full items-center gap-2.5 rounded-md px-2 transition-colors duration-150",
                          isActive
                            ? "bg-gold-bg text-ink-primary"
                            : "text-ink-secondary hover:bg-surface-raised hover:text-ink-primary",
                          collapsed && "lg:justify-center lg:px-0",
                          isHovered && !isActive && "bg-surface-raised"
                        )}
                        title={item.label}
                      >
                        {isActive && (
                          <span
                            aria-hidden
                            className={cn(
                              "absolute bottom-1.5 left-0 top-1.5 w-[2px] rounded-sm bg-gold-primary",
                              collapsed && "lg:hidden"
                            )}
                          />
                        )}
                        <Icon
                          size={15}
                          strokeWidth={1.7}
                          className={cn(
                            "shrink-0 transition-colors duration-150",
                            isActive ? "text-gold-primary" : "text-ink-tertiary"
                          )}
                        />
                        <span
                          className={cn(
                            "truncate text-[12.5px] font-medium",
                            collapsed && "lg:hidden"
                          )}
                        >
                          {item.label}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
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
            window.location.assign("/api/auth/logout");
          }}
          className={cn(
            "group flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors duration-150",
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
            "mt-1 flex h-8 w-full items-center justify-between gap-2 rounded-md px-2 text-[11px] text-ink-tertiary transition-colors duration-150 hover:bg-surface-raised hover:text-ink-secondary",
            collapsed && "lg:justify-center lg:px-0"
          )}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          <span className={cn("font-technical uppercase tracking-[0.14em]", collapsed && "lg:hidden")}>
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
