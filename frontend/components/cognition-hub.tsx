"use client";

import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Check,
  X,
  FileText,
  MessageSquare,
  TrendingUp,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";

type ApprovalStatus = "pending" | "approved" | "rejected" | "applied";
type FilterStatus = "all" | ApprovalStatus;

interface EvidenceItem {
  id: string;
  type: "ticket" | "feedback" | "pattern";
  title: string;
  excerpt: string;
  date: string;
}

interface ApprovalRecord {
  id: string;
  status: ApprovalStatus;
  confidence: number;
  title: string;
  affectedDocument: {
    name: string;
    version: string;
  };
  proposedChange: {
    oldText: string;
    newText: string;
  };
  evidence: EvidenceItem[];
  createdAt: string;
}

const mockRecords: ApprovalRecord[] = [
  {
    id: "AR-001",
    status: "pending",
    confidence: 87,
    title: "Update charging issue resolution to include cable replacement path for power adapter complaints",
    affectedDocument: {
      name: "sop_charging_v4_anker.md",
      version: "v4.2",
    },
    proposedChange: {
      oldText: "If the device does not charge, verify the outlet is functional and try a different cable.",
      newText: "If the device does not charge, verify the outlet is functional, try a different cable, and if using a third-party power adapter, recommend replacing with OEM adapter as a resolution path.",
    },
    evidence: [
      {
        id: "TKT-4521",
        type: "ticket",
        title: "Customer unable to charge device with third-party adapter",
        excerpt: "Customer reported device not charging. After troubleshooting, replacing third-party adapter with OEM resolved the issue.",
        date: "2024-01-15",
      },
      {
        id: "TKT-4533",
        type: "ticket",
        title: "Charging failure with non-branded cable",
        excerpt: "Multiple attempts to charge failed until customer switched to original equipment manufacturer cable.",
        date: "2024-01-16",
      },
      {
        id: "PAT-012",
        type: "pattern",
        title: "Third-party adapter correlation detected",
        excerpt: "23% of charging issues in the last 30 days involved third-party adapters. OEM replacement resolved 94% of these cases.",
        date: "2024-01-17",
      },
    ],
    createdAt: "2024-01-17T14:30:00Z",
  },
  {
    id: "AR-002",
    status: "pending",
    confidence: 92,
    title: "Add firmware update step to Bluetooth connectivity troubleshooting flow",
    affectedDocument: {
      name: "sop_bluetooth_pairing.md",
      version: "v2.1",
    },
    proposedChange: {
      oldText: "Reset Bluetooth settings and attempt to pair the device again.",
      newText: "Check for firmware updates first. If available, install update and restart device. Then reset Bluetooth settings and attempt to pair the device again.",
    },
    evidence: [
      {
        id: "TKT-4498",
        type: "ticket",
        title: "Bluetooth pairing fails after OS update",
        excerpt: "Customer experienced pairing issues post-OS update. Firmware update resolved connectivity.",
        date: "2024-01-14",
      },
      {
        id: "FBK-221",
        type: "feedback",
        title: "Agent feedback on Bluetooth resolution",
        excerpt: "Firmware updates should be checked earlier in the flow - would have saved 15 minutes on this call.",
        date: "2024-01-15",
      },
    ],
    createdAt: "2024-01-16T09:15:00Z",
  },
  {
    id: "AR-003",
    status: "approved",
    confidence: 95,
    title: "Include battery health check in power-related troubleshooting",
    affectedDocument: {
      name: "sop_power_issues.md",
      version: "v3.0",
    },
    proposedChange: {
      oldText: "Verify the power button is functioning correctly.",
      newText: "Verify the power button is functioning correctly. Check battery health status in device settings - if below 80%, recommend battery service.",
    },
    evidence: [
      {
        id: "TKT-4412",
        type: "ticket",
        title: "Device shutting down unexpectedly",
        excerpt: "Battery health at 67% was causing random shutdowns. Battery replacement resolved issue.",
        date: "2024-01-12",
      },
    ],
    createdAt: "2024-01-14T11:00:00Z",
  },
  {
    id: "AR-004",
    status: "rejected",
    confidence: 61,
    title: "Skip verification step for returning customers with purchase history",
    affectedDocument: {
      name: "sop_identity_verification.md",
      version: "v1.8",
    },
    proposedChange: {
      oldText: "Verify customer identity using two-factor authentication for all support requests.",
      newText: "For customers with verified purchase history in the last 90 days, single-factor verification is sufficient.",
    },
    evidence: [
      {
        id: "FBK-198",
        type: "feedback",
        title: "Agent suggestion for faster verification",
        excerpt: "Repeat customers find 2FA frustrating. Could we streamline for known accounts?",
        date: "2024-01-10",
      },
    ],
    createdAt: "2024-01-11T16:45:00Z",
  },
  {
    id: "AR-005",
    status: "applied",
    confidence: 89,
    title: "Add screen calibration step to display troubleshooting",
    affectedDocument: {
      name: "sop_display_issues.md",
      version: "v2.5",
    },
    proposedChange: {
      oldText: "If display colors appear incorrect, restart the device.",
      newText: "If display colors appear incorrect, access Display Settings > Calibration and run the auto-calibration tool. If issue persists, restart the device.",
    },
    evidence: [
      {
        id: "TKT-4389",
        type: "ticket",
        title: "Colors washed out after software update",
        excerpt: "Auto-calibration resolved color accuracy issues without need for restart.",
        date: "2024-01-08",
      },
      {
        id: "TKT-4401",
        type: "ticket",
        title: "Display tint issue",
        excerpt: "Screen had yellow tint. Calibration tool fixed within 30 seconds.",
        date: "2024-01-09",
      },
    ],
    createdAt: "2024-01-10T10:30:00Z",
  },
  {
    id: "AR-006",
    status: "pending",
    confidence: 78,
    title: "Recommend network reset before escalating connectivity issues",
    affectedDocument: {
      name: "sop_network_connectivity.md",
      version: "v4.1",
    },
    proposedChange: {
      oldText: "If connectivity issues persist after basic troubleshooting, escalate to Tier 2 support.",
      newText: "If connectivity issues persist after basic troubleshooting, perform a full network settings reset. If issue continues after reset, escalate to Tier 2 support.",
    },
    evidence: [
      {
        id: "TKT-4556",
        type: "ticket",
        title: "Intermittent WiFi disconnections",
        excerpt: "Network reset resolved persistent WiFi issues that would have otherwise been escalated.",
        date: "2024-01-17",
      },
      {
        id: "PAT-015",
        type: "pattern",
        title: "Escalation reduction opportunity",
        excerpt: "42% of Tier 2 network escalations in past month could have been resolved with network reset.",
        date: "2024-01-18",
      },
    ],
    createdAt: "2024-01-18T08:00:00Z",
  },
];

