"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import {
  Search,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Eye,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Pause,
} from "lucide-react";

// Status configuration
const statusConfig = {
  running: {
    label: "RUNNING",
    icon: Clock,
    color: "text-blue-system",
    bgColor: "bg-blue-system/10",
    borderColor: "border-blue-system/20",
  },
  escalated: {
    label: "ESCALATED",
    icon: AlertTriangle,
    color: "text-warning-amber",
    bgColor: "bg-[#B8821C]/10",
    borderColor: "border-[#B8821C]/20",
  },
  completed: {
    label: "COMPLETED",
    icon: CheckCircle2,
    color: "text-green-success",
    bgColor: "bg-green-success/10",
    borderColor: "border-green-success/20",
  },
  failed: {
    label: "FAILED",
    icon: XCircle,
    color: "text-red-alert",
    bgColor: "bg-red-alert/10",
    borderColor: "border-red-alert/20",
  },
  paused: {
    label: "PAUSED",
    icon: Pause,
    color: "text-ink-tertiary",
    bgColor: "bg-ink-tertiary/10",
    borderColor: "border-ink-tertiary/20",
  },
} as const;

type Status = keyof typeof statusConfig;

interface Ticket {
  id: string;
  customer: string;
  classification: string;
  status: Status;
  stepsCompleted: number;
  totalSteps: number;
  started: string;
  elapsed: string;
}

// Mock data
const mockTickets: Ticket[] = [
  { id: "TKT-7829", customer: "Delta Freight Co.", classification: "Shipment Delay", status: "running", stepsCompleted: 4, totalSteps: 7, started: "10:42:15", elapsed: "1m 23s" },
  { id: "TKT-7828", customer: "Apex Manufacturing", classification: "Invoice Dispute", status: "escalated", stepsCompleted: 3, totalSteps: 5, started: "10:41:02", elapsed: "2m 36s" },
  { id: "TKT-7827", customer: "Summit Logistics", classification: "Tracking Request", status: "completed", stepsCompleted: 6, totalSteps: 6, started: "10:38:44", elapsed: "3m 54s" },
  { id: "TKT-7826", customer: "Meridian Foods", classification: "Delivery Change", status: "running", stepsCompleted: 2, totalSteps: 4, started: "10:40:18", elapsed: "3m 20s" },
  { id: "TKT-7825", customer: "Coastal Imports", classification: "Customs Inquiry", status: "failed", stepsCompleted: 2, totalSteps: 8, started: "10:35:11", elapsed: "8m 27s" },
  { id: "TKT-7824", customer: "Northern Rail", classification: "Rate Quote", status: "running", stepsCompleted: 5, totalSteps: 6, started: "10:39:55", elapsed: "3m 43s" },
  { id: "TKT-7823", customer: "Pacific Traders", classification: "Shipment Delay", status: "paused", stepsCompleted: 1, totalSteps: 7, started: "10:32:08", elapsed: "11m 30s" },
  { id: "TKT-7822", customer: "Metro Distribution", classification: "Invoice Dispute", status: "completed", stepsCompleted: 5, totalSteps: 5, started: "10:28:33", elapsed: "15m 05s" },
  { id: "TKT-7821", customer: "Allied Shipping", classification: "Tracking Request", status: "running", stepsCompleted: 3, totalSteps: 6, started: "10:41:47", elapsed: "1m 51s" },
  { id: "TKT-7820", customer: "Continental Express", classification: "Delivery Change", status: "escalated", stepsCompleted: 4, totalSteps: 4, started: "10:37:22", elapsed: "6m 16s" },
];

const filterPills = ["All", "Active", "Escalated", "Completed", "Failed"] as const;

interface OperationsQueueProps {
  className?: string;
}

