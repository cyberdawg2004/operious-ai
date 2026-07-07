"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  ExternalLink,
  KeyRound,
  Loader2,
  PlugZap,
  RefreshCw,
  Server,
  X,
} from "lucide-react";
import {
  formatApiError,
  getConfiguredTenantId,
  listConfigChangeRequests,
  listConnectorConfigurations,
  previewMcpServerTools,
  proposeConfigChangeRequest,
  startMcpOAuth,
  type McpToolInfo,
  type TenantConfigChangeRequest,
  type TenantConnectorConfiguration,
} from "@/lib/api";
import {
  MCP_COMMITMENT_KIND_OPTIONS,
  MCP_EXECUTION_POLICY_OPTIONS,
  MCP_MONEY_GOODS_KINDS,
  buildMcpServerChangePayload,
  type McpCommitmentKind,
  type McpExecutionPolicy,
  type McpToolDeclarationInput,
} from "@/lib/config-change-payloads";
import { useAuthSession } from "@/lib/use-auth-session";
import { useApiResource } from "@/lib/use-api-resource";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { ProposedNotice } from "@/components/connector-config-views";

// ─── Types ────────────────────────────────────────────────────────────────

type McpViewState =
  | { kind: "list" }
  | { kind: "add_server" }
  | {
      kind: "classify_tools";
      mcpServerId: string;
      endpointUrl: string;
      authMethod: AuthMethod;
      tools: McpToolInfo[];
    }
  | { kind: "pending" };

type AuthMethod = "oauth" | "api_key" | "none";

type OAuthFlowState =
  | { status: "idle" }
  | { status: "opening" }
  | { status: "waiting"; authorizationUrl: string; stateToken: string }
  | { status: "done" }
  | { status: "error"; message: string };

type ToolClassificationRow = {
  tool: McpToolInfo;
  commitment_kind: McpCommitmentKind | "";
  execution_policy: McpExecutionPolicy | "";
  enabled: boolean;
  autoExecuteAcknowledged: boolean;
  schemaExpanded: boolean;
};

type McpDashboardData = {
  mcpConnectors: TenantConnectorConfiguration[];
  pendingRequests: TenantConfigChangeRequest[];
};

// ─── Heuristic suggestion ─────────────────────────────────────────────────

const MONEY_GOODS_KEYWORDS = [
  "refund", "payment", "charge", "credit", "transfer",
  "send", "wire", "issue", "disburse", "pay",
];

function suggestCommitmentKind(tool: McpToolInfo): McpCommitmentKind {
  const haystack = `${tool.name} ${tool.description}`.toLowerCase();
  for (const keyword of MONEY_GOODS_KEYWORDS) {
    if (haystack.includes(keyword)) return "goods";
  }
  return "none";
}

// ─── McpConnectorView (top-level panel) ──────────────────────────────────

