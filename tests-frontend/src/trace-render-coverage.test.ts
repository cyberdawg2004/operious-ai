import { test } from 'node:test';
import { deepStrictEqual } from 'node:assert';
import { join } from 'node:path';
import { ROOT, readText } from './util.js';

/**
 * Trace renderer coverage invariant.
 *
 * Forecloses the regression PR-A2 was created to close: the
 * `TraceNodeDto` union covered all 9 backend `TraceNodeKind` values,
 * but the `TraceTimeline` renderer only handled 4 of them. The other
 * 5 (`topology_evaluation`, `boundary_ingress`, `boundary_egress`,
 * `translation`, `voice`) silently fell through to "unknown" tone and
 * lost forensic signal.
 *
 * This test pins coverage at the source level: every `TraceNodeKind`
 * value MUST appear in
 *
 *   1. the `traceTone` map (a tone for every kind);
 *   2. the `titleFor` switch (a human-readable title for every kind);
 *   3. the `stableKeyFor` switch (a stable React key projection for
 *      every kind, so reconciliation survives bundle reorderings).
 *
 * Static / source-level matching is sufficient (and matches the
 * pattern used by `wire-format-pinning.test.ts`) — full TSX render
 * tests would require a DOM harness this workspace does not own, but
 * the discriminated-union exhaustiveness is what we actually need to
 * pin: any future kind added to `TraceNodeKind` must adopt the three
 * renderer surfaces or this test fails.
 */

const TRACE_TS = join(ROOT, 'packages', 'types', 'src', 'trace.ts');
const TIMELINE_TSX = join(
  ROOT,
  'packages',
  'observability',
  'src',
  'trace-timeline.tsx',
);

const extractTraceNodeKindValues = (): readonly string[] => {
  const source = readText(TRACE_TS);
  const m = source.match(
    /export const TraceNodeKind\s*=\s*\{([\s\S]*?)\}\s*as\s+const/,
  );
  if (!m) throw new Error('cannot locate TraceNodeKind in trace.ts');
  const body = m[1];
  const values: string[] = [];
  for (const line of body.split('\n')) {
    const v = line.match(/^\s*[A-Z_][A-Z0-9_]*\s*:\s*'([^']+)'/);
    if (v) values.push(v[1]);
  }
  values.sort();
  return values;
};

const extractTraceToneKeys = (source: string): readonly string[] => {
  const m = source.match(
    /const traceTone:\s*Record<TraceNodeDto\['kind'\],\s*BadgeTone>\s*=\s*\{([\s\S]*?)\};/,
  );
  if (!m) throw new Error('cannot locate traceTone map in trace-timeline.tsx');
  const body = m[1];
  const keys: string[] = [];
  for (const line of body.split('\n')) {
    const v = line.match(/^\s*([a-z_][a-z0-9_]*)\s*:/);
    if (v) keys.push(v[1]);
  }
  keys.sort();
  return keys;
};

const extractSwitchCases = (
  source: string,
  fnSignaturePattern: RegExp,
): readonly string[] => {
  const fnMatch = source.match(fnSignaturePattern);
  if (!fnMatch) {
    throw new Error(
      `cannot locate switch fn matching ${fnSignaturePattern}`,
    );
  }
  // Walk forward from the match capturing every `case 'X':` until we
  // see the closing `};` of the function body. The functions in
  // trace-timeline.tsx use the closed pattern
  //   const fn = (node: TraceNodeDto): T => { switch (node.kind) { … } };
  // so the next `};` after the match is the function's terminator.
  const start = fnMatch.index ?? 0;
  const tail = source.slice(start);
  const endIdx = tail.indexOf('\n};');
  const body = endIdx === -1 ? tail : tail.slice(0, endIdx);
  const cases: string[] = [];
  for (const caseMatch of body.matchAll(/case\s+'([^']+)'\s*:/g)) {
    cases.push(caseMatch[1]);
  }
  cases.sort();
  return cases;
};

test('every TraceNodeKind has a tone in trace-timeline.tsx', () => {
  const kinds = extractTraceNodeKindValues();
  const source = readText(TIMELINE_TSX);
  const toneKeys = extractTraceToneKeys(source);
  deepStrictEqual(
    toneKeys,
    kinds,
    `traceTone map drift — TraceNodeKind values = ${JSON.stringify(
      kinds,
    )}, traceTone keys = ${JSON.stringify(toneKeys)}`,
  );
});

test('every TraceNodeKind has a titleFor case', () => {
  const kinds = extractTraceNodeKindValues();
  const source = readText(TIMELINE_TSX);
  const cases = extractSwitchCases(
    source,
    /const titleFor\s*=\s*\(node: TraceNodeDto\)\s*:\s*string\s*=>/,
  );
  deepStrictEqual(
    cases,
    kinds,
    `titleFor switch drift — TraceNodeKind values = ${JSON.stringify(
      kinds,
    )}, titleFor cases = ${JSON.stringify(cases)}`,
  );
});

test('every TraceNodeKind has a stableKeyFor case', () => {
  const kinds = extractTraceNodeKindValues();
  const source = readText(TIMELINE_TSX);
  const cases = extractSwitchCases(
    source,
    /const stableKeyFor\s*=\s*\(node: TraceNodeDto\)\s*:\s*string\s*=>/,
  );
  deepStrictEqual(
    cases,
    kinds,
    `stableKeyFor switch drift — TraceNodeKind values = ${JSON.stringify(
      kinds,
    )}, stableKeyFor cases = ${JSON.stringify(cases)}`,
  );
});

test('TraceNodeKind values match backend trace_node_kind.py exactly', () => {
  const kinds = extractTraceNodeKindValues();
  const backendSource = readText(
    join(
      ROOT,
      'apps',
      'backend',
      'app',
      'observability',
      'trace_node_kind.py',
    ),
  );
  const classBody = backendSource.match(
    /class TraceNodeKind\(StrEnum\):([\s\S]*?)(?=\nclass\s+\w+\(|\n__all__|$)/,
  );
  if (!classBody) throw new Error('cannot locate backend TraceNodeKind');
  const backendValues: string[] = [];
  for (const line of classBody[1].split('\n')) {
    const v = line.match(/^\s+[A-Z_][A-Z0-9_]*\s*=\s*"([^"]+)"/);
    if (v) backendValues.push(v[1]);
  }
  backendValues.sort();
  deepStrictEqual(
    kinds,
    backendValues,
    `TraceNodeKind FE/BE drift: backend = ${JSON.stringify(
      backendValues,
    )}, frontend = ${JSON.stringify(kinds)}`,
  );
});
