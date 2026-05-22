"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Search,
  LayoutList,
  Network,
  Brain,
  BookOpen,
  Shield,
  Users,
  Settings,
  Plus,
  Upload,
  RefreshCw,
  FileText,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface CommandItem {
  id: string;
  icon: React.ElementType;
  label: string;
  description?: string;
  shortcut?: string[];
  action?: () => void;
}

interface CommandCategory {
  id: string;
  label: string;
  items: CommandItem[];
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate?: (route: string) => void;
}

const categories: CommandCategory[] = [
  {
    id: "recent",
    label: "RECENT",
    items: [
      {
        id: "open-operations",
        icon: LayoutList,
        label: "Open Operations Queue",
        shortcut: ["G", "O"],
      },
      {
        id: "open-trace",
        icon: Network,
        label: "Open Trace Inspector",
        shortcut: ["G", "T"],
      },
    ],
  },
  {
    id: "navigation",
    label: "NAVIGATION",
    items: [
      {
        id: "nav-cognition",
        icon: Brain,
        label: "Open Cognition Hub",
        shortcut: ["G", "C"],
      },
      {
        id: "nav-knowledge",
        icon: BookOpen,
        label: "Open Knowledge Base",
        shortcut: ["G", "K"],
      },
      {
        id: "nav-governance",
        icon: Shield,
        label: "Open Governance Console",
        shortcut: ["G", "G"],
      },
      {
        id: "nav-users",
        icon: Users,
        label: "Open User Management",
        shortcut: ["G", "U"],
      },
      {
        id: "nav-settings",
        icon: Settings,
        label: "Open Settings",
        shortcut: ["G", "S"],
      },
    ],
  },
  {
    id: "actions",
    label: "ACTIONS",
    items: [
      {
        id: "new-ticket",
        icon: Plus,
        label: "Create New Ticket",
        shortcut: ["C"],
      },
      {
        id: "upload-doc",
        icon: Upload,
        label: "Upload Document",
        shortcut: ["U"],
      },
      {
        id: "refresh-queue",
        icon: RefreshCw,
        label: "Refresh Queue",
        shortcut: ["R"],
      },
    ],
  },
  {
    id: "search",
    label: "SEARCH",
    items: [
      {
        id: "search-tickets",
        icon: Search,
        label: "Search Tickets",
        description: "by ID or keyword",
        shortcut: ["/"],
      },
      {
        id: "search-docs",
        icon: FileText,
        label: "Search Documents",
        description: "in knowledge base",
      },
    ],
  },
];