export function McpConnectorView({
  tenantId: propTenantId,
  canWrite,
}: {
  tenantId?: string | null;
  canWrite?: boolean;
}) {
  const { principal } = useAuthSession();
  const resolvedTenantId = propTenantId ?? principal?.tenant_id ?? getConfiguredTenantId();
  const resolvedCanWrite = canWrite ?? (principal?.capabilities.includes("tenant.connector.write") ?? false);

  const [viewState, setViewState] = useState<McpViewState>({ kind: "list" });
  const [notice, setNotice] = useState<string | null>(null);

  // Handle OAuth callback redirect: /connectors?oauth=success&mcp_server_id=...
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const oauthResult = params.get("oauth");
    const serverId = params.get("mcp_server_id");
    if (oauthResult === "success" && serverId) {
      setNotice(`OAuth authorized for "${serverId}". The credential is stored.`);
      // Strip the query params without a full reload.
      const clean = window.location.pathname;
      window.history.replaceState({}, "", clean);
    } else if (oauthResult === "error") {
      const reason = params.get("reason") ?? "unknown";
      setNotice(`OAuth authorization failed: ${reason}. Try again.`);
      const clean = window.location.pathname;
      window.history.replaceState({}, "", clean);
    }
  }, []);

  const load = useCallback(async (): Promise<McpDashboardData> => {
    const [allConnectors, proposed, approved] = await Promise.all([
      listConnectorConfigurations({ connector_type: "mcp_server", limit: 100, offset: 0 }),
      listConfigChangeRequests({ status: "PROPOSED", limit: 100, offset: 0 }),
      listConfigChangeRequests({ status: "APPROVED", limit: 100, offset: 0 }),
    ]);

    const mcpRequests = [...proposed.items, ...approved.items].filter(
      (req) => req.change_type === "mcp_server" || req.change_type === "mcp_oauth_token"
    );

    return {
      mcpConnectors: allConnectors.items,
      pendingRequests: mcpRequests,
    };
  }, []);

  const { data, error, isLoading, reload } = useApiResource(load);

  if (viewState.kind === "add_server") {
    return (
      <div className="space-y-4">
        {notice && <ProposedNotice message={notice} onDismiss={() => setNotice(null)} />}
        <AddMcpServerForm
          tenantId={resolvedTenantId}
          canWrite={resolvedCanWrite}
          onCancel={() => setViewState({ kind: "list" })}
          onFetchedTools={(mcpServerId, endpointUrl, authMethod, tools) => {
            setViewState({ kind: "classify_tools", mcpServerId, endpointUrl, authMethod, tools });
          }}
        />
      </div>
    );
  }

  if (viewState.kind === "classify_tools") {
    return (
      <div className="space-y-4">
        {notice && <ProposedNotice message={notice} onDismiss={() => setNotice(null)} />}
        <McpToolClassificationTable
          tenantId={resolvedTenantId}
          canWrite={resolvedCanWrite}
          mcpServerId={viewState.mcpServerId}
          endpointUrl={viewState.endpointUrl}
          tools={viewState.tools}
          onBack={() => setViewState({ kind: "add_server" })}
          onProposed={() => {
            setNotice(
              `MCP server "${viewState.mcpServerId}" proposed for approval.`
            );
            setViewState({ kind: "list" });
            reload();
          }}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {notice && <ProposedNotice message={notice} onDismiss={() => setNotice(null)} />}

      <div className="flex items-center justify-between gap-3">
        <div />
        <div className="flex items-center gap-2">
          {resolvedCanWrite && (
            <button
              type="button"
              onClick={() => setViewState({ kind: "add_server" })}
              className="cc-btn cc-btn-secondary"
            >
              <PlugZap size={14} strokeWidth={1.8} />
              Add MCP Server
            </button>
          )}
          <button
            type="button"
            onClick={reload}
            className="cc-btn cc-btn-secondary"
          >
            <RefreshCw size={14} strokeWidth={1.8} />
            Refresh
          </button>
        </div>
      </div>

      {isLoading && <LoadingState label="Loading MCP servers..." />}
      {error && !isLoading && (
        <ErrorState
          title="Could not load MCP servers"
          message={error}
          onAction={reload}
        />
      )}

      {!isLoading && !error && (data?.mcpConnectors ?? []).length === 0 && (
        <EmptyState
          title="Connect your first MCP server"
          message="Connect any MCP-compatible server. Tools are classified and governed per the existing approval model."
          actionLabel={resolvedCanWrite ? "Add MCP Server" : undefined}
          onAction={resolvedCanWrite ? () => setViewState({ kind: "add_server" }) : undefined}
        />
      )}

      {!isLoading && !error && (data?.mcpConnectors ?? []).length > 0 && (
        <div className="grid grid-cols-1 gap-4">
          {data!.mcpConnectors.map((connector) => (
            <McpServerCard
              key={`${connector.tool_name}-${connector.version}`}
              connector={connector}
              pendingRequests={data!.pendingRequests}
              canWrite={resolvedCanWrite}
              tenantId={resolvedTenantId}
              onManageTools={() => setViewState({ kind: "add_server" })}
            />
          ))}
        </div>
      )}

      {!isLoading && !error && (data?.pendingRequests ?? []).length > 0 && (
        <div className="rounded-lg border border-border-subtle bg-surface-raised px-3 py-2 text-[13px] text-ink-secondary">
          {data!.pendingRequests.length} MCP change request
          {data!.pendingRequests.length === 1 ? "" : "s"} awaiting separate approval.
        </div>
      )}
    </div>
  );
}

// ─── AddMcpServerForm ─────────────────────────────────────────────────────

