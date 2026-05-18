import { canonicalJson } from '@operious/shared';
import { Code } from './code';

interface JsonInspectorProps {
  readonly value: unknown;
  readonly className?: string;
}

/**
 * Renders any JSON value in canonicalized form: object keys are recursively
 * sorted so that two semantically-equal payloads render identically. This is
 * the deterministic-rendering invariant required by the Trace Inspector.
 */
export const JsonInspector = ({ value, className }: JsonInspectorProps) => {
  const json = (() => {
    try {
      const canonical = canonicalJson(value);
      return JSON.stringify(JSON.parse(canonical), null, 2);
    } catch {
      return '<unrenderable>';
    }
  })();

  return <Code tone="block" className={className}>{json}</Code>;
};