export function CommandPalette({ isOpen, onClose, onNavigate }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Filter items based on query
  const filteredCategories = categories
    .map((category) => ({
      ...category,
      items: category.items.filter(
        (item) =>
          item.label.toLowerCase().includes(query.toLowerCase()) ||
          item.description?.toLowerCase().includes(query.toLowerCase())
      ),
    }))
    .filter((category) => category.items.length > 0);

  // Flatten items for keyboard navigation
  const flatItems = filteredCategories.flatMap((cat) => cat.items);

  // Reset selection when query changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [isOpen]);

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current && flatItems.length > 0) {
      const selectedEl = listRef.current.querySelector(`[data-index="${selectedIndex}"]`);
      selectedEl?.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex, flatItems.length]);

  const executeItem = useCallback(
    (item: CommandItem) => {
      // Handle navigation
      if (item.id.startsWith("nav-") || item.id.startsWith("open-")) {
        const routeMap: Record<string, string> = {
          "open-operations": "operations",
          "open-trace": "trace",
          "nav-cognition": "cognition",
          "nav-knowledge": "knowledge",
          "nav-governance": "governance",
          "nav-users": "users",
          "nav-settings": "settings",
        };
        const route = routeMap[item.id];
        if (route && onNavigate) {
          onNavigate(route);
        }
      }
      // Execute custom action if provided
      item.action?.();
      onClose();
    },
    [onClose, onNavigate]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setSelectedIndex((i) => (i < flatItems.length - 1 ? i + 1 : i));
          break;
        case "ArrowUp":
          e.preventDefault();
          setSelectedIndex((i) => (i > 0 ? i - 1 : i));
          break;
        case "Enter":
          e.preventDefault();
          if (flatItems[selectedIndex]) {
            executeItem(flatItems[selectedIndex]);
          }
          break;
        case "Escape":
          e.preventDefault();
          onClose();
          break;
      }
    },
    [flatItems, selectedIndex, executeItem, onClose]
  );

  // Global keyboard shortcut to open
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        // Toggle is handled by parent
      }
    };
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
  }, []);

  if (!isOpen) return null;

  let itemIndex = -1;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[99] bg-[rgba(10,15,28,0.5)] backdrop-blur-[8px]"
        onClick={onClose}
      />

      {/* Modal */}
      <div
        className="fixed left-1/2 top-[20vh] z-[100] w-[640px] max-w-[90vw] -translate-x-1/2 overflow-hidden rounded-[12px] border border-[var(--border-subtle)] bg-[var(--surface)] shadow-[0_24px_64px_rgba(10,15,28,0.16)]"
        onKeyDown={handleKeyDown}
      >
        {/* Search input */}
        <div className="flex h-[56px] items-center gap-3 px-5">
          <Search className="h-4 w-4 shrink-0 text-[var(--ink-tertiary)]" strokeWidth={1.5} />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search actions, tickets, documents..."
            className="flex-1 border-0 bg-transparent font-sans text-[16px] font-normal text-[var(--ink-primary)] placeholder:text-[var(--ink-tertiary)] focus:outline-none"
          />
          <kbd className="rounded border border-[var(--border-subtle)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--ink-tertiary)]">
            ESC
          </kbd>
        </div>

        {/* Divider */}
        <div className="h-px bg-[var(--border-subtle)]" />

        {/* Results list */}
        <div ref={listRef} className="max-h-[480px] overflow-y-auto">
          {filteredCategories.length === 0 ? (
            <div className="px-5 py-8 text-center font-sans text-[13px] text-[var(--ink-tertiary)]">
              No results found for &quot;{query}&quot;
            </div>
          ) : (
            filteredCategories.map((category) => (
              <div key={category.id}>
                {/* Category header */}
                <div className="px-5 pb-2 pt-3 font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)]">
                  {category.label}
                </div>

                {/* Items */}
                {category.items.map((item) => {
                  itemIndex++;
                  const isSelected = itemIndex === selectedIndex;
                  const currentIndex = itemIndex;

                  return (
                    <div
                      key={item.id}
                      data-index={currentIndex}
                      onClick={() => executeItem(item)}
                      onMouseEnter={() => setSelectedIndex(currentIndex)}
                      className={cn(
                        "flex h-[44px] cursor-pointer items-center justify-between px-5",
                        isSelected && "border-l-[3px] border-l-[var(--gold-primary)] bg-[rgba(168,136,44,0.06)]"
                      )}
                    >
                      {/* Left side */}
                      <div className="flex items-center gap-3">
                        <item.icon
                          className="h-4 w-4 text-[var(--ink-secondary)]"
                          strokeWidth={1.5}
                        />
                        <span className="font-sans text-[13px] font-medium text-[var(--ink-primary)]">
                          {item.label}
                        </span>
                        {item.description && (
                          <>
                            <span className="text-[var(--ink-tertiary)]">·</span>
                            <span className="font-sans text-[12px] text-[var(--ink-tertiary)]">
                              {item.description}
                            </span>
                          </>
                        )}
                      </div>

                      {/* Right side - shortcut */}
                      {item.shortcut && (
                        <div className="flex items-center gap-1">
                          {item.shortcut.map((key, i) => (
                            <span key={i}>
                              <kbd className="rounded border border-[var(--border-subtle)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--ink-tertiary)]">
                                {key}
                              </kbd>
                              {i < item.shortcut!.length - 1 && (
                                <span className="mx-1 font-mono text-[11px] text-[var(--ink-tertiary)]">
                                  then
                                </span>
                              )}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer hint */}
        <div className="flex items-center justify-between border-t border-[var(--border-subtle)] px-5 py-3">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <kbd className="rounded border border-[var(--border-subtle)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--ink-tertiary)]">
                ↑
              </kbd>
              <kbd className="rounded border border-[var(--border-subtle)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--ink-tertiary)]">
                ↓
              </kbd>
              <span className="font-sans text-[12px] text-[var(--ink-tertiary)]">to navigate</span>
            </div>
            <div className="flex items-center gap-1.5">
              <kbd className="rounded border border-[var(--border-subtle)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--ink-tertiary)]">
                ↵
              </kbd>
              <span className="font-sans text-[12px] text-[var(--ink-tertiary)]">to select</span>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <kbd className="rounded border border-[var(--border-subtle)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--ink-tertiary)]">
              ⌘
            </kbd>
            <kbd className="rounded border border-[var(--border-subtle)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--ink-tertiary)]">
              K
            </kbd>
            <span className="font-sans text-[12px] text-[var(--ink-tertiary)]">to toggle</span>
          </div>
        </div>
      </div>
    </>
  );
}
