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
