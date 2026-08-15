import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalInbox } from "@/components/approval-inbox";

const auth = vi.hoisted(() => ({
  principal: null as { capabilities: string[] } | null,
  isLoading: false,
  error: null as string | null,
}));
const api = vi.hoisted(() => ({ approve: vi.fn(), deny: vi.fn() }));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ principal: auth.principal, error: auth.error, isLoading: auth.isLoading, reload: vi.fn(), operatorLabel: null }),
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    listActionApprovals: vi.fn().mockResolvedValue([{
      approval_id: "00000000-0000-4000-8000-000000000001", tenant_id: "northstar-clueso-demo",
      session_id: "2e5a8e82-9184-520d-a027-6190977e6f4b", tool_name: "replacement.order",
      status: "pending", requested_at: "2026-08-08T09:03:00+00:00", metadata: {}, payload: {},
    }]),
    getActionApproval: vi.fn().mockResolvedValue({
      approval_id: "00000000-0000-4000-8000-000000000001", tenant_id: "northstar-clueso-demo",
      session_id: "2e5a8e82-9184-520d-a027-6190977e6f4b", tool_name: "replacement.order",
      status: "pending", requested_at: "2026-08-08T09:03:00+00:00", metadata: {}, payload: {},
      classification_category: null, classification_confidence: null, classification_summary: null,
      session_phase: "dormant", session_opened_at: "2026-08-08T09:00:00+00:00",
      governance_decision_id: null, governance_reason: null, governance_evaluated_at: null,
    }),
    approveActionApproval: api.approve,
    denyActionApproval: api.deny,
  };
});

async function openApproval(): Promise<void> {
  await screen.findByText("Replacement Order");
  fireEvent.click(screen.getByText("Replacement Order"));
  await screen.findByText("Approval Review");
}

describe("ApprovalInbox capability gating", () => {
  beforeEach(() => {
    cleanup();
    auth.principal = null;
    auth.isLoading = false;
    auth.error = null;
    api.approve.mockReset();
    api.deny.mockReset();
  });

  it.each([
    ["recorder", ["tenant.operations.read", "tenant.supervisor.read"]],
    ["unrelated", ["tenant.connector.write"]],
    ["undefined", null],
  ])("keeps %s users read-only", async (_name, capabilities) => {
    auth.principal = capabilities === null ? null : { capabilities };
    render(<ApprovalInbox />);
    await openApproval();
    expect(screen.getByText("Read-only — approval authority not granted")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deny" })).not.toBeInTheDocument();
    expect(api.approve).not.toHaveBeenCalled();
    expect(api.deny).not.toHaveBeenCalled();
  });

  it("retains controls for an authorized operator", async () => {
    auth.principal = { capabilities: ["tenant.actions.approve"] };
    render(<ApprovalInbox />);
    await openApproval();
    expect(screen.getByRole("button", { name: "Approve" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Deny" })).toBeVisible();
  });

  it.each(["loading", "error"]) ("fails closed while authentication is %s", async (state) => {
    auth.isLoading = state === "loading";
    auth.error = state === "error" ? "principal unavailable" : null;
    render(<ApprovalInbox />);
    await openApproval();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deny" })).not.toBeInTheDocument();
  });
});
