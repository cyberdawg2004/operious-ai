import { test } from 'node:test';
import { strictEqual } from 'node:assert';

/**
 * Deterministic rendering invariants.
 *
 * The frontend MUST render lists of forensic artifacts in a deterministic
 * order. We enforce this by exercising @operious/shared helpers directly.
 */

import { canonicalJson, chronological, stableSortBy, freezeDeep } from '../../packages/shared/src/index.js';

test('stableSortBy is byte-stable across calls', () => {
  const items = [
    { id: 'b', t: 'x' },
    { id: 'a', t: 'x' },
    { id: 'c', t: 'x' },
    { id: 'a', t: 'y' },
  ];
  const a = stableSortBy(items, (i) => i.id);
  const b = stableSortBy(items, (i) => i.id);
  strictEqual(JSON.stringify(a), JSON.stringify(b));
  strictEqual(JSON.stringify(a.map((i) => i.id + i.t)), JSON.stringify(['ax', 'ay', 'bx', 'cx']));
});

test('chronological preserves equal-timestamp order deterministically', () => {
  const events = [
    { at: '2026-05-15T10:00:00Z', id: 'first' },
    { at: '2026-05-15T10:00:00Z', id: 'second' },
    { at: '2026-05-15T09:59:59Z', id: 'before' },
  ];
  const ordered = chronological(events, (e) => e.at);
  strictEqual(ordered.map((e) => e.id).join(','), 'before,first,second');
});

test('canonicalJson produces identical output for equivalent objects', () => {
  const a = { b: 2, a: { y: 1, x: 0 }, c: [{ k: 1, j: 0 }] };
  const b = { a: { x: 0, y: 1 }, c: [{ j: 0, k: 1 }], b: 2 };
  strictEqual(canonicalJson(a), canonicalJson(b));
});

test('freezeDeep makes DTOs immutable', () => {
  const dto: { foo: { bar: number[] } } = { foo: { bar: [1, 2, 3] } };
  freezeDeep(dto);
  strictEqual(Object.isFrozen(dto), true);
  strictEqual(Object.isFrozen(dto.foo), true);
  strictEqual(Object.isFrozen(dto.foo.bar), true);
});
