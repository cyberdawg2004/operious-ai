import { test } from 'node:test';
import { strictEqual } from 'node:assert';
import { join } from 'node:path';
import { ROOT, isInside, readText, tsFilesUnder } from './util.js';

/**
 * Marketing site is the executive narrative surface.
 *
 * It MUST NEVER import:
 *   - @operious/sdk
 *   - @operious/auth
 *   - @operious/observability
 *   - @operious/topology
 *   - @operious/contracts
 *   - @operious/tracing
 *   - @tanstack/react-query
 *
 * These are operational visibility surfaces. Marketing renders presentational
 * narrative — never live operational data.
 */
const FORBIDDEN_FOR_MARKETING = [
  '@operious/sdk',
  '@operious/auth',
  '@operious/observability',
  '@operious/topology',
  '@operious/contracts',
  '@operious/tracing',
  '@tanstack/react-query',
  '@xyflow/react',
];

test('marketing site does not depend on operational substrate packages', () => {
  const marketingRoot = join(ROOT, 'apps', 'marketing');
  const offences: string[] = [];
  for (const file of tsFilesUnder(join(marketingRoot, 'src'))) {
    const text = readText(file);
    for (const forbidden of FORBIDDEN_FOR_MARKETING) {
      if (text.includes(`'${forbidden}'`) || text.includes(`"${forbidden}"`)) {
        offences.push(`${file} imports ${forbidden}`);
      }
    }
  }
  strictEqual(offences.length, 0, `marketing isolation violated:\n${offences.join('\n')}`);
});

test('marketing site lives only inside apps/marketing', () => {
  const marketingRoot = join(ROOT, 'apps', 'marketing');
  // The Marketing site exists and is non-empty — sanity check the boundary.
  const files = tsFilesUnder(join(marketingRoot, 'src'));
  strictEqual(
    files.length > 0,
    true,
    'expected at least one TS file inside apps/marketing/src',
  );
  for (const file of files) {
    strictEqual(
      isInside(file, marketingRoot),
      true,
      `file ${file} is outside apps/marketing`,
    );
  }
});
