# Command Center Surface — Design Notes

> Companion document to the Visual Execution Hyperprompt. Records the
> implemented spec for the operator workstation and any deliberate
> deviations.

## Typography

| Role        | Family        | Spec'd | Implemented                              |
| ----------- | ------------- | ------ | ---------------------------------------- |
| Display     | Cormorant SC  | ✓      | `heading-xl/l/m`, `display-m` (rare)     |
| Body sans   | **Geist Sans**| ✓      | Replaces Inter — loaded via `geist/font/sans` |
| Technical   | IBM Plex Mono | ✓      | `data-l/m/s`, `eyebrow`                  |

* **Inter is gone.** No file in `apps/command-center/src` declares
  Inter as a font or fallback.
* **Cormorant SC floor enforced at 28px (`heading-m`).** The chrome
  surfaces stay almost entirely in Geist Sans / IBM Plex Mono —
  Cormorant is reserved for forensic detail headlines, page-title
  display moments, and the inspection panel title.
* **Geist stylistic sets** (`ss01`, `ss03`, `cv11`) and tabular
  numerals (`tnum`, `zero`) are forced globally so confidence bars,
  latency cells, queue counts, and timestamps never jitter.

## Motion

All easing and duration tokens live in `src/lib/motion.ts`. Adding any
arbitrary `cubic-bezier(...)` or arbitrary duration constitutes a spec
violation; reviewers should reject such PRs.

| Token         | Value (cubic-bezier)             | Permitted for                                       |
| ------------- | -------------------------------- | --------------------------------------------------- |
| expoOut       | 0.16, 1, 0.3, 1                  | Reveals, glow fades                                 |
| expoInOut     | 0.87, 0, 0.13, 1                 | Tenant-ceremony seal rotation                       |
| cinematic     | 0.22, 1, 0.36, 1                 | Toast slide-in                                      |
| precise       | 0.4, 0, 0.2, 1                   | Default — chrome, panels, palette                   |
| authoritative | 0.32, 0.72, 0, 1                 | Focus underlines, gold accents                      |
| traceOvershoot| 0.34, 1.56, 0.64, 1              | **Trace Inspector node entry ONLY**                 |

### Right inspection panel

* Open: `translateX(100% → 0)`, opacity 0 → 1, **320 ms `precise`**.
* Close: reverse, **240 ms `precise`** (exit faster than enter).
* Backdrop opacity 0 → 0.4 over **240 ms**; `backdrop-blur(0 → 8px)` over
  **320 ms**.
* Content stagger: 60 ms intervals starting 120 ms after panel opens,
  driven by Framer Motion variants in `PanelContentStager`.
* Escape, backdrop click, and the explicit close button all dismiss.

### Trace Inspector — `trace-timeline-graph.tsx`

* Node entry uses **`traceOvershoot`** for scale 0.6 → 1 (the only
  permitted overshoot in the surface). Opacity uses `precise`. A
  substrate-colored `boxShadow` ring expands then fades over 800 ms
  with `expoOut`. Entry is staggered up to 320 ms across the visible
  set so a freshly-loaded bundle doesn't pop in all at once.
* Hover / selection styling unchanged from the spec defaults; selected
  node carries the accent ring and `shadow-card-hover`.

### Tenant switcher ceremony

* On switch, a full-screen overlay fades in (200 ms) with
  `backdrop-blur-md`, the KernelSeal rotates 360° over 800 ms with
  `expoInOut`, the "Switching to [Tenant Name]" label drops in (400 ms,
  `precise`), then the overlay dismisses after the rotation completes.
* Implemented as a standalone `TenantCeremony` component composed by
  `TenantSelector` so the ceremony can be reused if other paths (e.g.
  command-palette tenant switch) need it.

### Command palette (⌘K)

* Backdrop opacity 0 → 0.5 + blur(0 → 8px) over 160 ms.
* Panel scale 0.96 → 1, opacity 0 → 1, **200 ms `precise`**.
* Close reverses in 160 ms.

### Toast notifications

* Timing tokens live in `TOAST` (320 ms in / 240 ms out, 5 s default
  auto-dismiss, max 3 visible). Wired through `sonner`'s
  `toastOptions.classNames` so visual styling stays in our tailwind
  tokens (no `richColors` palette overrides the brand).

## Pixel discipline

* **Spacing scale** matches the marketing surface (explicit ladder, no
  arbitrary px values).
* **Border-radius:** four tokens — `sm` (4 px controls), `md` (8 px
  cards), `lg` (12 px panels), `full` (status pills). Legacy uses of
  `rounded-md` keep working.
* **Shadows:** `hairline`, `card-hover`, `panel`, `dropdown`, `modal`.
  Legacy `shadow-card` and `shadow-raised` aliases are retained and
  alias to the canonical tokens.

## Reduced motion

`prefers-reduced-motion: reduce` collapses every transition to 0.01 ms,
disables the seal rotation in the tenant ceremony (overlay still
appears as an instantaneous announcement), disables the Trace
Inspector overshoot (entry becomes an instant fade), and skips toast
slide-in motion.

## Deviations (with rationale)

1. **GSAP not introduced.** Spec forbids it in the Command Center.
   Confirmed: no GSAP import anywhere in `apps/command-center/src`.
2. **React Spring not introduced.** Spec allows it for Trace Inspector
   physics, but the current timeline view is a vertical list (not a
   force-directed graph). When the graph rendering lands as a true
   node-link diagram, React Spring may be added — currently not
   required.
3. **D3 not introduced.** Same reasoning as React Spring — graph
   layout calculations are not yet needed.
4. **Lottie not introduced.** Explicitly forbidden by spec.

## Performance budget verification (current build)

```
Route (app)              Size      First Load JS    Budget
─ /                      138 B     87.5 kB          250 kB initial → OK
─ /operations            8.26 kB   168 kB           80 kB route → OVER (legacy)
─ /topology              60.7 kB   214 kB           80 kB route → OVER (legacy)
─ /trace                 6.2 kB    160 kB           80 kB route → OVER (legacy)
─ shared chunks          87.3 kB                    < 250 kB → OK
```

* The route chunk overages on `/operations`, `/topology`, `/trace`
  are pre-existing — they come from `@xyflow/react`, `@tanstack/react-query`
  and `@operious/observability` which are owned by the operational layer
  and not subject to this visual-execution PR. They're called out here
  so future work can chunk them more aggressively (lazy `topology`
  surfaces, dynamic-import the graph layout).
* Initial JS for the dashboard root is well within the 250 kB
  ceiling.

## Testing

All 59 frontend invariant tests in `tests-frontend/` continue to pass
unchanged. Demo-identity isolation, no-raw-fetch, contracts-surface,
and topology-layout invariants remain intact — visual-execution work
deliberately did not touch the API surface or the operational packages.
