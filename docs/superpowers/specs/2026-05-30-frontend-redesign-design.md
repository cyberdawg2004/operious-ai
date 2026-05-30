# Operious AI — World-Class Frontend Redesign
**Date:** 2026-05-30  
**Scope:** `apps/marketing2/frontend` + `apps/command-center2/frontend`  
**Branch:** `phase-2-2-stabilized`

---

## 1. Objectives

Redesign both frontends to premium $10k-tier quality:
- Marketing site: immersive, interactive, 3D, scroll-driven, enterprise-authoritative tone
- Command center: clean, functional, simple dark dashboard
- Preserve all existing functionality, API contracts, routing, and content
- Add new content sections per this spec

---

## 2. Approved Design Direction

### Visual Language
- **Hero/dark sections**: `#050508` background (not pure black)
- **Light/content sections**: `#F8F5EE` (existing `--canvas` brand token) — cream/sugary warmth
- **Gold accent**: `#C9A84C` / `#A8882C` — primary brand, CTAs, labels
- **Cyan accent**: `#00C7FF` — data, stats, technical elements
- **Status colors**: `#30D158` (allow/success), `#FF453A` (deny/error), `#FFD60A` (crisis/warning)
- **Light section text**: `#0A0F1C` primary, `#2A3548` body, `#4A5468` secondary (existing brand tokens)
- **Dark section text**: `#D8E4F4` primary, `#7A90B4` secondary (existing brand tokens)

### Typography
- **Display/headlines**: `Playfair Display` — 700/800/900, italic gold for accent words
- **Body/UI**: `Inter` — 300/400/500/600/700
- **Monospace/labels**: `SF Mono` / `JetBrains Mono` / system monospace

### Logo
- Preserve exact existing `OperiousMark` SVG (gold outer hexagon, blue inner hexagon, center dot)
- Do not modify the logo in any way

### Page rhythm (dark → light → dark)
```
Hero (dark #050508)
TextRevealByWord bridge (dark)
ContainerScroll — Command Center (cream #F8F5EE)
SkewCards — Capabilities (cream)
ZoomParallax — Platform visual (dark)
FlowArt/StoryScroll — Architecture narrative (GSAP, dark panels)
Industries grid (cream)
CTA (dark)
```

---

## 3. New Component Library

All components go in `apps/marketing2/frontend/components/ui/`:

| File | Source | Usage |
|------|--------|-------|
| `container-scroll-animation.tsx` | Aceternity | Command Center 3D reveal |
| `scroll-expansion-hero.tsx` | 21st.dev | Removed (replaced by ContainerScroll) |
| `gradient-card-showcase.tsx` | 21st.dev | Capabilities section (SkewCards) |
| `link-preview.tsx` | 21st.dev | Insights articles hover preview |
| `text-reveal.tsx` | Magic UI | Bridge statement after hero |
| `zoom-parallax.tsx` | 21st.dev | Platform visual showcase |
| `story-scroll.tsx` | 21st.dev/GSAP | Architecture narrative (FlowArt) |

### NPM Dependencies to add (marketing2)
```bash
framer-motion          # already installed — verify
gsap                   # FlowArt story scroll
@gsap/react            # FlowArt story scroll
qss                    # link-preview
@radix-ui/react-hover-card  # link-preview
@studio-freight/lenis  # smooth scroll (ZoomParallax demo)
```

---

## 4. Marketing Site — Page Sections

### 4.1 Navigation (keep existing, style upgrade)
- Existing `navigation.tsx` — upgrade with:
  - Nav link underline wipe hover effect
  - Scroll-triggered background blur (rgba(5,5,8,0.92) + backdrop-filter after 60px)
  - Gold dot blinking on eyebrow
  - Keep all existing links and routes

### 4.2 Hero Section (full redesign)
**File**: `app/page.tsx` hero section + `components/animated-headline.tsx`

