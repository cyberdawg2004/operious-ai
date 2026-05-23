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
  onNavigate?: (itemId: string) => void;
  tenantName?: string;
  userName?: string;
  userRole?: string;
  onTenantClick?: () => void;
  className?: string;
}

export function Sidebar({
  activeItem = "operations",
  onNavigate,
  tenantName = "Tenant scope not configured",
  userName = "Unverified operator",
  userRole = "Principal scope not configured",
  onTenantClick,
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
        "w-[240px] h-screen flex flex-col shrink-0",
        "bg-[var(--surface-raised)] border-r border-[var(--border-subtle)]",
        className
      )}
    >
      {/* Top section - Logo and tenant selector */}
      <div className="p-6">
        <Logo
          className="h-9 w-auto text-ink-primary"
          height={36}
          tone={theme === "dark" ? "dark" : "light"}
          width={148}
        />

        {/* Tenant selector */}
        <button
          onClick={onTenantClick}
          className={cn(
            "mt-6 w-full flex items-center gap-2 px-3 py-2",
            "border border-[var(--border-subtle)] rounded",
            "transition-all duration-160",
            "hover:bg-[var(--surface)] hover:border-[var(--border-defined)]"
          )}
        >
          <Building2 
            size={14} 
            strokeWidth={1.5} 
            className="text-ink-tertiary shrink-0" 
          />
          <span className="text-[13px] font-medium text-ink-primary flex-1 text-left truncate">
            {tenantName}
          </span>
          <ChevronDown 
            size={12} 
            strokeWidth={1.5} 
            className="text-ink-tertiary shrink-0" 
          />
        </button>
      </div>

      {/* Navigation section */}
      <nav className="flex-1 overflow-y-auto px-4 py-4">
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
                    "w-full h-9 flex items-center gap-3 rounded",
                    "transition-all duration-160",
                    isActive
                      ? "bg-[var(--gold-bg)] border-l-4 border-l-[var(--gold-primary)] pl-2 pr-3"
                      : "px-3",
                    !isActive && isHovered && "bg-[var(--surface-sunken)]"
                  )}
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
                      "text-[13px] font-medium transition-colors duration-160",
                      isActive ? "text-ink-primary" : "text-ink-secondary"
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
      <div className="p-4">
        <button
          onClick={handleSignOut}
          className={cn(
            "w-full flex items-center gap-3 px-3 py-2 rounded",
            "transition-all duration-160",
            "hover:bg-[var(--surface-sunken)] cursor-pointer text-left"
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
          <div className="flex-1 min-w-0">
            <p className="text-[13px] font-medium text-ink-primary truncate">
              {userName}
            </p>
            <p className="eyebrow text-ink-tertiary">{userRole}</p>
          </div>

          {/* Logout icon */}
          <LogOut
            size={14}
            strokeWidth={1.5}
            className="text-ink-tertiary shrink-0 hover:text-ink-secondary transition-colors"
          />
        </button>

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className={cn(
            "mt-2 w-full flex items-center justify-between gap-2 px-3 py-2 rounded",
            "text-[12px] text-ink-tertiary",
            "transition-all duration-160",
            "hover:bg-[var(--surface-sunken)] hover:text-ink-secondary"
          )}
        >
          <span className="font-technical uppercase tracking-wider">
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
