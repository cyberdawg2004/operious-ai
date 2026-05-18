import { brand } from '@operious/shared';
import type {
  ArbitrationDecisionDto,
  GovernanceTraceDto,
  MemoryProposalDto,
  Page,
  QueueItemDto,
  RecommendationDto,
  SOPProposalDto,
  SessionTimelineEventDto,
  TopologyGraphDto,
  TraceBundleDto,
} from '@operious/types';

/**
 * Deterministic mock fixtures.
 *
 * These exist purely to render the foundations of the Command Center while
 * the backend HTTP API is still being scaffolded. They are byte-stable across
 * renders — the same seed produces the same values, every time.
 *
 * When the backend API ships, this module is the only file that has to be
 * removed. Every UI component already routes through @operious/sdk hooks.
 */

const at = (offsetMinutes: number): string =>
  new Date(Date.UTC(2026, 4, 15, 10, 0, 0) + offsetMinutes * 60_000).toISOString();

export const QUEUE_FIXTURE: Page<QueueItemDto> = {
  observedAt: at(60),
  items: [
    {
      itemId: brand<'CorrelationId'>('cid-q-001'),
      kind: 'escalated_session',
      status: 'open',
      classification: 'session_human_handoff',
      title: 'Session escalated for human handoff',
      summary:
        'Customer requested supervisor escalation; SOP requires human authority confirmation.',
      sessionId: brand<'SessionId'>('sess-9f1a-001'),
      tenantLabel: 'acme-financial',
      raisedAt: at(0),
      observedAt: at(0),
      lineage: {
        correlationId: brand<'CorrelationId'>('corr-9f1a-0001'),
        sequence: 14,
        observedAt: at(0),
        tenantId: brand<'TenantId'>('tenant-acme'),
      },
    },
    {
      itemId: brand<'CorrelationId'>('cid-q-002'),
      kind: 'denied_governance_decision',
      status: 'open',
      classification: 'governance_deny',
      title: 'Governance denied a refund authorisation',
      summary:
        'Pre-execution governance refused the proposed refund operation; awaiting human review.',
      sessionId: brand<'SessionId'>('sess-9f1a-014'),
      tenantLabel: 'acme-financial',
      raisedAt: at(15),
      observedAt: at(15),
      lineage: {
        correlationId: brand<'CorrelationId'>('corr-9f1a-0014'),
        sequence: 22,
        observedAt: at(15),
        tenantId: brand<'TenantId'>('tenant-acme'),
      },
    },
    {
      itemId: brand<'CorrelationId'>('cid-q-003'),
      kind: 'arbitration_deadlock',
      status: 'claimed',
      classification: 'arbitration_deadlock',
      title: 'Arbitration deadlock between supervisors',
      summary:
        'Supervisor A and Supervisor B disagree on de-escalation pathway. Arbitration interpreted DEADLOCK_DETECTED.',
      sessionId: brand<'SessionId'>('sess-44b2-007'),
      tenantLabel: 'rivermark-logistics',
      raisedAt: at(32),
      observedAt: at(32),
      lineage: {
        correlationId: brand<'CorrelationId'>('corr-44b2-0007'),
        sequence: 11,
        observedAt: at(32),
        tenantId: brand<'TenantId'>('tenant-rivermark'),
      },
    },
    {
      itemId: brand<'CorrelationId'>('cid-q-004'),
      kind: 'topology_escalation',
      status: 'open',
      classification: 'topology_depth_exceeded',
      title: 'Topology escalation: chain depth exceeded',
      summary:
        'Coordination chain depth exceeded MAX_CHAIN_DEPTH=4. Topology refused further authority traversal.',
      tenantLabel: 'pillarboard-cs',
      raisedAt: at(48),
      observedAt: at(48),
      lineage: {
        correlationId: brand<'CorrelationId'>('corr-2da0-0048'),
        sequence: 7,
        observedAt: at(48),
        tenantId: brand<'TenantId'>('tenant-pillar'),
      },
    },
    {
      itemId: brand<'CorrelationId'>('cid-q-005'),
      kind: 'denied_governance_decision',
      status: 'deferred',
      classification: 'governance_require_approval',
      title: 'Governance demands approval for capability use',
      summary:
        'Capability `tool.refund.full` requires REQUIRE_APPROVAL. Awaiting approver action.',
      sessionId: brand<'SessionId'>('sess-acce-021'),
      tenantLabel: 'lyra-payments',
      raisedAt: at(70),
      observedAt: at(70),
      lineage: {
        correlationId: brand<'CorrelationId'>('corr-acce-0021'),
        sequence: 19,
        observedAt: at(70),
        tenantId: brand<'TenantId'>('tenant-lyra'),
      },
    },
  ],
};