export function OperationsQueue({ className }: OperationsQueueProps) {
  const [activeFilter, setActiveFilter] = useState<string>("All");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());
  const [currentPage, setCurrentPage] = useState(1);

  const handleRefresh = () => {
    setIsRefreshing(true);
    setTimeout(() => setIsRefreshing(false), 600);
  };

  const toggleRowSelection = (id: string) => {
    setSelectedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleAllRows = () => {
    if (selectedRows.size === mockTickets.length) {
      setSelectedRows(new Set());
    } else {
      setSelectedRows(new Set(mockTickets.map((t) => t.id)));
    }
  };

  // Filter tickets based on active filter
  const filteredTickets = mockTickets.filter((ticket) => {
    if (activeFilter === "All") return true;
    if (activeFilter === "Active") return ticket.status === "running" || ticket.status === "paused";
    return ticket.status === activeFilter.toLowerCase();
  });

  return (
    <main className={cn("flex-1 bg-canvas py-8 px-12 overflow-auto", className)}>
      {/* Breadcrumb */}
      <div className="eyebrow text-ink-tertiary mb-2">
        OPERATIONS · LIVE QUEUE
      </div>

      {/* Header row */}
      <div className="flex items-center justify-between">
        <h1 className="font-display font-bold text-[32px] text-ink-primary">
          Operations Queue
        </h1>

        <div className="flex items-center gap-3">
          {/* Filter pills */}
          <div className="flex items-center gap-2">
            {filterPills.map((pill) => (
              <button
                key={pill}
                onClick={() => setActiveFilter(pill)}
                className={cn(
                  "px-3 py-1.5 rounded-full text-[12px] font-medium",
                  "border transition-all duration-160",
                  activeFilter === pill
                    ? "bg-ink-primary text-white border-ink-primary"
                    : "bg-transparent text-ink-secondary border-border-subtle hover:border-border-defined"
                )}
              >
                {pill}
              </button>
            ))}
          </div>

          {/* Search input */}
          <div className="relative">
            <Search
              size={14}
              strokeWidth={1.5}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
            <input
              type="text"
              placeholder="Ticket ID, customer, classification..."
              className={cn(
                "h-9 w-[280px] pl-9 pr-3 rounded",
                "bg-surface border border-border-subtle",
                "text-[13px] text-ink-primary placeholder:text-ink-tertiary",
                "focus:outline-none focus:border-border-defined",
                "transition-colors duration-160"
              )}
            />
          </div>

          {/* Refresh button */}
          <button
            onClick={handleRefresh}
            className={cn(
              "w-9 h-9 flex items-center justify-center rounded",
              "border border-border-subtle bg-surface",
              "hover:border-border-defined transition-all duration-160"
            )}
          >
            <RefreshCw
              size={14}
              strokeWidth={1.5}
              className={cn(
                "text-ink-secondary transition-transform duration-600",
                isRefreshing && "animate-spin"
              )}
            />
          </button>
        </div>
      </div>

      {/* Status summary cards */}
      <div className="mt-6 grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4">
        <SummaryCard label="ACTIVE SESSIONS" value="247" />
        <SummaryCard label="ESCALATIONS PENDING" value="12" valueColor="text-[#B8821C]" />
        <SummaryCard label="AVG RESOLUTION" value="1m 43s" />
        <SummaryCard label="GOVERNANCE DENY RATE" value="2.3%" />
      </div>

      {/* Data table */}
      <div className="mt-8 bg-surface border border-border-subtle rounded-lg overflow-hidden">
        {/* Table header */}
        <div className="h-10 px-4 flex items-center bg-surface-raised border-b border-border-subtle">
          <div className="w-10 flex items-center justify-center">
            <input
              type="checkbox"
              checked={selectedRows.size === mockTickets.length && mockTickets.length > 0}
              onChange={toggleAllRows}
              className="w-3.5 h-3.5 rounded border-border-defined accent-gold cursor-pointer"
            />
          </div>
          <TableHeader className="w-[100px]">TICKET</TableHeader>
          <TableHeader className="flex-1 min-w-[160px]">CUSTOMER</TableHeader>
          <TableHeader className="w-[160px]">CLASSIFICATION</TableHeader>
          <TableHeader className="w-[120px]">STATUS</TableHeader>
          <TableHeader className="w-[140px]">PROGRESS</TableHeader>
          <TableHeader className="w-[100px]">STARTED</TableHeader>
          <TableHeader className="w-[80px]">ELAPSED</TableHeader>
          <TableHeader className="w-[80px] text-right">ACTIONS</TableHeader>
        </div>

        {/* Table body */}
        <div>
          {filteredTickets.map((ticket, index) => (
            <TableRow
              key={ticket.id}
              ticket={ticket}
              isSelected={selectedRows.has(ticket.id)}
              onSelect={() => toggleRowSelection(ticket.id)}
              isOdd={index % 2 === 1}
            />
          ))}
        </div>

        {/* Pagination */}
        <div className="h-12 px-4 flex items-center justify-between border-t border-border-subtle">
          <span className="text-[12px] text-ink-tertiary">
            Showing {filteredTickets.length} of {mockTickets.length} tickets
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
              disabled={currentPage === 1}
              className={cn(
                "w-8 h-8 flex items-center justify-center rounded",
                "border border-border-subtle",
                "disabled:opacity-50 disabled:cursor-not-allowed",
                "hover:border-border-defined transition-colors"
              )}
            >
              <ChevronLeft size={14} strokeWidth={1.5} className="text-ink-secondary" />
            </button>
            <span className="font-technical text-[12px] text-ink-secondary tabular-nums px-2">
              Page {currentPage}
            </span>
            <button
              onClick={() => setCurrentPage(currentPage + 1)}
              className={cn(
                "w-8 h-8 flex items-center justify-center rounded",
                "border border-border-subtle",
                "hover:border-border-defined transition-colors"
              )}
            >
              <ChevronRight size={14} strokeWidth={1.5} className="text-ink-secondary" />
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}

// Summary card component
function SummaryCard({
  label,
  value,
  valueColor = "text-ink-primary",
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="h-24 p-5 bg-surface border border-border-subtle rounded-lg flex flex-col gap-2">
      <span className="eyebrow text-ink-tertiary">{label}</span>
      <span className={cn("font-technical font-medium text-[32px] tabular-nums", valueColor)}>
        {value}
      </span>
    </div>
  );
}

// Table header component
function TableHeader({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("eyebrow text-ink-tertiary px-2", className)}>
      {children}
    </div>
  );
}

