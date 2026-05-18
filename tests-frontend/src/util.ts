import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

export const ROOT = join(import.meta.dirname, '..', '..');

const SKIP_DIRS = new Set([
  'node_modules',
  '.next',
  '.turbo',
  'dist',
  'venv',
  '.git',
  '.pytest_cache',
  '.ruff_cache',
]);

export const walkFiles = (root: string, pred: (path: string) => boolean): string[] => {
  const out: string[] = [];
  const visit = (dir: string) => {
    let entries: string[];
    try {
      entries = readdirSync(dir);
    } catch {
      return;
    }
    for (const entry of entries) {
      if (SKIP_DIRS.has(entry)) continue;
      const path = join(dir, entry);
      let stat;
      try {
        stat = statSync(path);
      } catch {
        continue;
      }
      if (stat.isDirectory()) {
        visit(path);
      } else if (pred(path)) {
        out.push(path);
      }
    }
  };
  visit(root);
  return out;
};

export const tsFilesUnder = (root: string): string[] =>
  walkFiles(root, (path) => /\.(tsx?|mts|cts)$/.test(path));

export const readText = (path: string): string => readFileSync(path, 'utf8');

export const isInside = (path: string, prefix: string): boolean =>
  path.startsWith(prefix.endsWith('/') ? prefix : `${prefix}/`);