function AddMcpServerForm({
  tenantId,
  canWrite,
  onCancel,
  onFetchedTools,
}: {
  tenantId: string | null;
  canWrite: boolean;
  onCancel: () => void;
  onFetchedTools: (
    mcpServerId: string,
    endpointUrl: string,
    authMethod: AuthMethod,
    tools: McpToolInfo[]
  ) => void;
}) {
  const [mcpServerId, setMcpServerId] = useState("");
  const [endpointUrl, setEndpointUrl] = useState("");
  const [authMethod, setAuthMethod] = useState<AuthMethod>("oauth");

  // OAuth fields
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [authEndpoint, setAuthEndpoint] = useState("");
  const [tokenEndpoint, setTokenEndpoint] = useState("");
  const [scopes, setScopes] = useState("");
  const [redirectUri, setRedirectUri] = useState(
    typeof window !== "undefined"
      ? `${window.location.origin}/api/v1/mcp/oauth/callback`
      : ""
  );
  const [oauthFlow, setOauthFlow] = useState<OAuthFlowState>({ status: "idle" });
  const popupRef = useRef<Window | null>(null);

  // API key fields
  const [apiKey, setApiKey] = useState("");

  // Fetch tools state
  const [fetchStatus, setFetchStatus] = useState<"idle" | "loading" | "error">("idle");
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const serverIdValid = /^[a-zA-Z0-9_]+$/.test(mcpServerId.trim());
  const endpointValid = endpointUrl.trim().startsWith("https://");

  const canFetch = mcpServerId.trim() && serverIdValid && endpointValid;

  // Poll for OAuth popup completing (it redirects to /connectors?oauth=success)
  useEffect(() => {
    if (oauthFlow.status !== "waiting") return;
    const interval = setInterval(() => {
      if (!popupRef.current || popupRef.current.closed) {
        clearInterval(interval);
        // Check if the parent page URL changed (popup completed and closed)
        // The callback redirects to /connectors?oauth=success — the popup
        // itself receives that redirect, not the parent. We mark done on close.
        setOauthFlow({ status: "done" });
        return;
      }
      try {
        // If we can read the popup URL it means the redirect landed in the popup.
        const url = popupRef.current.location.href;
        if (url.includes("oauth=success")) {
          popupRef.current.close();
          setOauthFlow({ status: "done" });
          clearInterval(interval);
        } else if (url.includes("oauth=error")) {
          const params = new URLSearchParams(new URL(url).search);
          popupRef.current.close();
          setOauthFlow({ status: "error", message: params.get("reason") ?? "unknown" });
          clearInterval(interval);
        }
      } catch {
        // Cross-origin during redirect — expected, just keep polling.
      }
    }, 500);
    return () => clearInterval(interval);
  }, [oauthFlow.status]);

  const initiateOAuth = async () => {
    if (!tenantId) {
      setOauthFlow({ status: "error", message: "Tenant scope is missing." });
      return;
    }
    if (!mcpServerId.trim()) {
      setFormError("Set a Server ID before authorizing — it binds the credential.");
      return;
    }
    setOauthFlow({ status: "opening" });
    try {
      const resp = await startMcpOAuth(tenantId, {
        mcp_server_id: mcpServerId.trim(),
        oauth_config: {
          client_id: clientId.trim(),
          auth_endpoint: authEndpoint.trim(),
          token_endpoint: tokenEndpoint.trim(),
          scopes: scopes.split(",").map((s) => s.trim()).filter(Boolean),
          redirect_uri: redirectUri.trim(),
          client_secret: clientSecret,
        },
      });
      const popup = window.open(
        resp.authorization_url,
        "mcp_oauth",
        "width=600,height=700,menubar=no,toolbar=no,location=no"
      );
      if (!popup) {
        setOauthFlow({
          status: "error",
          message: "Popup was blocked. Allow popups for this page and try again.",
        });
        return;
      }
      popupRef.current = popup;
      setOauthFlow({ status: "waiting", authorizationUrl: resp.authorization_url, stateToken: resp.state_token });
    } catch (err) {
      setOauthFlow({ status: "error", message: formatApiError(err) });
    }
  };

  const handleFetchTools = async () => {
    if (!tenantId) { setFetchError("Tenant scope is missing."); return; }
    if (!canFetch) return;
    setFetchStatus("loading");
    setFetchError(null);
    setFormError(null);
    try {
      // Uses preview endpoint — no prior registration needed.
      const result = await previewMcpServerTools(tenantId, endpointUrl.trim());
      setFetchStatus("idle");
      onFetchedTools(mcpServerId.trim(), endpointUrl.trim(), authMethod, result.tools);
    } catch (caught: unknown) {
      setFetchError(
        `Could not fetch tools from ${endpointUrl.trim()}: ${formatApiError(caught)}`
      );
      setFetchStatus("error");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-[24px] font-semibold text-ink-primary">
            Add MCP Server
          </h2>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-secondary">
            Connect any MCP-compatible server. Classify and govern each tool it exposes.
          </p>
        </div>
        <button
          type="button"
          onClick={onCancel}
          className="flex h-10 w-10 items-center justify-center rounded border border-border-subtle text-ink-tertiary hover:text-ink-primary"
          aria-label="Cancel"
        >
          <X className="h-4 w-4" strokeWidth={1.8} />
        </button>
      </div>

      {formError && <FormError message={formError} />}

      <McpFieldset legend="Server identity">
        <McpText
          label="MCP Server ID (letters, numbers, underscores)"
          value={mcpServerId}
          onChange={setMcpServerId}
          placeholder="gmail_mcp"
          required
        />
        {mcpServerId.trim() && !serverIdValid && (
          <p className="text-[12px] text-red-alert">
            Server ID must only contain letters, numbers, and underscores.
          </p>
        )}
        <McpText
          label="Endpoint URL (must start with https://)"
          value={endpointUrl}
          onChange={setEndpointUrl}
          placeholder="https://gmail.mcp.example.com"
          required
        />
        {endpointUrl.trim() && !endpointValid && (
          <p className="text-[12px] text-red-alert">
            Endpoint URL must start with https://.
          </p>
        )}
      </McpFieldset>

      <McpFieldset legend="Authentication">
        <div className="flex gap-4">
          {(["oauth", "api_key", "none"] as const).map((method) => (
            <label key={method} className="flex cursor-pointer items-center gap-2 text-[13px] text-ink-primary">
              <input
                type="radio"
                name="auth_method"
                value={method}
                checked={authMethod === method}
                onChange={() => {
                  setAuthMethod(method);
                  setOauthFlow({ status: "idle" });
                }}
                className="accent-gold-primary"
              />
              {method === "oauth" ? "OAuth 2.0" : method === "api_key" ? "API Key" : "None / Public"}
            </label>
          ))}
        </div>

        {authMethod === "oauth" && (
          <div className="space-y-3 pt-1">
            <McpText label="Client ID" value={clientId} onChange={setClientId} placeholder="your-client-id" />
            <McpWriteOnlyInput label="Client secret" value={clientSecret} onChange={setClientSecret} />
            <McpText
              label="Authorization endpoint"
              value={authEndpoint}
              onChange={setAuthEndpoint}
              placeholder="https://accounts.google.com/o/oauth2/v2/auth"
            />
            <McpText
              label="Token endpoint"
              value={tokenEndpoint}
              onChange={setTokenEndpoint}
              placeholder="https://oauth2.googleapis.com/token"
            />
            <McpText
              label="Scopes (comma-separated)"
              value={scopes}
              onChange={setScopes}
              placeholder="https://mail.google.com/, openid"
            />
            <McpText
              label="Redirect URI"
              value={redirectUri}
              onChange={setRedirectUri}
              placeholder="https://app.operious.ai/api/v1/mcp/oauth/callback"
            />

            {oauthFlow.status === "idle" && (
              <button
                type="button"
                onClick={initiateOAuth}
                disabled={!clientId.trim() || !authEndpoint.trim() || !tokenEndpoint.trim()}
                className="cc-btn cc-btn-secondary disabled:opacity-50"
              >
                <ExternalLink size={13} strokeWidth={1.8} />
                Authorize with OAuth
              </button>
            )}
            {oauthFlow.status === "opening" && (
              <div className="flex items-center gap-2 text-[13px] text-ink-secondary">
                <Loader2 className="h-4 w-4 animate-spin" />
                Opening authorization window…
              </div>
            )}
            {oauthFlow.status === "waiting" && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-[13px] text-ink-secondary">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Waiting for OAuth consent… (complete in the popup)
                </div>
                <a
                  href={oauthFlow.authorizationUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[12px] text-gold-primary underline underline-offset-2"
                >
                  Open authorization URL manually
                </a>
              </div>
            )}
            {oauthFlow.status === "done" && (
              <div className="flex items-center gap-2 text-[13px] text-green-600">
                <CheckCircle2 className="h-4 w-4" />
                OAuth authorized — credential stored
              </div>
            )}
            {oauthFlow.status === "error" && (
              <div className="space-y-2">
                <FormError message={`OAuth failed: ${oauthFlow.message}`} />
                <button
                  type="button"
                  onClick={() => setOauthFlow({ status: "idle" })}
                  className="text-[12px] text-gold-primary underline underline-offset-2"
                >
                  Try again
                </button>
              </div>
            )}
          </div>
        )}

        {authMethod === "api_key" && (
          <div className="pt-1">
            <McpWriteOnlyInput label="API key" value={apiKey} onChange={setApiKey} />
          </div>
        )}

        {authMethod === "none" && (
          <p className="pt-1 text-[12px] text-ink-tertiary">
            No credential required — server accepts unauthenticated calls.
          </p>
        )}
      </McpFieldset>

      {fetchError && <FormError message={fetchError} />}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleFetchTools}
          disabled={!canFetch || fetchStatus === "loading" || !canWrite}
          className="cc-btn cc-btn-secondary disabled:opacity-50"
        >
          {fetchStatus === "loading" ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Fetching tools…
            </>
          ) : (
            <>
              <Server size={14} strokeWidth={1.8} />
              Fetch available tools
            </>
          )}
        </button>
        <button type="button" onClick={onCancel} className="cc-btn cc-btn-secondary">
          Cancel
        </button>
      </div>
    </div>
  );
}