// Table row component
function TableRow({
  ticket,
  isSelected,
  onSelect,
  isOdd,
}: {
  ticket: Ticket;
  isSelected: boolean;
  onSelect: () => void;
  isOdd: boolean;
}) {
  const status = statusConfig[ticket.status];
  const StatusIcon = status.icon;
  const progressPercent = (ticket.stepsCompleted / ticket.totalSteps) * 100;

  return (
    <div
      className={cn(
        "h-12 px-4 flex items-center",
        "border-b border-border-subtle last:border-b-0",
        "transition-colors duration-160",
        isOdd ? "bg-canvas/50" : "bg-surface",
        "hover:bg-[var(--surface-sunken)]"
      )}
    >
      {/* Checkbox */}
      <div className="w-10 flex items-center justify-center">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onSelect}
          className="w-3.5 h-3.5 rounded border-border-defined accent-gold cursor-pointer"
        />
      </div>

      {/* Ticket ID */}
      <div className="w-[100px] px-2">
        <span className="font-technical text-[13px] font-medium text-blue-system tabular-nums">
          {ticket.id}
        </span>
      </div>

      {/* Customer */}
      <div className="flex-1 min-w-[160px] px-2">
        <span className="text-[13px] text-ink-primary truncate">{ticket.customer}</span>
      </div>

      {/* Classification */}
      <div className="w-[160px] px-2">
        <span className="text-[13px] text-ink-secondary">{ticket.classification}</span>
      </div>

      {/* Status badge */}
      <div className="w-[120px] px-2">
        <div
          className={cn(
            "inline-flex items-center gap-1.5 px-2 py-1 rounded",
            status.bgColor,
            "border",
            status.borderColor
          )}
        >
          <StatusIcon size={12} strokeWidth={1.5} className={status.color} />
          <span className={cn("font-technical text-[10px] font-medium tracking-wider", status.color)}>
            {status.label}
          </span>
        </div>
      </div>

      {/* Progress */}
      <div className="w-[140px] px-2 flex items-center gap-2">
        <div className="flex-1 h-1.5 bg-border-subtle rounded-full overflow-hidden">
          <div
            className="h-full bg-gold transition-all duration-300"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <span className="font-technical text-[11px] text-ink-tertiary tabular-nums">
          {ticket.stepsCompleted}/{ticket.totalSteps}
        </span>
      </div>

      {/* Started */}
      <div className="w-[100px] px-2">
        <span className="font-technical text-[12px] text-ink-secondary tabular-nums">
          {ticket.started}
        </span>
      </div>

      {/* Elapsed */}
      <div className="w-[80px] px-2">
        <span className="font-technical text-[12px] text-ink-secondary tabular-nums">
          {ticket.elapsed}
        </span>
      </div>

      {/* Actions */}
      <div className="w-[80px] px-2 flex justify-end">
        <button
          className={cn(
            "w-7 h-7 flex items-center justify-center rounded",
            "border border-border-subtle",
            "hover:border-border-defined hover:bg-surface-raised",
            "transition-all duration-160"
          )}
        >
          <Eye size={14} strokeWidth={1.5} className="text-ink-secondary" />
        </button>
      </div>
    </div>
  );
}