const SAMPLE_TIMELINE: readonly SessionTimelineEventDto[] = [
  {
    eventId: brand<'SessionEventId'>('evt-9f1a-001-0'),
    sessionId: brand<'SessionId'>('sess-9f1a-001'),
    sequence: 0,
    kind: 'session_opened',
    continuityMode: 'synchronous',
    observedAt: at(-30),
    correlationId: brand<'CorrelationId'>('corr-9f1a-0000'),
    summary: 'Session opened from boundary ingress (zendesk).',
    payload: { source: 'zendesk', tenant: 'acme-financial' },
  },
  {
    eventId: brand<'SessionEventId'>('evt-9f1a-001-1'),
    sessionId: brand<'SessionId'>('sess-9f1a-001'),
    sequence: 1,
    kind: 'context_attached',
    continuityMode: 'synchronous',
    observedAt: at(-25),
    correlationId: brand<'CorrelationId'>('corr-9f1a-0001'),
    summary: 'Operational context bound to session.',
    payload: { contextDigest: 'sha256:abc...' },
  },
  {
    eventId: brand<'SessionEventId'>('evt-9f1a-001-2'),
    sessionId: brand<'SessionId'>('sess-9f1a-001'),
    sequence: 2,
    kind: 'lineage_linked',
    continuityMode: 'synchronous',
    observedAt: at(-20),
    correlationId: brand<'CorrelationId'>('corr-9f1a-0002'),
    summary: 'Linked to parent session for follow-up.',
    payload: { parentSessionId: 'sess-9f0e-099' },
  },
  {
    eventId: brand<'SessionEventId'>('evt-9f1a-001-3'),
    sessionId: brand<'SessionId'>('sess-9f1a-001'),
    sequence: 3,
    kind: 'lifecycle_reclassified',
    continuityMode: 'synchronous',
    observedAt: at(-5),
    correlationId: brand<'CorrelationId'>('corr-9f1a-0003'),
    summary: 'Lifecycle reclassified ACTIVE → DORMANT pending escalation.',
    payload: { from: 'active', to: 'dormant' },
  },
];

const SAMPLE_GOVERNANCE: GovernanceTraceDto = {
  traceId: brand<'GovernanceTraceId'>('govtrace-9f1a-001'),
  evaluationId: brand<'GovernanceEvaluationId'>('goveval-9f1a-001'),
  stage: 'pre_execution',
  decision: 'require_approval',
  violations: [
    {
      ruleId: 'capability.refund.full',
      severity: 30, // ViolationSeverity.HIGH (2.5-J1 wire-pinned)
      message: 'Refund cap exceeds tenant approval floor.',
    },
  ],
  restrictions: [
    {
      kind: 'rate_limit',
      description: 'Tenant cap: 5 refunds / hour',
      metadata: { window: 3600 },
    },
  ],
  observedAt: at(-5),
  lineage: {
    correlationId: brand<'CorrelationId'>('corr-9f1a-0003'),
    sequence: 12,
    observedAt: at(-5),
    parentCorrelationId: brand<'CorrelationId'>('corr-9f1a-0002'),
  },
};

const SAMPLE_ARBITRATION: ArbitrationDecisionDto = {
  decisionId: brand<'ArbitrationDecisionId'>('arbdec-9f1a-001'),
  caseId: brand<'ArbitrationCaseId'>('arbcase-9f1a-001'),
  outcome: 'arbitration_inconclusive',
  precedingAuthority: 'governance',
  findings: [
    {
      kind: 'authority_precedence_applied',
      summary: 'Governance precedence applied; arbitration deferred to human approval.',
      evidence: { restrictiveDecision: 'require_approval' },
    },
  ],
  observedAt: at(0),
  lineage: {
    correlationId: brand<'CorrelationId'>('corr-9f1a-0004'),
    sequence: 13,
    observedAt: at(0),
    parentCorrelationId: brand<'CorrelationId'>('corr-9f1a-0003'),
  },
};

