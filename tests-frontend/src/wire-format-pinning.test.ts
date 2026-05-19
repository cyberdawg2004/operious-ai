import { test } from 'node:test';
import { deepStrictEqual } from 'node:assert';
import { join } from 'node:path';
import { ROOT, readText } from './util.js';

/**
 * Wire-format pinning.
 *
 * For each frontend enum mirror, parse the backend Python enum and confirm
 * the two sets of wire-format string values match exactly. If a backend
 * enum drifts (rename, addition, removal) without a matching frontend
 * change, this test fails — exactly as intended.
 *
 * We deliberately do NOT use a lexer / Python parser here; the backend
 * enum files are highly stylized and a regex over `NAME = "value"` lines
 * within a `class X(StrEnum):` block is precise enough.
 */

const extractStrEnum = (
  python: string,
  className: string,
): readonly string[] => {
  const classMatch = python.match(
    new RegExp(`class\\s+${className}\\(StrEnum\\):([\\s\\S]*?)(?=\\nclass\\s+\\w+\\(|\\n__all__|$)`),
  );
  if (!classMatch) {
    throw new Error(`could not locate StrEnum class ${className}`);
  }
  const body = classMatch[1];
  const lines = body.split('\n');
  const values: string[] = [];
  for (const line of lines) {
    const m = line.match(/^\s+[A-Z_][A-Z0-9_]*\s*=\s*"([^"]+)"/);
    if (m) values.push(m[1]);
  }
  values.sort();
  return values;
};

const extractIntEnum = (
  python: string,
  className: string,
): readonly number[] => {
  const classMatch = python.match(
    new RegExp(`class\\s+${className}\\(IntEnum\\):([\\s\\S]*?)(?=\\nclass\\s+\\w+\\(|\\n__all__|$)`),
  );
  if (!classMatch) {
    throw new Error(`could not locate IntEnum class ${className}`);
  }
  const body = classMatch[1];
  const lines = body.split('\n');
  const values: number[] = [];
  for (const line of lines) {
    const m = line.match(/^\s+[A-Z_][A-Z0-9_]*\s*=\s*(\d+)/);
    if (m) values.push(parseInt(m[1], 10));
  }
  values.sort((a, b) => a - b);
  return values;
};

const tsMirrorIntValues = (
  source: string,
  constName: string,
): readonly number[] => {
  const m = source.match(
    new RegExp(`export const ${constName}\\s*=\\s*\\{([\\s\\S]*?)\\}\\s*as\\s+const`),
  );
  if (!m) {
    throw new Error(`could not locate TS mirror const ${constName}`);
  }
  const body = m[1];
  const values: number[] = [];
  for (const line of body.split('\n')) {
    const v = line.match(/^\s*[A-Z_][A-Z0-9_]*:\s*(\d+)\s*,?/);
    if (v) values.push(parseInt(v[1], 10));
  }
  values.sort((a, b) => a - b);
  return values;
};

const tsMirrorValues = (
  source: string,
  constName: string,
): readonly string[] => {
  const m = source.match(
    new RegExp(`export const ${constName}\\s*=\\s*\\{([\\s\\S]*?)\\}\\s*as\\s+const`),
  );
  if (!m) {
    throw new Error(`could not locate TS mirror const ${constName}`);
  }
  const body = m[1];
  const values: string[] = [];
  for (const line of body.split('\n')) {
    const v = line.match(/^\s*[A-Z_][A-Z0-9_]*:\s*'([^']+)'/);
    if (v) values.push(v[1]);
  }
  values.sort();
  return values;
};

interface Pinning {
  readonly backendFile: string;
  readonly backendClass: string;
  readonly tsFile: string;
  readonly tsConst: string;
}