// ─── McpToolClassificationTable ───────────────────────────────────────────

function McpToolClassificationTable({
  tenantId,
  canWrite,
  mcpServerId,
  endpointUrl,
  tools,
  onBack,
  onProposed,
}: {
  tenantId: string | null;
  canWrite: boolean;
  mcpServerId: string;
  endpointUrl: string;
  tools: McpToolInfo[];
  onBack: () => void;
  onProposed: () => void;
}) {
  const [rows, setRows] = useState<ToolClassificationRow[]>(() =>
    tools.map((tool) => ({
      tool,
      commitment_kind: suggestCommitmentKind(tool),
      execution_policy: "operious_approval" as McpExecutionPolicy,
      enabled: true,
      autoExecuteAcknowledged: false,
      schemaExpanded: false,
    }))
  );

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const updateRow = (index: number, patch: Partial<ToolClassificationRow>) => {
    setRows((current) =>
      current.map((row, i) => (i === index ? { ...row, ...patch } : row))
    );
  };

  const enabledRows = rows.filter((row) => row.enabled);

  const allClassified = enabledRows.every(
    (row) => row.commitment_kind !== "" && row.execution_policy !== ""
  );

  const autoExecuteMoneyRows = enabledRows.filter(
    (row) =>
      row.execution_policy === "auto_execute" &&
      row.commitment_kind !== "" &&
      MCP_MONEY_GOODS_KINDS.has(row.commitment_kind as McpCommitmentKind)
  );

  const allAutoExecuteAcknowledged = autoExecuteMoneyRows.every(
    (row) => row.autoExecuteAcknowledged
  );

  const canSubmit = enabledRows.length > 0 && allClassified && allAutoExecuteAcknowledged;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) {
      setFormError(
        "All enabled tools must have commitment_kind and execution_policy set, " +
        "and all auto-execute money/goods warnings must be acknowledged."
      );
      return;
    }
    if (!tenantId) {
      setFormError("Tenant scope is missing.");
      return;
    }

    setIsSubmitting(true);
    setFormError(null);

    try {
      const mcpTools: McpToolDeclarationInput[] = rows.map((row) => ({
        tool_name: row.tool.name,
        commitment_kind: (row.commitment_kind || "none") as McpCommitmentKind,
        execution_policy: (row.execution_policy || "operious_approval") as McpExecutionPolicy,
        description_snapshot: row.tool.description,
        input_schema_snapshot: row.tool.inputSchema,
        enabled: row.enabled,
      }));

      const payload = buildMcpServerChangePayload({
        mcp_server_id: mcpServerId,
        endpoint_url: endpointUrl,
        mcp_tools: mcpTools,
        timeout_seconds: 15,
      });

      await proposeConfigChangeRequest(payload);
      onProposed();
    } catch (caught: unknown) {
      setFormError(formatApiError(caught));
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-[24px] font-semibold text-ink-primary">
            Classify Tools — {mcpServerId}
          </h2>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-secondary">
            {endpointUrl} · {tools.length} tool{tools.length === 1 ? "" : "s"} fetched
          </p>
        </div>
        <button type="button" onClick={onBack} className="cc-btn cc-btn-secondary">
          Back
        </button>
      </div>

      <div className="rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-[12px] leading-relaxed text-ink-secondary">
        Classify each tool before submission.{" "}
        <code>commitment_kind</code> describes what the tool commits.{" "}
        <code>execution_policy</code> determines whether Operious holds for approval or fires immediately.
        Suggested values are pre-filled from tool metadata — confirm each one.
      </div>

      {autoExecuteMoneyRows.length > 0 && (
        <div className="rounded-lg border border-amber-400/60 bg-amber-50 px-3 py-2 text-[12px] text-amber-800 dark:border-amber-500/40 dark:bg-amber-950/30 dark:text-amber-300">
          <strong>{autoExecuteMoneyRows.length}</strong> tool
          {autoExecuteMoneyRows.length === 1 ? " is" : "s are"} set to{" "}
          <strong>auto_execute</strong> on a money/goods commitment.
          Each requires acknowledgment below before submission is enabled.
        </div>
      )}

      {formError && <FormError message={formError} />}

      {rows.length === 0 && (
        <div className="rounded-lg border border-border-subtle bg-surface-raised px-4 py-6 text-center text-[13px] text-ink-secondary">
          No tools returned from this server.
        </div>
      )}

      <div className="space-y-3">
        {rows.map((row, index) => (
          <ToolClassificationRow
            key={row.tool.name}
            row={row}
            index={index}
            onUpdate={(patch) => updateRow(index, patch)}
          />
        ))}
      </div>

      {!allClassified && enabledRows.length > 0 && (
        <div className="rounded-lg border border-border-subtle bg-surface-raised px-3 py-2 text-[13px] text-ink-secondary">
          All enabled tools need commitment_kind and execution_policy before submitting.
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={!canSubmit || isSubmitting || !canWrite}
          className="inline-flex min-h-11 items-center justify-center rounded bg-gold-primary px-4 py-2 text-[13px] font-semibold text-white hover:bg-gold-muted disabled:opacity-60"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Proposing…
            </>
          ) : (
            "Submit for approval"
          )}
        </button>
        <button type="button" onClick={onBack} className="cc-btn cc-btn-secondary">
          Back
        </button>
      </div>
    </form>
  );
}