export const TRACE_BUNDLE_FIXTURE: TraceBundleDto = {
  correlationId: brand<'CorrelationId'>('corr-9f1a-0003'),
  sessionId: brand<'SessionId'>('sess-9f1a-001'),
  observedAt: at(5),
  replayDigest: 'sha256:7c1ad8f3aa90c47abce9bb...e92',
  nodes: [
    ...SAMPLE_TIMELINE.map(
      (evt) =>
        ({
          kind: 'session_timeline_event',
          payload: evt,
        }) as const,
    ),
    {
      kind: 'governance_trace',
      payload: SAMPLE_GOVERNANCE,
    },
    {
      kind: 'agent_execution_trace',
      payload: {
        executionId: brand<'AgentExecutionId'>('aex-9f1a-001'),
        agentLabel: 'frontline.support.v3',
        inputDigest: 'sha256:1aa...',
        outputDigest: 'sha256:b21...',
        observedAt: at(-2),
        durationMs: 412,
        lineage: {
          correlationId: brand<'CorrelationId'>('corr-9f1a-0003'),
          sequence: 11,
          observedAt: at(-2),
          parentCorrelationId: brand<'CorrelationId'>('corr-9f1a-0002'),
        },
      },
    },
    {
      kind: 'arbitration_decision',
      payload: SAMPLE_ARBITRATION,
    },
  ],
};

export const SESSION_TIMELINE_FIXTURE = {
  sessionId: brand<'SessionId'>('sess-9f1a-001'),
  events: SAMPLE_TIMELINE,
};

export const TOPOLOGY_FIXTURE: TopologyGraphDto = {
  observedAt: at(0),
  version: 'v3.2.0',
  nodes: [
    {
      nodeId: brand<'TopologyNodeId'>('node-frontline'),
      kind: 'agent',
      label: 'frontline.support.v3',
      agentId: brand<'AgentId'>('agent-frontline-v3'),
      tenantScope: 'tenant-acme',
      metadata: { role: 'frontline' },
    },
    {
      nodeId: brand<'TopologyNodeId'>('node-sme'),
      kind: 'agent',
      label: 'sme.refunds.v2',
      agentId: brand<'AgentId'>('agent-sme-refunds-v2'),
      tenantScope: 'tenant-acme',
      metadata: { role: 'sme' },
    },
    {
      nodeId: brand<'TopologyNodeId'>('node-supervisor'),
      kind: 'supervisor',
      label: 'supervisor.tier-1',
      tenantScope: 'tenant-acme',
      metadata: { policy: 'most-restrictive-wins' },
    },
    {
      nodeId: brand<'TopologyNodeId'>('node-gov-system'),
      kind: 'system',
      label: 'pii.compliance.acme',
      metadata: { framework: 'GDPR/CCPA' },
    },
    {
      nodeId: brand<'TopologyNodeId'>('node-broadcast'),
      kind: 'broadcast',
      label: 'tenant.acme broadcast',
      metadata: { isolation: 'tenant' },
    },
    {
      nodeId: brand<'TopologyNodeId'>('node-external'),
      kind: 'external',
      label: 'human.tier-2.acme',
      metadata: { sla: 'P15M' },
    },
  ],
  edges: [
    // 2.5-J1: edge kinds align with the backend wire-format
    // (`TopologyEdgeKind` in `app/coordination/topology/enums.py`).
    {
      edgeId: brand<'TopologyEdgeId'>('edge-frontline-sme'),
      kind: 'peer',
      source: brand<'TopologyNodeId'>('node-frontline'),
      target: brand<'TopologyNodeId'>('node-sme'),
      label: 'declared',
      metadata: { maxChainDepth: 4 },
    },
    {
      edgeId: brand<'TopologyEdgeId'>('edge-sme-supervisor'),
      kind: 'escalation',
      source: brand<'TopologyNodeId'>('node-sme'),
      target: brand<'TopologyNodeId'>('node-supervisor'),
      label: 'escalation',
      metadata: {},
    },
    {
      edgeId: brand<'TopologyEdgeId'>('edge-supervisor-external'),
      kind: 'handoff',
      source: brand<'TopologyNodeId'>('node-supervisor'),
      target: brand<'TopologyNodeId'>('node-external'),
      label: 'human handoff',
      metadata: {},
    },
    {
      edgeId: brand<'TopologyEdgeId'>('edge-frontline-gov'),
      kind: 'system',
      source: brand<'TopologyNodeId'>('node-frontline'),
      target: brand<'TopologyNodeId'>('node-gov-system'),
      label: 'governed by',
      metadata: {},
    },
    {
      edgeId: brand<'TopologyEdgeId'>('edge-supervisor-broadcast'),
      kind: 'broadcast',
      source: brand<'TopologyNodeId'>('node-supervisor'),
      target: brand<'TopologyNodeId'>('node-broadcast'),
      label: 'broadcast',
      metadata: {},
    },
  ],
};