const PINNINGS: readonly Pinning[] = [
  {
    backendFile: 'apps/backend/app/session/enums.py',
    backendClass: 'SessionLifecyclePhase',
    tsFile: 'packages/types/src/session.ts',
    tsConst: 'SessionLifecyclePhase',
  },
  {
    backendFile: 'apps/backend/app/session/enums.py',
    backendClass: 'SessionScope',
    tsFile: 'packages/types/src/session.ts',
    tsConst: 'SessionScope',
  },
  {
    backendFile: 'apps/backend/app/session/enums.py',
    backendClass: 'SessionEventKind',
    tsFile: 'packages/types/src/session.ts',
    tsConst: 'SessionEventKind',
  },
  {
    backendFile: 'apps/backend/app/session/enums.py',
    backendClass: 'SessionContinuityMode',
    tsFile: 'packages/types/src/session.ts',
    tsConst: 'SessionContinuityMode',
  },
  {
    backendFile: 'apps/backend/app/session/enums.py',
    backendClass: 'SessionCorrelationKind',
    tsFile: 'packages/types/src/session.ts',
    tsConst: 'SessionCorrelationKind',
  },
  {
    backendFile: 'apps/backend/app/governance/enums.py',
    backendClass: 'Decision',
    tsFile: 'packages/types/src/governance.ts',
    tsConst: 'GovernanceDecision',
  },
  {
    backendFile: 'apps/backend/app/governance/enums.py',
    backendClass: 'EnforcementStage',
    tsFile: 'packages/types/src/governance.ts',
    tsConst: 'EnforcementStage',
  },
  {
    backendFile: 'apps/backend/app/governance/enums.py',
    backendClass: 'RestrictionKind',
    tsFile: 'packages/types/src/governance.ts',
    tsConst: 'RestrictionKind',
  },
  // 2.5-J1: topology vocabulary alignment.
  {
    backendFile: 'apps/backend/app/coordination/topology/enums.py',
    backendClass: 'CoordinationTopologyDecision',
    tsFile: 'packages/types/src/topology.ts',
    tsConst: 'CoordinationTopologyDecision',
  },
  {
    backendFile: 'apps/backend/app/coordination/topology/enums.py',
    backendClass: 'TopologyNodeKind',
    tsFile: 'packages/types/src/topology.ts',
    tsConst: 'TopologyNodeKind',
  },
  {
    backendFile: 'apps/backend/app/coordination/topology/enums.py',
    backendClass: 'TopologyEdgeKind',
    tsFile: 'packages/types/src/topology.ts',
    tsConst: 'TopologyEdgeKind',
  },
  {
    backendFile: 'apps/backend/app/coordination/topology/enums.py',
    backendClass: 'TopologyBoundaryKind',
    tsFile: 'packages/types/src/topology.ts',
    tsConst: 'TopologyBoundaryKind',
  },
  {
    backendFile: 'apps/backend/app/coordination/topology/enums.py',
    backendClass: 'TopologyBoundaryCrossing',
    tsFile: 'packages/types/src/topology.ts',
    tsConst: 'TopologyBoundaryCrossing',
  },
  // 2.5-J1: cross-substrate trace-node kind alignment.
  {
    backendFile: 'apps/backend/app/observability/trace_node_kind.py',
    backendClass: 'TraceNodeKind',
    tsFile: 'packages/types/src/trace.ts',
    tsConst: 'TraceNodeKind',
  },
  // PR-A2: arbitration vocabulary alignment.
  // Pre-PR-A2 only the *outcome* enum was mirrored on the FE and the
  // finding wire used short literals + a `kind` field while the BE
  // emitted namespaced codes on a `code` field — silent drift on every
  // arbitration response. The four authority/verdict/conflict/deadlock
  // enums were missing entirely.
  {
    backendFile: 'apps/backend/app/arbitration/enums.py',
    backendClass: 'ArbitrationOutcome',
    tsFile: 'packages/types/src/arbitration.ts',
    tsConst: 'ArbitrationOutcome',
  },
  {
    backendFile: 'apps/backend/app/arbitration/enums.py',
    backendClass: 'ArbitrationAuthorityLevel',
    tsFile: 'packages/types/src/arbitration.ts',
    tsConst: 'ArbitrationAuthorityLevel',
  },
  {
    backendFile: 'apps/backend/app/arbitration/enums.py',
    backendClass: 'ArbitrationVerdictKind',
    tsFile: 'packages/types/src/arbitration.ts',
    tsConst: 'ArbitrationVerdictKind',
  },
  {
    backendFile: 'apps/backend/app/arbitration/enums.py',
    backendClass: 'ArbitrationConflictKind',
    tsFile: 'packages/types/src/arbitration.ts',
    tsConst: 'ArbitrationConflictKind',
  },
  {
    backendFile: 'apps/backend/app/arbitration/enums.py',
    backendClass: 'ArbitrationDeadlockKind',
    tsFile: 'packages/types/src/arbitration.ts',
    tsConst: 'ArbitrationDeadlockKind',
  },
  {
    backendFile: 'apps/backend/app/arbitration/taxonomy.py',
    backendClass: 'ArbitrationFindingCode',
    tsFile: 'packages/types/src/arbitration.ts',
    tsConst: 'ArbitrationFindingCode',
  },
  // PR-A2: boundary substrate alignment — five vocabularies, zero
  // frontend mirrors pre-PR-A2. Adapter classification, message
  // taxonomy, normalisation outcomes, and replay disposition were
  // un-pinned wire vocabularies any FE renderer had to guess.
  {
    backendFile: 'apps/backend/app/boundary/enums.py',
    backendClass: 'BoundaryDirection',
    tsFile: 'packages/types/src/boundary.ts',
    tsConst: 'BoundaryDirection',
  },
  {
    backendFile: 'apps/backend/app/boundary/enums.py',
    backendClass: 'BoundarySourceType',
    tsFile: 'packages/types/src/boundary.ts',
    tsConst: 'BoundarySourceType',
  },
  {
    backendFile: 'apps/backend/app/boundary/enums.py',
    backendClass: 'BoundaryMessageType',
    tsFile: 'packages/types/src/boundary.ts',
    tsConst: 'BoundaryMessageType',
  },
  {
    backendFile: 'apps/backend/app/boundary/enums.py',
    backendClass: 'BoundaryNormalizationStatus',
    tsFile: 'packages/types/src/boundary.ts',
    tsConst: 'BoundaryNormalizationStatus',
  },
  {
    backendFile: 'apps/backend/app/boundary/enums.py',
    backendClass: 'BoundaryReplayDisposition',
    tsFile: 'packages/types/src/boundary.ts',
    tsConst: 'BoundaryReplayDisposition',
  },
  // PR-A2: translation substrate alignment — eight vocabularies.
  {
    backendFile: 'apps/backend/app/boundary/translation/enums.py',
    backendClass: 'TranslationDirection',
    tsFile: 'packages/types/src/translation.ts',
    tsConst: 'TranslationDirection',
  },
  {
    backendFile: 'apps/backend/app/boundary/translation/enums.py',
    backendClass: 'TranslationStatus',
    tsFile: 'packages/types/src/translation.ts',
    tsConst: 'TranslationStatus',
  },
  {
    backendFile: 'apps/backend/app/boundary/translation/enums.py',
    backendClass: 'TranslationProviderKind',
    tsFile: 'packages/types/src/translation.ts',
    tsConst: 'TranslationProviderKind',
  },
  {
    backendFile: 'apps/backend/app/boundary/translation/enums.py',
    backendClass: 'SemanticPreservationStatus',
    tsFile: 'packages/types/src/translation.ts',
    tsConst: 'SemanticPreservationStatus',
  },
  {
    backendFile: 'apps/backend/app/boundary/translation/enums.py',
    backendClass: 'LocalizationFormality',
    tsFile: 'packages/types/src/translation.ts',
    tsConst: 'LocalizationFormality',
  },
  {
    backendFile: 'apps/backend/app/boundary/translation/enums.py',
    backendClass: 'TranslationFindingKind',
    tsFile: 'packages/types/src/translation.ts',
    tsConst: 'TranslationFindingKind',
  },
  {
    backendFile: 'apps/backend/app/boundary/translation/enums.py',
    backendClass: 'TranslationTraceKind',
    tsFile: 'packages/types/src/translation.ts',
    tsConst: 'TranslationTraceKind',
  },
  // PR-A2: voice substrate alignment — six vocabularies.
  {
    backendFile: 'apps/backend/app/boundary/voice/enums.py',
    backendClass: 'VoiceDirection',
    tsFile: 'packages/types/src/voice.ts',
    tsConst: 'VoiceDirection',
  },
  {
    backendFile: 'apps/backend/app/boundary/voice/enums.py',
    backendClass: 'VoiceStatus',
    tsFile: 'packages/types/src/voice.ts',
    tsConst: 'VoiceStatus',
  },
  {
    backendFile: 'apps/backend/app/boundary/voice/enums.py',
    backendClass: 'VoiceProviderKind',
    tsFile: 'packages/types/src/voice.ts',
    tsConst: 'VoiceProviderKind',
  },
  {
    backendFile: 'apps/backend/app/boundary/voice/enums.py',
    backendClass: 'AudioFormat',
    tsFile: 'packages/types/src/voice.ts',
    tsConst: 'AudioFormat',
  },
  {
    backendFile: 'apps/backend/app/boundary/voice/enums.py',
    backendClass: 'VoiceFindingKind',
    tsFile: 'packages/types/src/voice.ts',
    tsConst: 'VoiceFindingKind',
  },
  {
    backendFile: 'apps/backend/app/boundary/voice/enums.py',
    backendClass: 'VoiceTraceKind',
    tsFile: 'packages/types/src/voice.ts',
    tsConst: 'VoiceTraceKind',
  },
];

