"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Logo } from "./logo";
import { useTheme } from "./theme-provider";
import {
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
  label: string;
  icon: React.ElementType;
}

const navItems: NavItem[] = [
  { id: "operations", label: "Operations Queue", icon: LayoutList },
  { id: "trace", label: "Trace Inspector", icon: Network },
  { id: "cognition", label: "Cognition Hub", icon: Brain },
  { id: "knowledge", label: "Knowledge Base", icon: BookOpen },
  { id: "governance", label: "Governance Policies", icon: Gavel },
  { id: "topology", label: "Topology", icon: GitBranch },
  { id: "channels", label: "Channels", icon: Radio },
  { id: "team", label: "Team & Roles", icon: Users },
  { id: "audit", label: "Audit & Exports", icon: FileSearch },
  { id: "settings", label: "Settings", icon: Settings },
];

interface SidebarProps {
  activeItem?: string;
  collapsed?: boolean;
  onNavigate?: (itemId: string) => void;
  tenantName?: string;
  userName?: string;
  userRole?: string;
  onTenantClick?: () => void;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
  className?: string;
}

export function Sidebar({
  activeItem = "operations",
  collapsed = false,
  onNavigate,
  tenantName = "Tenant scope not configured",
  userName = "Unverified operator",
  userRole = "Principal scope not configured",
  onTenantClick,
  mobileOpen = false,
  onMobileClose,
  className,
}: SidebarProps) {
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);
  const { theme, toggleTheme } = useTheme();

  const handleSignOut = () => {
    localStorage.removeItem("operious_access_token");
    window.location.reload();
  };

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-50 flex h-dvh w-[280px] shrink-0 flex-col",
        "bg-[var(--surface-raised)] border-r border-[var(--border-subtle)]",
        "overscroll-contain transition-[transform,width] duration-200 ease-out will-change-transform",
        mobileOpen ? "translate-x-0" : "-translate-x-full",
        collapsed ? "lg:w-[76px]" : "lg:w-[248px]",
        "lg:sticky lg:top-0 lg:z-30 lg:h-screen lg:translate-x-0",
        className
      )}
      aria-label="Primary command navigation"
    >
      {/* Top section - Logo and tenant selector */}
      <div className={cn("px-4 pb-4 pt-5", collapsed ? "lg:px-3" : "lg:px-5")}>
        <div className="flex items-center justify-between gap-3">
          <Logo
            className={cn("h-9 w-auto text-ink-primary", collapsed && "lg:hidden")}
            height={36}
            tone={theme === "dark" ? "dark" : "light"}
            width={148}
          />
          <Logo
            className={cn("hidden h-10 w-10 text-ink-primary", collapsed && "lg:block")}
            height={40}
            tone={theme === "dark" ? "dark" : "light"}
            variant="mark"
            width={40}
          />
          <button
            type="button"
            className="flex h-11 w-11 items-center justify-center rounded border border-border-subtle text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary lg:hidden"
            onClick={onMobileClose}
            aria-label="Close navigation"
          >
            <X className="h-5 w-5" strokeWidth={1.7} />
          </button>
        </div>

        {/* Tenant selector */}
        <button
          onClick={onTenantClick}
          className={cn(
            "mt-5 flex h-11 w-full items-center gap-2 rounded px-3 lg:h-10",
            "border border-[var(--border-subtle)] rounded",
            "transition-all duration-160",
            "hover:bg-[var(--surface)] hover:border-[var(--border-defined)]",
            collapsed && "lg:justify-center lg:px-0"
          )}
          title={tenantName}
        >
          <Building2 
            size={14} 
            strokeWidth={1.5} 
            className="text-ink-tertiary shrink-0" 
          />
          <span
            className={cn(
              "flex-1 truncate text-left text-[13px] font-medium text-ink-primary",
              collapsed && "lg:hidden"
            )}
          >
            {tenantName}
          </span>
          <ChevronDown 
            size={12} 
            strokeWidth={1.5} 
            className={cn("text-ink-tertiary shrink-0", collapsed && "lg:hidden")} 
          />
        </button>
      </div>

      {/* Navigation section */}
      <nav className={cn("flex-1 overflow-y-auto px-4 py-3", collapsed && "lg:px-3")}>
        <ul className="space-y-1">
          {navItems.map((item) => {
            const isActive = activeItem === item.id;
            const isHovered = hoveredItem === item.id;
            const Icon = item.icon;

            return (
              <li key={item.id}>
                <button
                  onClick={() => onNavigate?.(item.id)}
                  onMouseEnter={() => setHoveredItem(item.id)}
                  onMouseLeave={() => setHoveredItem(null)}
                  className={cn(
                    "flex h-11 w-full items-center gap-3 rounded lg:h-10",
                    "transition-all duration-160",
                    isActive
                      ? "bg-[var(--gold-bg)] border-l-4 border-l-[var(--gold-primary)] pl-2 pr-3"
                      : "px-3",
                    collapsed && "lg:justify-center lg:px-0",
                    collapsed && isActive && "lg:border-l-0 lg:pl-0 lg:pr-0 lg:ring-1 lg:ring-[var(--gold-primary)]",
                    !isActive && isHovered && "bg-[var(--surface-sunken)]"
                  )}
                  title={item.label}
                >
                  <Icon
                    size={16}
                    strokeWidth={1.5}
                    className={cn(
                      "shrink-0 transition-colors duration-160",
                      isActive ? "text-[var(--gold-primary)]" : "text-ink-secondary"
                    )}
                  />
                  <span
                    className={cn(
                      "truncate text-[13px] font-medium transition-colors duration-160",
                      isActive ? "text-ink-primary" : "text-ink-secondary",
                      collapsed && "lg:hidden"
                    )}
                  >
                    {item.label}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Divider */}
      <div className="mx-4 h-px bg-[var(--border-subtle)]" />

      {/* Bottom section - User profile */}
      <div className={cn("p-4", collapsed && "lg:px-3")}>
        <button
          onClick={handleSignOut}
          className={cn(
            "flex h-12 w-full items-center gap-3 rounded px-3",
            "transition-all duration-160",
            "hover:bg-[var(--surface-sunken)] cursor-pointer text-left",
            collapsed && "lg:justify-center lg:px-0"
          )}
          title="Clear local access token and reload"
        >
          {/* Avatar */}
          <div className="w-8 h-8 rounded-full bg-ink-tertiary/20 flex items-center justify-center shrink-0">
            <span className="text-[11px] font-medium text-ink-secondary">
              {userName
                .split(" ")
                .map((n) => n[0])
                .join("")}
            </span>
          </div>

          {/* User info */}
          <div className={cn("flex-1 min-w-0", collapsed && "lg:hidden")}>
            <p className="text-[13px] font-medium text-ink-primary truncate">
              {userName}
            </p>
            <p className="eyebrow text-ink-tertiary">{userRole}</p>
          </div>

          {/* Logout icon */}
          <LogOut
            size={14}
            strokeWidth={1.5}
            className={cn(
              "text-ink-tertiary shrink-0 hover:text-ink-secondary transition-colors",
              collapsed && "lg:hidden"
            )}
          />
        </button>

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className={cn(
            "mt-2 flex h-11 w-full items-center justify-between gap-2 rounded px-3 lg:h-10",
            "text-[12px] text-ink-tertiary",
            "transition-all duration-160",
            "hover:bg-[var(--surface-sunken)] hover:text-ink-secondary",
            collapsed && "lg:justify-center lg:px-0"
          )}
          title={theme === "dark" ? "Dark Mode" : "Light Mode"}
        >
          <span className={cn("font-technical uppercase tracking-wider", collapsed && "lg:hidden")}>
            {theme === "dark" ? "Dark Mode" : "Light Mode"}
          </span>
          {theme === "dark" ? (
            <Moon size={14} strokeWidth={1.5} />
          ) : (
            <Sun size={14} strokeWidth={1.5} />
          )}
        </button>
      </div>
    </aside>
  );
}