Layout: full-width centered, NOT split (no right box)

Elements:
- Canvas particle field (gold + blue nodes, react to cursor proximity)
- Grid overlay (80px × 80px, 1.6% opacity)
- Gold horizontal rule at very top
- Eyebrow: two short gold lines + "Governed Execution Infrastructure" monospace text
- Headline (Playfair Display 800, clamp 52px→108px):
  - "The runtime that governs AI at scale."
  - "governs" and "AI" in italic gold gradient
  - Words animate in staggered (translateY 90% → 0, opacity 0→1)
- Subheadline (Inter 400, 18px, `#7A90B4`): existing brand copy, max-width 640px centered
- CTAs: gold filled "Request enterprise access →" + ghost "Explore the architecture"
  - Both with magnetic mouse-follow effect (7% displacement)
- 7-substrate strip (Boundary → Arbitration) at bottom
- Scroll indicator (animated gold line)

**3D**: Use existing `SplineHeroBg` component — keep it, potentially upgrade or replace with React Three Fiber lazy-loaded scene for production (plan for it, implement if feasible within timeline)

### 4.3 TextRevealByWord Bridge
**Component**: `components/ui/text-reveal.tsx`  
**Text**: "Every enterprise AI deployment needs a governance layer between what the model proposes and what the system executes. Operious is that layer."  
**Gold words**: governance, layer, proposes, executes, Operious  
**Background**: dark `#050508`  
**Implementation**: `TextRevealByWord` component from Magic UI, adapted for Playfair Display font

### 4.4 ContainerScroll — Command Center Reveal
**Component**: `components/ui/container-scroll-animation.tsx`  
**Background**: cream `#F8F5EE`  
**Section header**:
- Label: "Command Center"
- Title (Playfair 800): "The operational intelligence layer your team actually uses."
- Subtitle (Inter 400): existing copy

**Card content**: A live-looking screenshot/mockup of the Command Center dashboard showing:
- Operations queue with Arabic ticket rows (ar → en)
- ALLOW / APPROVAL / DENY badges
- KPI stat row (3 active, 47 resolved, 2 pending, 0 DLQ)
- Sidebar with nav items including crisis indicator

This can be:
1. A real screenshot of the command center (preferred)
2. A static image from Unsplash (fallback)
3. The live command center embedded in an iframe (aspirational)

### 4.5 SkewCards — Capabilities
**Component**: `components/ui/gradient-card-showcase.tsx`  
**Background**: cream `#F8F5EE`  
**Cards** (6, adapted brand colors):
1. Constitutional Governance — gold gradient (`#A8882C → #C9A84C`)
2. Forensic Reconstructibility — blue gradient (`#1A4A9A → #00C7FF`)
3. Multilingual Operations — green gradient (`#0D6B3A → #30D158`)
4. Crisis Override Control — red gradient (`#7A1A1A → #FF453A`)
5. Semantic Fraud Intelligence — purple gradient (`#4A1A7A → #8B5CF6`)
6. SOP Citation Intelligence — lime gradient (`#3A4A1A → #84CC16`)

Each card: Playfair Display italic title, Inter 400 description, white "Explore →" button

### 4.6 ZoomParallax — Platform Showcase
**Component**: `components/ui/zoom-parallax.tsx`  
**Background**: dark `#050508`  
**Images** (7, enterprise/tech Unsplash):
- Data center servers
- Office operations
- Document analysis
- Network infrastructure
- Arabic language interface
- Financial/trading screens
- Abstract tech

Section label + "Built for the regulated enterprise." headline overlay

### 4.7 FlowArt — Architecture Narrative
**Component**: `components/ui/story-scroll.tsx` (FlowArt + FlowSection)  
**4 panels** with GSAP pin + rotation-in effect:

| Panel | Background | Color | Headline | Body |
|-------|------------|-------|----------|------|
| 01 — Boundary | `#050508` | `#D8E4F4` | Admit Only The Governed. | No request enters without passing the admission gate... |
| 02 — Governance | `#0A0F1C` | `#D8E4F4` | Policy Executes. Not Suggests. | Policy chains evaluate every proposed action... |
| 03 — Execution | `#F8F5EE` | `#0A0F1C` | Every Decision. Permitted Action. | Warranty claims, refund requests, replacements — each governed and SOP-cited... |
| 04 — Audit | `#0A0F1C` | `#D8E4F4` | Every Decision. Permanent Record. | UUID5 identity. HMAC-SHA256 signatures. Append-only timelines... |

### 4.8 Containment Vessel (keep existing, upgrade styling)
Keep existing `ContainmentLayer` component structure.  
Upgrade visuals:
- Dark background
- Gold-illuminated layer number + left bar on hover
- Layer title color transition to `#D8E4F4` on hover
- Smooth 300ms transitions

### 4.9 LiveEvidence (keep existing, upgrade styling)
Keep all existing `LiveEvidence` component logic.  
Upgrade visuals:
- Dark terminal panel
- Green live dot blinking
- Monospaced rows with gold KEY labels
- Rows animate in sequentially (existing Framer Motion, keep)

### 4.10 Industries (keep existing content, upgrade styling)
Keep all 6 existing industries with their icons and links.  
Upgrade: cream background, gold icon boxes, hover lift

### 4.11 Insights (upgrade with HoverPeek)
Keep all 3 existing article cards.  
Add `HoverPeek` on article titles for link preview hover cards.  
**Package**: `link-preview.tsx` — `isStatic: false` (uses Microlink screenshots)

### 4.12 Trust Section (keep, upgrade styling)
Keep existing 3 trust cards (SOC2, HIPAA, Tenant Isolation).  
Cream background, gold accent for meta text.

### 4.13 CTA (keep content, upgrade styling)
Keep existing CTA copy and link.  
Dark background with radial gold glow.  
Playfair Display headline.  
Magnetic gold CTA button.

---

## 5. Command Center — Redesign

### Approach
Do NOT rewrite functional components. Upgrade:
1. Global design tokens in `app/globals.css`
2. Shell (`dashboard-shell.tsx`) — header styling
3. Sidebar (`sidebar.tsx`) — dark, minimal, gold active state
4. Page transitions (Framer Motion `AnimatePresence`)
5. Individual page visual treatments (keep all data fetching)

### Design Tokens (dark theme)
```css
--cc-bg-deep: #0A0A0C;
--cc-bg-surface: #111114;
--cc-bg-raised: #1A1A1E;
--cc-border-subtle: #2A2A2E;
--cc-gold-primary: #C9A84C;
--cc-gold-hover: #E8C76A;
--cc-text-primary: #F2F2EA;
--cc-text-secondary: #9A9A8A;
--cc-text-muted: #5A5A52;
--cc-destructive: #C44B4B;
--cc-success: #4B8C5A;
```

### Sidebar Upgrade
- Dark `#0A0A0C` background
- Nav items: subtle left border indicator on active (2px gold)
- Hover: `rgba(201,168,76,0.05)` background
- Active: `rgba(201,168,76,0.08)` background + gold text
- Section groupings with `#1A1A1E` separator labels
- Approval count badge: amber pill
- Crisis active: red dot pulse indicator
- Fraud active: orange dot pulse indicator

### Header Upgrade
- Sticky, `rgba(10,10,12,0.92)` + backdrop-blur-md
- Breadcrumb: "Command Center / {Section}" in monospace
- Page title: Inter 600, `#F2F2EA`
- Collapse/expand sidebar button
- Command palette trigger (existing, keep)
- User button (existing, keep)