const filterOptions: { id: FilterStatus; label: string }[] = [
  { id: "all", label: "All" },
  { id: "pending", label: "Pending" },
  { id: "approved", label: "Approved" },
  { id: "rejected", label: "Rejected" },
  { id: "applied", label: "Applied" },
];

const sortOptions = [
  { id: "confidence", label: "Confidence" },
  { id: "age", label: "Age" },
  { id: "evidence", label: "Evidence count" },
];

function getStatusConfig(status: ApprovalStatus) {
  switch (status) {
    case "pending":
      return {
        label: "PENDING REVIEW",
        className: "border-[var(--warning-amber)] text-[var(--warning-amber)] bg-[var(--warning-amber)]/10",
      };
    case "approved":
      return {
        label: "APPROVED",
        className: "border-[var(--green-success)] text-[var(--green-success)] bg-[var(--green-success)]/10",
      };
    case "rejected":
      return {
        label: "REJECTED",
        className: "border-[var(--red-alert)] text-[var(--red-alert)] bg-[var(--red-alert)]/10",
      };
    case "applied":
      return {
        label: "APPLIED",
        className: "border-[var(--gold-primary)] text-[var(--gold-primary)] bg-[var(--gold-primary)]/10",
      };
  }
}

function getEvidenceIcon(type: EvidenceItem["type"]) {
  switch (type) {
    case "ticket":
      return FileText;
    case "feedback":
      return MessageSquare;
    case "pattern":
      return TrendingUp;
  }
}

