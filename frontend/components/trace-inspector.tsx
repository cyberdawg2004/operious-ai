"use client";

import { useState } from "react";
import {
  Search,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  Shield,
  MessageSquare,
  Cpu,
  FileText,
  ChevronRight,
  Copy,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Substrate color mapping
const substrateColors = {
  INGEST: "#3B82F6", // Blue
  NLU: "#8B5CF6", // Purple
  POLICY: "#B8821C", // Amber (warning)
  RETRIEVAL: "#06B6D4", // Cyan
  GENERATION: "#EC4899", // Pink
  REVIEW: "#F97316", // Orange
  DISPATCH: "#10B981", // Emerald
  AUDIT: "#6B7280", // Gray
} as const;

type SubstrateType = keyof typeof substrateColors;

interface TimelineEvent {
  id: string;
  timestamp: string;
  substrate: SubstrateType;
  action: string;
  status: "success" | "warning" | "error";
  duration: string;
  details: {
    input?: string;
    output?: string;
    model?: string;
    tokens?: number;
    confidence?: number;
    policyId?: string;
    decision?: string;
  };
}

const mockEvents: TimelineEvent[] = [
  {
    id: "evt-001",
    timestamp: "14:32:01.042",
    substrate: "INGEST",
    action: "Email received and parsed",
    status: "success",
    duration: "124ms",
    details: {
      input: "Raw email payload (2.4KB)",
      output: "Structured message object",
    },
  },
  {
    id: "evt-002",
    timestamp: "14:32:01.166",
    substrate: "NLU",
    action: "Intent classification",
    status: "success",
    duration: "89ms",
    details: {
      model: "intent-classifier-v3",
      confidence: 0.94,
      output: "REFUND_REQUEST",
    },
  },
  {
    id: "evt-003",
    timestamp: "14:32:01.255",
    substrate: "POLICY",
    action: "Policy chain evaluation",
    status: "warning",
    duration: "203ms",
    details: {
      policyId: "POL-RFD-V3",
      decision: "ALLOW_WITH_REVIEW",
      output: "Amount exceeds auto-approve threshold",
    },
  },
  {
    id: "evt-004",
    timestamp: "14:32:01.458",
    substrate: "RETRIEVAL",
    action: "Knowledge base query",
    status: "success",
    duration: "156ms",
    details: {
      input: "refund policy electronics 30 days",
      output: "3 relevant documents retrieved",
      tokens: 1247,
    },
  },
  {
    id: "evt-005",
    timestamp: "14:32:01.614",
    substrate: "GENERATION",
    action: "Response draft created",
    status: "success",
    duration: "892ms",
    details: {
      model: "gpt-4-turbo",
      tokens: 342,
      output: "Draft response generated",
    },
  },
  {
    id: "evt-006",
    timestamp: "14:32:02.506",
    substrate: "REVIEW",
    action: "Human review requested",
    status: "warning",
    duration: "45.2s",
    details: {
      output: "Escalated to L2 agent",
    },
  },
  {
    id: "evt-007",
    timestamp: "14:33:17.721",
    substrate: "REVIEW",
    action: "Review completed - approved",
    status: "success",
    duration: "—",
    details: {
      output: "Agent approved with minor edits",
    },
  },
  {
    id: "evt-008",
    timestamp: "14:33:17.892",
    substrate: "DISPATCH",
    action: "Response sent to customer",
    status: "success",
    duration: "67ms",
    details: {
      output: "Email dispatched via SendGrid",
    },
  },
  {
    id: "evt-009",
    timestamp: "14:33:17.959",
    substrate: "AUDIT",
    action: "Trace finalized",
    status: "success",
    duration: "12ms",
    details: {
      output: "Immutable record created",
    },
  },
];

const StatusIcon = ({ status }: { status: TimelineEvent["status"] }) => {
  switch (status) {
    case "success":
      return <CheckCircle2 className="w-4 h-4 text-green-success" />;
    case "warning":
      return <AlertTriangle className="w-4 h-4 text-warning-amber" />;
    case "error":
      return <XCircle className="w-4 h-4 text-red-alert" />;
  }
};

export function TraceInspector() {
  const [traceLoaded, setTraceLoaded] = useState(true);
  const [searchValue, setSearchValue] = useState("TKT-2026-08842");
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent | null>(
    mockEvents[2]
  );

  const handleOpenTrace = () => {
    if (searchValue.trim()) {
      setTraceLoaded(true);
    }
  };

  return (
    <div
      className="flex-1 min-h-screen py-8 px-12"
      style={{ backgroundColor: "var(--canvas)" }}
    >
      {/* Header Strip */}
      <div className="mb-8">
        {/* Breadcrumb */}
        <div
          className="font-mono text-[11px] uppercase tracking-[0.18em] mb-2"
          style={{ color: "var(--gold-primary)" }}
        >
          TRACE · INSPECTOR
        </div>

        {/* Title Row */}
        <div className="flex items-center justify-between">
          <h1
            className="font-display text-[32px] font-bold"
            style={{ color: "var(--ink-primary)" }}
          >
            Trace Inspector
          </h1>

          {/* Search + Button */}
          <div className="flex items-center gap-3">
            <div className="relative">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5"
                style={{ color: "var(--ink-tertiary)" }}
              />
              <input
                type="text"
                placeholder="Ticket ID or Session ID..."
                value={searchValue}
                onChange={(e) => setSearchValue(e.target.value)}
                className="w-[300px] h-9 pl-9 pr-4 rounded font-sans text-[13px] outline-none transition-all duration-160"
                style={{
                  backgroundColor: "var(--surface-raised)",
                  border: "1px solid var(--border-subtle)",
                  color: "var(--ink-primary)",
                }}
                onFocus={(e) =>
                  (e.target.style.borderColor = "var(--gold-primary)")
                }
                onBlur={(e) =>
                  (e.target.style.borderColor = "var(--border-subtle)")
                }
                onKeyDown={(e) => e.key === "Enter" && handleOpenTrace()}
              />
            </div>
            <button
              onClick={handleOpenTrace}
              className="h-9 px-4 rounded font-sans text-[13px] font-medium text-white transition-opacity duration-160 hover:opacity-90"
              style={{ backgroundColor: "var(--ink-primary)" }}
            >
              Open Trace
            </button>
          </div>
        </div>
      </div>

      {/* Empty State */}
      {!traceLoaded && (
        <div className="flex items-center justify-center" style={{ height: "calc(100vh - 200px)" }}>
          <p
            className="font-display italic text-[24px] text-center max-w-[600px]"
            style={{ color: "var(--ink-tertiary)" }}
          >
            Enter a Ticket ID or Session ID to reconstruct its operational trace.
          </p>
        </div>
      )}

      {/* Loaded State */}
      {traceLoaded && (
        <>
          {/* Metadata Strip */}
          <div
            className="flex items-stretch rounded-lg p-4 mb-6"
            style={{
              backgroundColor: "var(--surface-raised)",
              border: "1px solid var(--border-subtle)",
            }}
          >
            <MetadataField label="TICKET ID" value="TKT-2026-08842" mono />
            <Divider />
            <MetadataField label="TENANT" value="Anker Innovations" />
            <Divider />
            <MetadataField label="CHANNEL" value="Email" />
            <Divider />
            <MetadataField
              label="STATUS"
              value={
                <span
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium uppercase"
                  style={{
                    backgroundColor: "rgba(22, 163, 74, 0.1)",
                    color: "var(--green-success)",
                  }}
                >
                  RESOLVED
                </span>
              }
            />
            <Divider />
            <MetadataField label="TOTAL EVENTS" value="47" mono />
            <Divider />
            <MetadataField
              label="TRACE INTEGRITY"
              value={
                <span className="flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: "var(--green-success)" }}
                  />
                  <span className="font-mono text-[13px] font-medium" style={{ color: "var(--ink-primary)" }}>
                    VALID
                  </span>
                </span>
              }
            />
            <Divider />
            <MetadataField label="DURATION" value="2m 14s" mono />
            <Divider />
            <MetadataField label="POLICY CHAIN" value="POL-RFD-V3" mono />
          </div>

          {/* Two-Pane Layout */}
          <div className="flex gap-6">
            {/* Left Pane - Timeline Graph */}
            <div
              className="w-[60%] rounded-lg p-6"
              style={{
                backgroundColor: "var(--surface-raised)",
                border: "1px solid var(--border-subtle)",
                minHeight: "600px",
              }}
            >
              {/* Timeline Header */}
              <div
                className="font-mono text-[11px] uppercase tracking-[0.18em] mb-4"
                style={{ color: "var(--ink-tertiary)" }}
              >
                OPERATIONAL TIMELINE
              </div>

              {/* Color Legend */}
              <div className="flex flex-wrap gap-4 mb-6 pb-4" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                {Object.entries(substrateColors).map(([name, color]) => (
                  <div key={name} className="flex items-center gap-1.5">
                    <span
                      className="w-2.5 h-2.5 rounded-full"
                      style={{ backgroundColor: color }}
                    />
                    <span
                      className="font-mono text-[11px] uppercase"
                      style={{ color: "var(--ink-secondary)" }}
                    >
                      {name}
                    </span>
                  </div>
                ))}
              </div>

              {/* Timeline */}
              <div className="relative">
                {/* Vertical Line */}
                <div
                  className="absolute left-[60px] top-0 bottom-0 w-px"
                  style={{ backgroundColor: "var(--border-subtle)" }}
                />

                {/* Events */}
                <div className="space-y-1">
                  {mockEvents.map((event, index) => (
                    <button
                      key={event.id}
                      onClick={() => setSelectedEvent(event)}
                      className={cn(
                        "w-full flex items-center gap-4 px-3 py-2.5 rounded-lg text-left transition-all duration-160",
                        selectedEvent?.id === event.id
                          ? "ring-2"
                          : "hover:bg-[var(--surface-sunken)]"
                      )}
                      style={{
                        backgroundColor:
                          selectedEvent?.id === event.id
                            ? "rgba(183, 135, 38, 0.08)"
                            : "transparent",
                        ["--tw-ring-color" as string]: "var(--gold-primary)",
                      }}
                    >
                      {/* Timestamp */}
                      <span
                        className="font-mono text-[11px] w-[52px] shrink-0 tabular-nums"
                        style={{ color: "var(--ink-tertiary)" }}
                      >
                        {event.timestamp.split(".")[0]}
                      </span>

                      {/* Node */}
                      <div className="relative z-10">
                        <span
                          className="block w-3 h-3 rounded-full ring-2 ring-[var(--surface-raised)]"
                          style={{ backgroundColor: substrateColors[event.substrate] }}
                        />
                      </div>

                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span
                            className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded"
                            style={{
                              backgroundColor: `${substrateColors[event.substrate]}20`,
                              color: substrateColors[event.substrate],
                            }}
                          >
                            {event.substrate}
                          </span>
                          <span
                            className="font-sans text-[13px] truncate"
                            style={{ color: "var(--ink-primary)" }}
                          >
                            {event.action}
                          </span>
                        </div>
                      </div>

                      {/* Status & Duration */}
                      <div className="flex items-center gap-3 shrink-0">
                        <span
                          className="font-mono text-[11px] tabular-nums"
                          style={{ color: "var(--ink-tertiary)" }}
                        >
                          {event.duration}
                        </span>
                        <StatusIcon status={event.status} />
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Right Pane - Event Inspector */}
            <div
              className="w-[40%] rounded-lg"
              style={{
                backgroundColor: "var(--surface-raised)",
                border: "1px solid var(--border-subtle)",
                minHeight: "600px",
              }}
            >
              {/* Inspector Header */}
              <div
                className="px-6 py-4 flex items-center justify-between"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                <span
                  className="font-mono text-[11px] uppercase tracking-[0.18em]"
                  style={{ color: "var(--ink-tertiary)" }}
                >
                  EVENT INSPECTOR
                </span>
                {selectedEvent && (
                  <div className="flex items-center gap-2">
                    <button
                      className="p-1.5 rounded transition-colors duration-160 hover:bg-[var(--surface-sunken)]"
                      title="Copy event data"
                    >
                      <Copy className="w-4 h-4" style={{ color: "var(--ink-tertiary)" }} />
                    </button>
                    <button
                      className="p-1.5 rounded transition-colors duration-160 hover:bg-[var(--surface-sunken)]"
                      title="Open in new tab"
                    >
                      <ExternalLink className="w-4 h-4" style={{ color: "var(--ink-tertiary)" }} />
                    </button>
                  </div>
                )}
              </div>

              {/* Inspector Content */}
              {selectedEvent ? (
                <div className="p-6 space-y-6">
                  {/* Event Header */}
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <span
                        className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded"
                        style={{
                          backgroundColor: `${substrateColors[selectedEvent.substrate]}20`,
                          color: substrateColors[selectedEvent.substrate],
                        }}
                      >
                        {selectedEvent.substrate}
                      </span>
                      <StatusIcon status={selectedEvent.status} />
                    </div>
                    <h3
                      className="font-sans text-[16px] font-medium mb-1"
                      style={{ color: "var(--ink-primary)" }}
                    >
                      {selectedEvent.action}
                    </h3>
                    <p
                      className="font-mono text-[12px]"
                      style={{ color: "var(--ink-tertiary)" }}
                    >
                      {selectedEvent.id} · {selectedEvent.timestamp}
                    </p>
                  </div>

                  {/* Metrics Row */}
                  <div
                    className="flex gap-4 p-4 rounded-lg"
                    style={{ backgroundColor: "var(--surface-sunken)" }}
                  >
                    <div className="flex items-center gap-2">
                      <Clock className="w-4 h-4" style={{ color: "var(--ink-tertiary)" }} />
                      <span className="font-mono text-[13px]" style={{ color: "var(--ink-primary)" }}>
                        {selectedEvent.duration}
                      </span>
                    </div>
                    {selectedEvent.details.tokens && (
                      <div className="flex items-center gap-2">
                        <Cpu className="w-4 h-4" style={{ color: "var(--ink-tertiary)" }} />
                        <span className="font-mono text-[13px]" style={{ color: "var(--ink-primary)" }}>
                          {selectedEvent.details.tokens} tokens
                        </span>
                      </div>
                    )}
                    {selectedEvent.details.confidence && (
                      <div className="flex items-center gap-2">
                        <Shield className="w-4 h-4" style={{ color: "var(--ink-tertiary)" }} />
                        <span className="font-mono text-[13px]" style={{ color: "var(--ink-primary)" }}>
                          {(selectedEvent.details.confidence * 100).toFixed(0)}% conf
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Details */}
                  <div className="space-y-4">
                    {selectedEvent.details.model && (
                      <DetailRow label="MODEL" value={selectedEvent.details.model} />
                    )}
                    {selectedEvent.details.policyId && (
                      <DetailRow label="POLICY ID" value={selectedEvent.details.policyId} />
                    )}
                    {selectedEvent.details.decision && (
                      <DetailRow label="DECISION" value={selectedEvent.details.decision} />
                    )}
                    {selectedEvent.details.input && (
                      <DetailRow label="INPUT" value={selectedEvent.details.input} />
                    )}
                    {selectedEvent.details.output && (
                      <DetailRow label="OUTPUT" value={selectedEvent.details.output} />
                    )}
                  </div>

                  {/* Raw JSON Toggle */}
                  <div>
                    <button
                      className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] transition-colors duration-160"
                      style={{ color: "var(--ink-tertiary)" }}
                    >
                      <ChevronRight className="w-3 h-3" />
                      View Raw JSON
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center h-[500px]">
                  <p
                    className="font-sans text-[14px] italic"
                    style={{ color: "var(--ink-tertiary)" }}
                  >
                    Select an event to inspect
                  </p>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function MetadataField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex-1 px-4 first:pl-0 last:pr-0">
      <div
        className="font-mono text-[10px] uppercase tracking-[0.18em] mb-1"
        style={{ color: "var(--ink-tertiary)" }}
      >
        {label}
      </div>
      {typeof value === "string" ? (
        <div
          className={cn(
            "text-[13px] font-medium",
            mono ? "font-mono" : "font-sans"
          )}
          style={{ color: "var(--ink-primary)" }}
        >
          {value}
        </div>
      ) : (
        value
      )}
    </div>
  );
}

function Divider() {
  return (
    <div
      className="w-px self-stretch mx-2"
      style={{ backgroundColor: "var(--border-subtle)" }}
    />
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        className="font-mono text-[10px] uppercase tracking-[0.18em] mb-1"
        style={{ color: "var(--ink-tertiary)" }}
      >
        {label}
      </div>
      <div
        className="font-mono text-[13px]"
        style={{ color: "var(--ink-primary)" }}
      >
        {value}
      </div>
    </div>
  );
}