### Page Transitions
Wrap `{children}` in `dashboard-shell.tsx` with:
```tsx
<AnimatePresence mode="wait">
  <motion.div
    key={pathname}
    initial={{ opacity: 0, y: 8 }}
    animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: -8 }}
    transition={{ duration: 0.2, ease: "easeOut" }}
  >
    {children}
  </motion.div>
</AnimatePresence>
```

### Operations Queue Upgrade
Keep all data fetching in `operations-queue.tsx`.  
Upgrade ticket card visuals:
- Glass card background
- Confidence score as colored badge
- Category as pill
- Language as flag or ISO badge
- Time elapsed with color coding
- Hover lift animation

### Fraud Monitor Upgrade
Keep circuit state logic.  
Upgrade: CLOSED = green pulse, TRIPPED = red pulse + border glow

### Crisis Panel Upgrade  
Keep template buttons and deployment logic.  
Upgrade: BLOCK_SKU = amber, HALT_REFUNDS = red, ESCALATE_ALL = amber, FREEZE_CATEGORY = blue  
TTL countdown: animated monospace number

### Trace Inspector Upgrade
Keep timeline data.  
Upgrade nodes: colored circle + connecting line, ALLOW = green glow, DENY = red glow

---

## 6. Shared Design System

### globals.css additions (both apps)
Both apps already share color tokens in `apps/marketing2/frontend/app/globals.css`.  
Add:
- Font imports (Playfair Display + Inter from Google Fonts)
- CSS custom property for `--font-serif`
- Animation utilities: `@keyframes` for reveal, blink, scroll indicator

### Component placement
```
apps/marketing2/frontend/
  components/
    ui/                     ← new 21st.dev components
      container-scroll-animation.tsx
      gradient-card-showcase.tsx
      link-preview.tsx
      text-reveal.tsx
      zoom-parallax.tsx
      story-scroll.tsx
    animated-headline.tsx   ← upgrade existing
    containment-layer.tsx   ← upgrade existing
    feature-card.tsx        ← upgrade existing
    ...existing components
```

---

## 7. Accessibility & Performance

- `prefers-reduced-motion` media query on all animations
- 3D/canvas scenes lazy-loaded with `React.Suspense` + `dynamic(() => import(...))`
- Images: WebP via Next.js `Image`, `loading="lazy"` on below-fold
- No layout shift: pre-defined dimensions on all media
- All interactive elements: `cursor-pointer`, visible focus rings
- ARIA labels on icon-only buttons
- Contrast: 4.5:1 minimum on all text

---

## 8. Build Requirements

Both apps must pass `npm run build` with 0 TypeScript errors after changes.

```bash
cd apps/marketing2/frontend && npm run build
cd apps/command-center2/frontend && npm run build
```

---

## 9. Commit

```
git commit -m "feat: world-class frontend redesign — Playfair Display + Inter, cream/dark palette, Framer Motion, GSAP FlowArt, ContainerScroll, SkewCards, TextReveal, ZoomParallax, HoverPeek"
git push origin phase-2-2-stabilized
```

---

## 10. Component/Feature Mapping

| Component | Where Used | Priority |
|-----------|-----------|----------|
| Hero particles + cursor | `app/page.tsx` | High |
| TextRevealByWord | `app/page.tsx` bridge | High |
| ContainerScroll | `app/page.tsx` CC reveal | High |
| SkewCards | `app/page.tsx` capabilities | High |
| ZoomParallax | `app/page.tsx` showcase | Medium |
| FlowArt/FlowSection | `app/page.tsx` architecture | High |
| HoverPeek | `app/page.tsx` insights | Medium |
| Page transitions | `app/dashboard/layout.tsx` | High |
| Sidebar upgrade | `components/sidebar.tsx` | High |
| Operations queue cards | `components/operations-queue.tsx` | Medium |
| Fraud monitor | `components/fraud-monitoring-view.tsx` | Medium |
| Crisis panel | `components/crisis-control-panel.tsx` | Medium |
| Trace inspector | `components/trace-inspector.tsx` | Medium |