// ─── Individual tool classification row ──────────────────────────────────

function ToolClassificationRow({
  row,
  onUpdate,
}: {
  row: ToolClassificationRow;
  index: number;
  onUpdate: (patch: Partial<ToolClassificationRow>) => void;
}) {
  const isAutoExecuteMoney =
    row.execution_policy === "auto_execute" &&
    row.commitment_kind !== "" &&
    MCP_MONEY_GOODS_KINDS.has(row.commitment_kind as McpCommitmentKind);

  const totalSchemaKeys = Object.keys(row.tool.inputSchema ?? {}).length;
  const schemaKeys = Object.keys(row.tool.inputSchema ?? {}).slice(0, 5);

  const isSuggested = row.commitment_kind !== "" && row.commitment_kind === suggestCommitmentKind(row.tool);

  return (
    <div
      className={`rounded-lg border ${row.enabled ? "border-border-subtle" : "border-border-subtle/50 opacity-60"} bg-surface-raised p-4 space-y-3`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[13px] font-semibold text-ink-primary">
            {row.tool.name}
          </div>
          <div className="mt-1 text-[12px] leading-relaxed text-ink-secondary line-clamp-2">
            {row.tool.description || "No description provided."}
          </div>
        </div>
        <label className="flex shrink-0 cursor-pointer items-center gap-2 text-[12px] text-ink-secondary">
          <input
            type="checkbox"
            checked={row.enabled}
            onChange={(e) => onUpdate({ enabled: e.target.checked })}
            className="accent-gold-primary"
          />
          Enabled
        </label>
      </div>

      {totalSchemaKeys > 0 && (
        <div>
          <button
            type="button"
            onClick={() => onUpdate({ schemaExpanded: !row.schemaExpanded })}
            className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary hover:text-ink-secondary"
          >
            {row.schemaExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            Input schema ({totalSchemaKeys} field{totalSchemaKeys === 1 ? "" : "s"})
          </button>
          {row.schemaExpanded && (
            <div className="mt-1 rounded border border-border-subtle bg-surface px-2 py-2 text-[11px] font-mono text-ink-secondary">
              {schemaKeys.map((key) => <div key={key}>{key}</div>)}
              {totalSchemaKeys > 5 && (
                <div className="text-ink-tertiary">+{totalSchemaKeys - 5} more…</div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
            Commitment kind{" "}
            {isSuggested && (
              <span className="normal-case text-gold-primary">(suggested)</span>
            )}
          </span>
          <select
            value={row.commitment_kind}
            onChange={(e) =>
              onUpdate({
                commitment_kind: e.target.value as McpCommitmentKind | "",
                autoExecuteAcknowledged: false,
              })
            }
            disabled={!row.enabled}
            className="h-10 w-full rounded border border-border-subtle bg-surface px-3 text-[13px] text-ink-primary focus:border-gold-primary focus:outline-none disabled:opacity-50"
          >
            <option value="">— Select —</option>
            {MCP_COMMITMENT_KIND_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="mb-1 block font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
            Execution policy
          </span>
          <select
            value={row.execution_policy}
            onChange={(e) =>
              onUpdate({
                execution_policy: e.target.value as McpExecutionPolicy | "",
                autoExecuteAcknowledged: false,
              })
            }
            disabled={!row.enabled}
            className="h-10 w-full rounded border border-border-subtle bg-surface px-3 text-[13px] text-ink-primary focus:border-gold-primary focus:outline-none disabled:opacity-50"
          >
            <option value="">— Select —</option>
            {MCP_EXECUTION_POLICY_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt === "operious_approval" ? "operious_approval (recommended)" : "auto_execute"}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Auto-execute money/goods warning — mandatory acknowledgment */}
      {isAutoExecuteMoney && (
        <div className="rounded-lg border border-amber-400/60 bg-amber-50 px-3 py-3 dark:border-amber-500/40 dark:bg-amber-950/30">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="space-y-2">
              <p className="text-[13px] font-semibold text-amber-800 dark:text-amber-300">
                Auto-execute {row.commitment_kind} action — NO Operious approval gate
              </p>
              <p className="text-[12px] leading-relaxed text-amber-700 dark:text-amber-400">
                This tool fires WITHOUT Operious approval. Your system must authorize all{" "}
                [{row.commitment_kind}] operations. This choice is audited.
              </p>
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={row.autoExecuteAcknowledged}
                  onChange={(e) => onUpdate({ autoExecuteAcknowledged: e.target.checked })}
                  className="accent-amber-600"
                />
                <span className="text-[12px] font-medium text-amber-800 dark:text-amber-300">
                  I confirm this tool will auto-execute without Operious approval
                </span>
              </label>
            </div>
          </div>
        </div>
      )}

      {row.enabled && (row.commitment_kind === "" || row.execution_policy === "") && (
        <p className="text-[12px] text-ink-tertiary">
          Classification required before this tool can be submitted.
        </p>
      )}
    </div>
  );
}

// ─── McpServerCard ────────────────────────────────────────────────────────

function McpServerCard({
  connector,
  pendingRequests,
  canWrite,
  tenantId,
  onManageTools,
}: {
  connector: TenantConnectorConfiguration;
  pendingRequests: TenantConfigChangeRequest[];
  canWrite: boolean;
  tenantId: string | null;
  onManageTools: () => void;
}) {
  const mcpServerId =
    typeof connector.field_mappings?.mcp_server_id === "string"
      ? connector.field_mappings.mcp_server_id
      : connector.tool_name;

  const endpointUrl =
    typeof connector.field_mappings?.endpoint_url === "string"
      ? connector.field_mappings.endpoint_url
      : connector.endpoint_template;

  const mcpTools = Array.isArray(connector.field_mappings?.mcp_tools)
    ? (connector.field_mappings.mcp_tools as McpToolDeclarationInput[])
    : [];

  const pendingForServer = pendingRequests.filter(
    (req) =>
      req.proposed_payload.mcp_server_id === mcpServerId ||
      req.proposed_payload.mcp_server_id === connector.tool_name
  );

  const connectionStatus = deriveConnectionStatus(connector, pendingForServer.length);
  const statusMeta = mcpConnectionStatusMeta(connectionStatus);

  const autoExecuteMoneyTools = mcpTools.filter(
    (t) => t.execution_policy === "auto_execute" && MCP_MONEY_GOODS_KINDS.has(t.commitment_kind)
  );

  return (
    <Card hover>
      <CardHeader>
        <div>
          <CardTitle>{mcpServerId}</CardTitle>
          <CardDescription>{endpointUrl || connector.endpoint_template}</CardDescription>
        </div>
        <StatusBadge
          label={statusMeta.label}
          tone={statusMeta.tone}
          icon={statusMeta.icon}
        />
      </CardHeader>

      <div className="grid gap-2 text-[13px] md:grid-cols-2">
        <McpField label="Server ID" value={mcpServerId} />
        <McpField label="Tool count" value={mcpTools.length > 0 ? String(mcpTools.length) : "—"} />
        <McpField label="Version" value={`v${connector.version}`} />
        <McpField label="Configured by" value={connector.configured_by} />
      </div>

      {autoExecuteMoneyTools.length > 0 && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-400/40 bg-amber-50 px-3 py-2 text-[12px] text-amber-700 dark:border-amber-500/30 dark:bg-amber-950/20 dark:text-amber-400">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {autoExecuteMoneyTools.length} auto-execute money/goods tool
          {autoExecuteMoneyTools.length === 1 ? "" : "s"} — fires without approval
        </div>
      )}

      {mcpTools.length > 0 && (
        <div className="mt-3 space-y-1">
          <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
            Tools
          </div>
          <div className="flex flex-wrap gap-2">
            {mcpTools.map((tool) => (
              <div
                key={tool.tool_name}
                className="flex items-center gap-1.5 rounded border border-border-subtle bg-surface px-2 py-1 text-[11px] text-ink-secondary"
              >
                <span className="font-mono font-medium text-ink-primary">{tool.tool_name}</span>
                <span className="text-ink-tertiary">·</span>
                <span>{tool.commitment_kind}</span>
                <span className="text-ink-tertiary">·</span>
                <span
                  className={
                    tool.execution_policy === "auto_execute"
                      ? "font-medium text-amber-600 dark:text-amber-400"
                      : "text-ink-secondary"
                  }
                >
                  {tool.execution_policy}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {pendingForServer.length > 0 && (
        <div className="mt-3 rounded-lg border border-border-subtle bg-surface-raised px-3 py-2 text-[12px] text-ink-secondary">
          {pendingForServer.length} change request
          {pendingForServer.length === 1 ? "" : "s"} awaiting approval.
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onManageTools}
          disabled={!canWrite}
          className="cc-btn cc-btn-secondary disabled:opacity-50"
        >
          <PlugZap size={14} strokeWidth={1.8} />
          Manage tools
        </button>
        <button
          type="button"
          onClick={onManageTools}
          disabled={!canWrite}
          className="cc-btn cc-btn-secondary disabled:opacity-50"
        >
          <KeyRound size={14} strokeWidth={1.8} />
          Manage credentials
        </button>
      </div>
    </Card>
  );
}

// ─── Shared form primitives ───────────────────────────────────────────────

function McpFieldset({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3 rounded-lg border border-border-subtle bg-surface-raised p-4">
      <legend className="px-1 font-mono text-[11px] uppercase tracking-[0.14em] text-ink-tertiary">
        {legend}
      </legend>
      {children}
    </fieldset>
  );
}

function McpText({
  label,
  value,
  onChange,
  placeholder,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        className="h-11 w-full rounded border border-border-subtle bg-surface px-3 text-[14px] text-ink-primary focus:border-gold-primary focus:outline-none sm:h-10"
      />
    </label>
  );
}

function McpWriteOnlyInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <input
        type="password"
        autoComplete="new-password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-11 w-full rounded border border-border-subtle bg-surface px-3 text-[14px] text-ink-primary focus:border-gold-primary focus:outline-none sm:h-10"
      />
    </label>
  );
}

function McpField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </div>
      <div className="mt-1 break-words text-[13px] leading-relaxed text-ink-secondary">
        {value || "—"}
      </div>
    </div>
  );
}

function FormError({ message }: { message: string }) {
  return (
    <div className="rounded border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
      {message}
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────

type McpConnectionStatus = "active" | "pending_approval" | "oauth_expired";

function deriveConnectionStatus(
  connector: TenantConnectorConfiguration,
  pendingCount: number
): McpConnectionStatus {
  if (pendingCount > 0) return "pending_approval";
  if (connector.status === "active") return "active";
  return "oauth_expired";
}

function mcpConnectionStatusMeta(status: McpConnectionStatus): {
  label: string;
  tone: "success" | "warning" | "neutral";
  icon: typeof CheckCircle2 | typeof CircleAlert;
} {
  if (status === "active") return { label: "Active", tone: "success", icon: CheckCircle2 };
  if (status === "pending_approval") return { label: "Pending approval", tone: "warning", icon: CircleAlert };
  return { label: "OAuth expired", tone: "warning", icon: CircleAlert };
}
