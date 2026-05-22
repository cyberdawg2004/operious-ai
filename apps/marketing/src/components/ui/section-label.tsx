import type { ReactNode } from 'react';

interface SectionLabelProps {
  readonly index: string;
  readonly children: ReactNode;
  readonly tone?: 'light' | 'dark';
  readonly className?: string;
}

/**
 * Section label — `§01 · THE PROBLEM` form. Used at the top of every
 * narrative section to anchor the reader in the editorial structure.
 */
export const SectionLabel = ({
  index,
  children,
  tone = 'light',
  className,
}: SectionLabelProps) => {
  const color = tone === 'dark' ? 'text-gold-highlight' : 'text-gold';
  return (
    <p
      className={`eyebrow ${color} ${className ?? ''}`}
      aria-label={`Section ${index}`}
    >
      <span className="opacity-60">§{index}</span>
      <span className="mx-2 opacity-40">·</span>
      <span>{children}</span>
    </p>
  );
};

export default SectionLabel;