export const MEMORY_PROPOSALS_FIXTURE: Page<MemoryProposalDto> = {
  observedAt: at(0),
  items: [
    {
      proposalId: brand<'MemoryProposalId'>('mem-prop-001'),
      kind: 'communication_pattern',
      status: 'pending_approval',
      title: 'De-escalation phrase: refund delays',
      summary:
        'Adopt a calmer phrasing for refund-delay responses based on supervisor evaluations.',
      proposedBy: 'supervisor',
      diff: [
        { path: 'phrase', changeType: 'modified', before: 'We will get back to you', after: 'We have escalated this and will follow up by EOD' },
      ],
      observedAt: at(0),
      lineage: {
        correlationId: brand<'CorrelationId'>('corr-mem-001'),
        sequence: 4,
        observedAt: at(0),
      },
    },
    {
      proposalId: brand<'MemoryProposalId'>('mem-prop-002'),
      kind: 'escalation_pattern',
      status: 'pending_approval',
      title: 'Escalate sooner on capability deny',
      summary:
        'When governance returns DENY for capabilities, route to human within 60s rather than 5m.',
      proposedBy: 'system',
      diff: [
        { path: 'thresholds.escalation_after_seconds', changeType: 'modified', before: '300', after: '60' },
      ],
      observedAt: at(5),
      lineage: {
        correlationId: brand<'CorrelationId'>('corr-mem-002'),
        sequence: 5,
        observedAt: at(5),
      },
    },
  ],
};

export const SOP_PROPOSALS_FIXTURE: Page<SOPProposalDto> = {
  observedAt: at(0),
  items: [
    {
      proposalId: brand<'SOPProposalId'>('sop-prop-001'),
      status: 'pending_approval',
      sopName: 'Refund Approval — Tier 1',
      version: 'v1.4-draft',
      summary: 'Tighten refund cap and require supervisor pre-confirmation above $500.',
      diff: [
        { path: 'cap.usd', changeType: 'modified', before: '1000', after: '500' },
        { path: 'requires_pre_confirmation', changeType: 'added', after: 'true' },
      ],
      observedAt: at(0),
      lineage: {
        correlationId: brand<'CorrelationId'>('corr-sop-001'),
        sequence: 2,
        observedAt: at(0),
      },
    },
  ],
};

export const RECOMMENDATIONS_FIXTURE: Page<RecommendationDto> = {
  observedAt: at(0),
  items: [
    {
      recommendationId: brand<'RecommendationId'>('rec-001'),
      kind: 'workflow_ambiguity',
      title: 'Ambiguous SOP step in tier-1 refunds',
      summary: 'Step 4 of refund SOP allows two compatible escalation paths; clarify precedence.',
      evidence: { conflicting_paths: 2, observed_in_sessions: 14 },
      observedAt: at(0),
      lineage: {
        correlationId: brand<'CorrelationId'>('corr-rec-001'),
        sequence: 1,
        observedAt: at(0),
      },
    },
    {
      recommendationId: brand<'RecommendationId'>('rec-002'),
      kind: 'operational_bottleneck',
      title: 'Bottleneck: PII review queue',
      summary: 'PII review wait time exceeded SLA in 8% of sessions over the last week.',
      evidence: { sla_violation_rate_pct: 8 },
      observedAt: at(15),
      lineage: {
        correlationId: brand<'CorrelationId'>('corr-rec-002'),
        sequence: 2,
        observedAt: at(15),
      },
    },
  ],
};