function ApprovalCard({ record }: { record: ApprovalRecord }) {
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null);
  const statusConfig = getStatusConfig(record.status);

  return (
    <div className="bg-[var(--surface)] border border-[var(--border-subtle)] rounded-lg p-6 flex flex-col gap-4">
      {/* Header Row */}
      <div className="flex items-center justify-between">
        <span
          className={cn(
            "px-2.5 py-1 border rounded-full font-mono text-[10px] uppercase tracking-[0.08em]",
            statusConfig.className
          )}
        >
          {statusConfig.label}
        </span>
        <span className="font-mono text-[13px] font-medium tabular-nums text-[var(--ink-secondary)]">
          {record.confidence}% confidence
        </span>
      </div>

      {/* Title */}
      <h3 className="font-serif font-semibold text-lg leading-[1.3] text-[var(--ink-primary)]">
        {record.title}
      </h3>

      {/* Affected Document */}
      <div>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-1">
          AFFECTED DOCUMENT
        </span>
        <a
          href="#"
          className="font-mono text-[13px] text-[var(--gold-primary)] hover:underline"
        >
          {record.affectedDocument.name} ({record.affectedDocument.version})
        </a>
      </div>

      {/* Proposed Change */}
      <div>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-2">
          PROPOSED CHANGE
        </span>
        <div className="border border-[var(--border-subtle)] rounded bg-[var(--surface-raised)] p-3 space-y-2">
          <p className="font-mono text-[12px] leading-relaxed text-[var(--red-alert)]/60 line-through">
            {record.proposedChange.oldText}
          </p>
          <p className="font-mono text-[12px] leading-relaxed text-[var(--green-success)]">
            {record.proposedChange.newText}
          </p>
        </div>
      </div>

      {/* Evidence Section */}
      <div>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-2">
          SUPPORTING EVIDENCE ({record.evidence.length})
        </span>
        <div className="space-y-2">
          {record.evidence.map((item) => {
            const Icon = getEvidenceIcon(item.type);
            const isExpanded = expandedEvidence === item.id;

            return (
              <div
                key={item.id}
                className="border border-[var(--border-subtle)] rounded bg-[var(--surface-raised)]"
              >
                <button
                  onClick={() => setExpandedEvidence(isExpanded ? null : item.id)}
                  className="w-full flex items-center gap-3 p-3 text-left hover:bg-[var(--surface-hover)] transition-colors duration-160"
                >
                  {isExpanded ? (
                    <ChevronDown className="w-4 h-4 text-[var(--ink-tertiary)] flex-shrink-0" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-[var(--ink-tertiary)] flex-shrink-0" />
                  )}
                  <Icon className="w-4 h-4 text-[var(--gold-primary)] flex-shrink-0" />
                  <span className="font-mono text-[12px] text-[var(--ink-secondary)] truncate flex-1">
                    {item.id}: {item.title}
                  </span>
                  <span className="font-mono text-[10px] text-[var(--ink-tertiary)] flex-shrink-0">
                    {item.date}
                  </span>
                </button>
                {isExpanded && (
                  <div className="px-3 pb-3 pt-0">
                    <p className="font-mono text-[11px] leading-relaxed text-[var(--ink-secondary)] pl-7">
                      {item.excerpt}
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Action Buttons */}
      {record.status === "pending" && (
        <div className="flex items-center gap-3 pt-2 border-t border-[var(--border-subtle)]">
          <button className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-[var(--green-success)] text-white rounded font-mono text-[12px] uppercase tracking-[0.08em] hover:bg-[var(--green-success)]/90 transition-colors duration-160">
            <Check className="w-4 h-4" strokeWidth={1.5} />
            Approve
          </button>
          <button className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-transparent border border-[var(--red-alert)] text-[var(--red-alert)] rounded font-mono text-[12px] uppercase tracking-[0.08em] hover:bg-[var(--red-alert)]/10 transition-colors duration-160">
            <X className="w-4 h-4" strokeWidth={1.5} />
            Reject
          </button>
        </div>
      )}

      {/* Timestamp */}
      <div className="flex items-center gap-2 text-[var(--ink-tertiary)]">
        <Clock className="w-3 h-3" strokeWidth={1.5} />
        <span className="font-mono text-[10px]">
          Created {new Date(record.createdAt).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
    </div>
  );
}

export function CognitionHub() {
  const [activeFilter, setActiveFilter] = useState<FilterStatus>("all");
  const [sortBy, setSortBy] = useState("confidence");
  const [showSortDropdown, setShowSortDropdown] = useState(false);

  const filteredRecords = mockRecords.filter((record) => {
    if (activeFilter === "all") return true;
    return record.status === activeFilter;
  });

  const sortedRecords = [...filteredRecords].sort((a, b) => {
    switch (sortBy) {
      case "confidence":
        return b.confidence - a.confidence;
      case "age":
        return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
      case "evidence":
        return b.evidence.length - a.evidence.length;
      default:
        return 0;
    }
  });

  const stats = {
    pending: mockRecords.filter((r) => r.status === "pending").length,
    approvedThisWeek: mockRecords.filter((r) => r.status === "approved").length,
    appliedThisMonth: mockRecords.filter((r) => r.status === "applied").length,
    avgConfidence: Math.round(
      mockRecords.reduce((acc, r) => acc + r.confidence, 0) / mockRecords.length
    ),
  };

  return (
    <div className="flex-1 bg-[var(--canvas)] py-8 px-12 overflow-auto">
      {/* Header */}
      <div className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)]">
          COGNITION · APPROVAL QUEUE
        </span>
      </div>

      {/* Title Row */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-serif font-bold text-[32px] text-[var(--ink-primary)]">
          Cognition Hub
        </h1>
        <div className="flex items-center gap-4">
          {/* Filter Pills */}
          <div className="flex items-center gap-1 p-1 bg-[var(--surface)] rounded-lg border border-[var(--border-subtle)]">
            {filterOptions.map((option) => (
              <button
                key={option.id}
                onClick={() => setActiveFilter(option.id)}
                className={cn(
                  "px-3 py-1.5 rounded font-mono text-[11px] uppercase tracking-[0.08em] transition-colors duration-160",
                  activeFilter === option.id
                    ? "bg-[var(--gold-primary)] text-white"
                    : "text-[var(--ink-secondary)] hover:bg-[var(--surface-hover)]"
                )}
              >
                {option.label}
              </button>
            ))}
          </div>

          {/* Sort Dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowSortDropdown(!showSortDropdown)}
              className="flex items-center gap-2 px-3 py-2 bg-[var(--surface)] border border-[var(--border-subtle)] rounded font-mono text-[11px] text-[var(--ink-secondary)] hover:bg-[var(--surface-hover)] transition-colors duration-160"
            >
              Sort: {sortOptions.find((o) => o.id === sortBy)?.label}
              <ChevronDown className="w-3 h-3" />
            </button>
            {showSortDropdown && (
              <div className="absolute top-full right-0 mt-1 w-40 bg-[var(--surface)] border border-[var(--border-subtle)] rounded shadow-lg z-10">
                {sortOptions.map((option) => (
                  <button
                    key={option.id}
                    onClick={() => {
                      setSortBy(option.id);
                      setShowSortDropdown(false);
                    }}
                    className={cn(
                      "w-full px-3 py-2 text-left font-mono text-[11px] hover:bg-[var(--surface-hover)] transition-colors duration-160",
                      sortBy === option.id
                        ? "text-[var(--gold-primary)]"
                        : "text-[var(--ink-secondary)]"
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Summary Strip */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <div className="bg-[var(--surface)] border border-[var(--border-subtle)] rounded-lg p-4">
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-1">
            PENDING REVIEW
          </span>
          <span className="font-mono text-[28px] font-semibold tabular-nums text-[var(--ink-primary)]">
            {stats.pending}
          </span>
        </div>
        <div className="bg-[var(--surface)] border border-[var(--border-subtle)] rounded-lg p-4">
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-1">
            APPROVED THIS WEEK
          </span>
          <span className="font-mono text-[28px] font-semibold tabular-nums text-[var(--ink-primary)]">
            {stats.approvedThisWeek}
          </span>
        </div>
        <div className="bg-[var(--surface)] border border-[var(--border-subtle)] rounded-lg p-4">
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-1">
            APPLIED THIS MONTH
          </span>
          <span className="font-mono text-[28px] font-semibold tabular-nums text-[var(--ink-primary)]">
            {stats.appliedThisMonth}
          </span>
        </div>
        <div className="bg-[var(--surface)] border border-[var(--border-subtle)] rounded-lg p-4">
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-1">
            AVERAGE CONFIDENCE
          </span>
          <span className="font-mono text-[28px] font-semibold tabular-nums text-[var(--ink-primary)]">
            {stats.avgConfidence}%
          </span>
        </div>
      </div>

      {/* Card Grid */}
      <div className="grid grid-cols-2 gap-6">
        {sortedRecords.map((record) => (
          <ApprovalCard key={record.id} record={record} />
        ))}
      </div>

      {sortedRecords.length === 0 && (
        <div className="text-center py-16">
          <p className="font-mono text-[13px] text-[var(--ink-tertiary)]">
            No records found for the selected filter.
          </p>
        </div>
      )}
    </div>
  );
}
