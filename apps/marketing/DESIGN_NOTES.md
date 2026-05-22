# Marketing Surface — Design Notes

> Companion document to the Visual Execution Hyperprompt. Records the
> implemented spec for this surface and any deliberate deviations.

## Typography

| Role        | Family        | Spec'd | Implemented                              |
| ----------- | ------------- | ------ | ---------------------------------------- |
| Display     | Cormorant SC  | ✓      | `display-xl/l/m`, `heading-xl/l/m`       |
| Body sans   | **Geist Sans**| ✓      | Replaces Inter — loaded via `geist/font/sans` |
| Technical   | IBM Plex Mono | ✓      | `data-l/m/s`, `eyebrow`, `eyebrow-s`     |

* **Inter is gone.** No file in `apps/marketing/src` imports Inter or
  declares it as a font fallback.
* **Cormorant SC floor enforced at 28px (`heading-m`).** Below 28px, all
  text resolves to Geist Sans (body-s / body-xs / caption) or IBM Plex
  Mono (eyebrow / data-s).
* **Global font-feature settings:** `ss01`, `ss03`, `cv11` enabled on
  the root body so Geist's refined `a`/`g`/numeric proportions are
  always active. `tabular-nums` + `tnum`/`zero` enforced on every mono
  surface (count-ups never jitter).
* **One italic word per page** is the editorial signature. Implemented
  via the `.italic-emph` utility — only the headline's "deviate." word
  receives italic treatment.

## Motion

All easing and duration tokens live in `src/lib/motion.ts`. Sections
import only from this module — no arbitrary `cubic-bezier(...)`,
no arbitrary `duration: 0.35`.

| Token         | Value (cubic-bezier)             |
| ------------- | -------------------------------- |
| expoOut       | 0.16, 1, 0.3, 1                  |
| expoInOut     | 0.87, 0, 0.13, 1                 |
| cinematic     | 0.22, 1, 0.36, 1                 |
| precise       | 0.4, 0, 0.2, 1                   |
| authoritative | 0.32, 0.72, 0, 1                 |

### Hero load sequence

Frame-by-frame timeline is encoded in `HERO_TIMELINE` and executed by
`hero-section.tsx` using framer-motion. Each timeline event has a
single `setTimeout` flip; the component never re-renders on a
per-frame basis. Italic word ("deviate.") receives an additional
scale (0.96 → 1) + tracking decompression (-0.03em → -0.01em) per
spec.

### Section 3 — The Kernel (signature)

Spec mandates a scroll-bound substrate stack with bidirectional
scrubbing. Implemented with **Framer Motion's `useScroll` +
`useTransform`** rather than GSAP — see deviation note below.

The connecting line draws via SVG `pathLength` tied to scroll
progress (gold at the top → blue at the bottom). Each substrate row
fades in / slides in at its declared progress threshold. The
authority precedence stamps fill in across 0.7 → 0.85. The bottom
statistics fade in across 0.85 → 0.95. The section is `min-height:
200vh` per the spec breathing requirement.

### Section 7 — Substrate chat

The header KernelSeal performs its three-phase reveal at 22 px so it
reads as a "small mark." Suggested prompt chips fade in one-by-one.

### Other sections

* **§02 Problem** — three columns staggered 0 / 150 / 300 ms.
* **§03 Domains** — 3 × 2 diagonal stagger (0 / 80 / 160 / 120 / 200 / 280 ms).
* **§04 Products** — mockup parallaxes at 0.6× scroll, text at 1.0× per spec.
* **§05 Trust** — `CountUp` (tabular-nums, expoOut curve, 1200 ms).
* **§09 Newsletter** — submit morphs to a checkmark badge.
* **§10 FAQ** — height-auto accordion via Framer Motion (320 ms `precise`).

## Pixel discipline

* **Spacing scale:** explicit 0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12,
  16, 20, 24, 32, 40, 48, 64 (in `tailwind.config.ts`). No arbitrary
  `p-[17px]`.
* **Border-radius:** `sm` (4 px controls), `md` (8 px cards), `lg` (12 px panels),
  `full` (9999 px status pills). No `rounded-xl/2xl/3xl`.
* **Shadows:** `hairline`, `card-hover`, `panel`, `dropdown`, `modal`
  (the five sanctioned tokens). The legacy `shadow-card` /
  `shadow-dark-glow` names are kept as aliases temporarily and resolve
  to the canonical tokens.

## Atmospherics

* **Hex lattice (hero):** Implemented as a CSS-driven SVG pattern
  rotating once every 240 s. **Deviation:** the spec recommends
  React Three Fiber; the CSS approach hits the same visual brief at a
  fraction of the bundle weight (homepage First Load JS = 150 KB,
  spec ceiling = 150 KB). If we later need true 3D depth, the lattice
  component is the single insertion point.
* **Grain (light sections):** SVG noise PNG via the `.grain-light`
  utility, opacity 0.025, `mix-blend-mode: multiply`.
* **Ambient (dark sections):** radial gradients at corners (gold
  top-left, blue bottom-right), each at 0.04 alpha.
* **Custom cursor:** Implemented in `components/atmospherics/custom-cursor.tsx`.
  Dot (6 px) follows at lerp 0.18; ring (32 px) follows at lerp 0.12 on
  interactive elements; text-bar (2 × 18 px) over selectable text.
  Hidden on touch (`pointer: coarse`) and reduced-motion devices.

## Accessibility / reduced motion

* `prefers-reduced-motion: reduce` collapses every transition to 0.01 ms,
  forces reveal states to visible, and disables the custom cursor.
* All interactive surfaces carry `data-cursor` hints to inform the
  custom cursor of mode without requiring DOM walks.
* `focus-visible` outline is gold-highlight at 2 px / 4 px offset.

## Deviations (with rationale)

1. **R3F not used for hero lattice.** Spec recommends it; we use a
   CSS-driven SVG pattern. Rationale: meets the visual brief at zero
   incremental JS weight (hero remains within budget). If the
   investment is warranted later, the swap is local to
   `hex-lattice.tsx`.
2. **GSAP ScrollTrigger not introduced.** Spec allows it for
   scroll-bound timelines that Framer Motion "cannot orchestrate
   cleanly." Framer Motion's `useScroll + useTransform` covers the
   Kernel scroll choreography; we have not yet hit a case that
   requires GSAP. Adding it now would burn bundle weight for no
   visual return.
3. **Lenis smooth scroll not enabled.** Reserved for a follow-up. The
   default native scroll behavior is preserved so users keyboard /
   trackpad scrolling stays predictable. Easy to bolt on later.

## Performance budget verification (current build)

```
Route (app)              Size      First Load JS
─ / (homepage)           53.6 kB   150 kB    ← at hero ceiling
+ shared chunks          87.2 kB
```

* LCP / CLS measurements: not yet instrumented in CI. Manual
  inspection on a desktop preview shows < 1.5 s LCP and CLS ≈ 0 since
  fonts are self-hosted via `next/font` with adjusted fallback.

## Testing

All 59 frontend invariant tests in `tests-frontend/` continue to pass
unchanged. Marketing isolation invariant verified — no operational SDK
imports were introduced.
