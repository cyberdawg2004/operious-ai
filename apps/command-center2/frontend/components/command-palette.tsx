"use client";

import { useState, useEffect, useRef } from "react";
import {
  Activity,
  AlertTriangle,
  Search,
  LayoutList,
  Network,
  Brain,
  BookOpen,
  Shield,
  Users,
  Settings,
  FileText,
  Radio,
  GitBranch,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface CommandItem {
  id: string;
  icon: React.ElementType;
  label: string;
  description?: string;
  shortcut?: string[];
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
        id: "open-queue-status",
        icon: Activity,
        label: "Open Queue Status",
        shortcut: ["G", "Q"],
      },
      {
        id: "open-dlq-inspector",
        icon: AlertTriangle,
        label: "Open DLQ Inspector",
        shortcut: ["G", "D"],
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
        id: "nav-topology",
        icon: GitBranch,
        label: "Open Topology",
        shortcut: ["G", "Y"],
      },
      {
        id: "nav-channels",
        icon: Radio,
        label: "Open Channels",
        shortcut: ["G", "H"],
      },
      {
        id: "nav-team",
        icon: Users,
        label: "Open Team & Roles",
        shortcut: ["G", "U"],
      },
      {
        id: "nav-audit",
        icon: FileText,
        label: "Open Audit & Exports",
        shortcut: ["G", "A"],
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

  const flatItems = filteredCategories.flatMap((cat) => cat.items);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [isOpen]);

  useEffect(() => {
    if (listRef.current && flatItems.length > 0) {
      const selectedEl = listRef.current.querySelector(`[data-index="${selectedIndex}"]`);
      selectedEl?.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex, flatItems.length]);

  function executeItem(item: CommandItem) {
    const routeMap: Record<string, string> = {
      "open-operations": "operations",
      "open-queue-status": "queue-status",
      "open-dlq-inspector": "dlq-inspector",
      "open-trace": "trace",
      "nav-cognition": "cognition",
      "nav-knowledge": "knowledge",
      "nav-governance": "governance",
      "nav-topology": "topology",
      "nav-channels": "channels",
      "nav-team": "team",
      "nav-audit": "audit",
      "nav-settings": "settings",
      "search-tickets": "operations",
      "search-docs": "knowledge",
    };
    const route = routeMap[item.id];
    if (route && onNavigate) {
      onNavigate(route);
    }
    onClose();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
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
  }

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
        className="fixed left-1/2 top-[8vh] z-[100] max-h-[86dvh] w-[calc(100vw-32px)] max-w-[640px] -translate-x-1/2 overflow-hidden rounded-[12px] border border-[var(--border-subtle)] bg-[var(--surface)] shadow-[0_24px_64px_rgba(10,15,28,0.16)] sm:top-[20vh]"
        onKeyDown={handleKeyDown}
      >
        {/* Search input */}
        <div className="flex h-[56px] items-center gap-3 px-5">
          <Search className="h-4 w-4 shrink-0 text-[var(--ink-tertiary)]" strokeWidth={1.5} />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
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
        <div ref={listRef} className="max-h-[calc(86dvh-150px)] overflow-y-auto sm:max-h-[480px]">
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
                        isSelected && "border-l-[3px] border-l-[var(--gold-primary)] bg-[var(--gold-bg)]"
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
        <div className="flex flex-col gap-3 border-t border-[var(--border-subtle)] px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-4">
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
