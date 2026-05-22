'use client';

/**
 * HexLattice — full-bleed hexagonal wireframe for the dark hero.
 *
 * Implementation: a single seamless SVG pattern, scaled to fill, slowly
 * rotating via CSS transform (0.3rpm = 200s per revolution). Pure CSS
 * animation — no Three.js, no canvas, no per-frame JS.
 */
export const HexLattice = ({ className }: { readonly className?: string }) => (
  <div className={`pointer-events-none absolute inset-0 overflow-hidden ${className ?? ''}`} aria-hidden>
    <div
      className="absolute left-1/2 top-1/2 h-[180vmax] w-[180vmax] -translate-x-1/2 -translate-y-1/2 hex-lattice-bg animate-lattice-spin"
      style={{ opacity: 0.08 }}
    />
    <div
      className="absolute inset-0"
      style={{
        background:
          'radial-gradient(ellipse at center, transparent 0%, rgba(5,8,15,0.6) 60%, #05080F 95%)',
      }}
    />
  </div>
);

export default HexLattice;
