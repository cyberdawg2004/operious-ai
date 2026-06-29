"use client";

import { useCallback, useState } from "react";
import { ApprovalInbox } from "@/components/approval-inbox";
import { CaseApprovalsInbox } from "@/components/case-approvals-inbox";
import { ConfigChangeApprovals } from "@/components/config-change-approvals";
import { EscalationsInbox } from "@/components/escalations-inbox";
import { cn } from "@/lib/utils";

type TabId = "action-approvals" | "reply-reviews" | "escalations" | "knowledge-uploads";

const TAB_ORDER: TabId[] = ["action-approvals", "reply-reviews", "escalations", "knowledge-uploads"];

// "Action Sign-offs" vs "Message Approvals" -- deliberately NOT "Action
// Approvals" / "Reply Reviews": those two names read as near-synonyms,
// which is what sent an operator looking for a reply approval into the
// action-approvals tab and finding nothing. The pair must read as an
// obvious split: authorizing a REAL-WORLD ACTION (money/goods) vs
// approving a MESSAGE (text). Display-only -- tab ids, routes, and the
// underlying queues are unchanged.
const TAB_LABELS: Record<TabId, string> = {
  "action-approvals": "Action Sign-offs",
  "reply-reviews": "Message Approvals",
  escalations: "Escalations",
  "knowledge-uploads": "Knowledge Uploads",
};

const TAB_DESCRIPTIONS: Record<TabId, string> = {
  "action-approvals":
    "Sign off on refunds, replacements, and other actions that move money or goods.",
  "reply-reviews": "Approve customer-facing reply messages before they send.",
  escalations: "Cases that couldn't be resolved automatically and need a human look.",
  "knowledge-uploads": "Approve new or updated tenant knowledge documents and templates.",
};

/**
 * "Needs Your Attention" — a presentation-only shell that composes the four
 * existing governance inboxes (action approvals, SME reply reviews,
 * escalations, knowledge upload approvals) behind tabs. Each tab keeps its own
 * data source, actions, and capability gating; this component does not merge
 * endpoints or share action handlers across tabs. All tabs stay mounted (and
 * polling) so their counts stay live for the tab badges and switching tabs
 * doesn't reset state.
 */
export function AttentionInbox() {
  const [counts, setCounts] = useState<Record<TabId, number | null>>({
    "action-approvals": null,
    "reply-reviews": null,
    escalations: null,
    "knowledge-uploads": null,
  });
  const [activeTab, setActiveTab] = useState<TabId | null>(null);

  const setActionApprovalsCount = useCallback((count: number) => {
    setCounts((prev) => (prev["action-approvals"] === count ? prev : { ...prev, "action-approvals": count }));
  }, []);
  const setReplyReviewsCount = useCallback((count: number) => {
    setCounts((prev) => (prev["reply-reviews"] === count ? prev : { ...prev, "reply-reviews": count }));
  }, []);
  const setEscalationsCount = useCallback((count: number) => {
    setCounts((prev) => (prev.escalations === count ? prev : { ...prev, escalations: count }));
  }, []);
  const setKnowledgeUploadsCount = useCallback((count: number) => {
    setCounts((prev) => (prev["knowledge-uploads"] === count ? prev : { ...prev, "knowledge-uploads": count }));
  }, []);

  // Default to whichever tab has the most pending items once all three counts
  // have loaded — but only if the operator hasn't already picked a tab.
  const currentTab = activeTab ?? defaultTab(counts);

  return (
    <div className="min-h-[calc(100vh-82px)] bg-canvas px-4 py-5 sm:px-6 lg:px-12 lg:py-8">
      <div className="mb-5">
        <span className="font-technical text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
          Governance / Needs Your Attention
        </span>
        <h2 className="mt-1 text-[22px] font-semibold text-ink-primary">
          Needs Your Attention
        </h2>
      </div>

      <div role="tablist" aria-label="Items needing attention" className="mb-5 flex flex-wrap gap-1 border-b border-border-subtle">
        {TAB_ORDER.map((id) => {
          const count = counts[id];
          const isActive = currentTab === id;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveTab(id)}
              className={cn(
                "relative flex items-center gap-2 px-3 pb-3 pt-1 text-[13px] font-medium transition-colors",
                isActive
                  ? "border-b-2 border-gold-primary text-ink-primary"
                  : "border-b-2 border-transparent text-ink-tertiary hover:text-ink-secondary"
              )}
            >
              {TAB_LABELS[id]}
              <span
                className={cn(
                  "inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 font-technical text-[10px] font-semibold tabular-nums",
                  count !== null && count > 0
                    ? "bg-gold-primary text-white"
                    : "bg-surface-raised text-ink-tertiary"
                )}
              >
                {count ?? "—"}
              </span>
            </button>
          );
        })}
      </div>

      <p className="mb-5 text-[13px] text-ink-tertiary">{TAB_DESCRIPTIONS[currentTab]}</p>

      <div className={cn(currentTab !== "action-approvals" && "hidden")}>
        <ApprovalInbox embedded onCountChange={setActionApprovalsCount} />
      </div>
      <div className={cn(currentTab !== "reply-reviews" && "hidden")}>
        <CaseApprovalsInbox embedded onCountChange={setReplyReviewsCount} />
      </div>
      <div className={cn(currentTab !== "escalations" && "hidden")}>
        <EscalationsInbox embedded onCountChange={setEscalationsCount} />
      </div>
      <div className={cn(currentTab !== "knowledge-uploads" && "hidden")}>
        <ConfigChangeApprovals embedded changeKind="knowledge" onCountChange={setKnowledgeUploadsCount} />
      </div>
    </div>
  );
}

/** Whichever tab has the most pending items, once all three counts have
 * loaded; "Action Sign-offs" while loading or if everything is empty. */
function defaultTab(counts: Record<TabId, number | null>): TabId {
  if (TAB_ORDER.some((id) => counts[id] === null)) return "action-approvals";
  const withCounts = TAB_ORDER.map((id) => ({ id, count: counts[id] ?? 0 }));
  const max = Math.max(...withCounts.map((entry) => entry.count));
  return max > 0 ? withCounts.find((entry) => entry.count === max)!.id : "action-approvals";
}