for (const pinning of PINNINGS) {
  test(`wire-format pinned: ${pinning.backendClass} ↔ ${pinning.tsConst}`, () => {
    const py = readText(join(ROOT, pinning.backendFile));
    const ts = readText(join(ROOT, pinning.tsFile));
    const backend = extractStrEnum(py, pinning.backendClass);
    const frontend = tsMirrorValues(ts, pinning.tsConst);
    deepStrictEqual(
      frontend,
      backend,
      `wire-format drift: backend ${pinning.backendClass} = ${JSON.stringify(backend)}, frontend ${pinning.tsConst} = ${JSON.stringify(frontend)}`,
    );
  });
}

// ─── 2.5-J1: IntEnum pinning ─────────────────────────────────────────

interface IntPinning {
  readonly backendFile: string;
  readonly backendClass: string;
  readonly tsFile: string;
  readonly tsConst: string;
}

const INT_PINNINGS: readonly IntPinning[] = [
  {
    backendFile: 'apps/backend/app/governance/enums.py',
    backendClass: 'ViolationSeverity',
    tsFile: 'packages/types/src/governance.ts',
    tsConst: 'ViolationSeverity',
  },
];

for (const pinning of INT_PINNINGS) {
  test(`wire-format pinned: ${pinning.backendClass} ↔ ${pinning.tsConst} (IntEnum)`, () => {
    const py = readText(join(ROOT, pinning.backendFile));
    const ts = readText(join(ROOT, pinning.tsFile));
    const backend = extractIntEnum(py, pinning.backendClass);
    const frontend = tsMirrorIntValues(ts, pinning.tsConst);
    deepStrictEqual(
      frontend,
      backend,
      `wire-format drift: backend ${pinning.backendClass} = ${JSON.stringify(backend)}, frontend ${pinning.tsConst} = ${JSON.stringify(frontend)}`,
    );
  });
}
