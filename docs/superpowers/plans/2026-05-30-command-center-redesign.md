# Command Center Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `apps/command-center2/frontend` to a clean, functional, premium dark dashboard — upgrading visual styling, adding Framer Motion page transitions, and improving component aesthetics while preserving all existing data fetching, API calls, auth, and business logic.

**Architecture:** Install framer-motion, upgrade CSS tokens in globals.css, enhance the shell and sidebar, add page transitions, then upgrade individual page components. Zero functional changes — all API clients, auth0, SSE connections, and data contracts stay identical.

**Tech Stack:** Next.js 16, React 19, Tailwind CSS 4, Framer Motion 12 (new), TypeScript 5

---

## File Map

**Modify:**
- `package.json` — add framer-motion
- `app/globals.css` — upgrade CC dark tokens, add Inter font
- `components/dashboard-shell.tsx` — header upgrade + Framer Motion page transitions
- `components/sidebar.tsx` — dark premium design, gold active state, pulse indicators
- `components/operations-queue.tsx` — glass card ticket rows, confidence badges, color time
- `components/fraud-monitoring-view.tsx` — CLOSED/TRIPPED pulse animation states
- `components/crisis-control-panel.tsx` — colored emergency buttons, TTL countdown animation
- `components/trace-inspector.tsx` — node glow states (ALLOW green, DENY red)

---

## Task 1: Install framer-motion

**Files:**
- Modify: `apps/command-center2/frontend/package.json`

- [ ] **Step 1: Install**

```bash
cd apps/command-center2/frontend
npm install framer-motion
```

Expected: `added N packages` with no errors.

- [ ] **Step 2: Verify TypeScript sees it**

```bash
cd apps/command-center2/frontend && npx tsc --noEmit 2>&1 | grep framer | head -5
```

Expected: no "Cannot find module 'framer-motion'" errors.

- [ ] **Step 3: Commit**

```bash
git add apps/command-center2/frontend/package.json apps/command-center2/frontend/package-lock.json
git commit -m "chore(cc): install framer-motion"
```

---

## Task 2: Upgrade Design Tokens

**Files:**
- Modify: `apps/command-center2/frontend/app/globals.css`

- [ ] **Step 1: Add Google Fonts + Inter variable**

At the very top of `globals.css`, before `@import "tailwindcss"`:

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
```

- [ ] **Step 2: Update CC design tokens in :root block**

The existing globals.css has a `--cc-bg-deep` etc. block. Update/verify these values:

```css
/* Command Center dark theme tokens */
--cc-bg-deep: #0A0A0C;
--cc-bg-surface: #111114;
--cc-bg-raised: #1A1A1E;
--cc-border-subtle: rgba(255,255,255,0.055);
--cc-border-default: rgba(255,255,255,0.09);
--cc-gold-primary: #C9A84C;
--cc-gold-hover: #E8C76A;
--cc-gold-dim: #A8882C;
--cc-text-primary: #F2F2EA;
--cc-text-secondary: #9A9A8A;
--cc-text-muted: #5A5A52;
--cc-destructive: #C44B4B;
--cc-success: #4B8C5A;
--cc-cyan: #00C7FF;
--cc-warning: #FFD60A;
--font-inter-cc: 'Inter', system-ui, sans-serif;
```

- [ ] **Step 3: Add page transition keyframes + status pulse animations**

Append to `globals.css`:

```css
/* Page transition */
@keyframes cc-fade-in {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.animate-cc-fade-in {
  animation: cc-fade-in 0.2s ease-out;
}

/* Status pulse animations */
@keyframes pulse-green {
  0%, 100% { box-shadow: 0 0 0 0 rgba(75, 140, 90, 0.4); }
  50%       { box-shadow: 0 0 0 8px rgba(75, 140, 90, 0); }
}
@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 0 rgba(196, 75, 75, 0.5); }
  50%       { box-shadow: 0 0 0 10px rgba(196, 75, 75, 0); }
}
@keyframes pulse-amber {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255, 214, 10, 0.4); }
  50%       { box-shadow: 0 0 0 8px rgba(255, 214, 10, 0); }
}
.animate-pulse-green { animation: pulse-green 2.5s ease-in-out infinite; }
.animate-pulse-red   { animation: pulse-red 1.5s ease-in-out infinite; }
.animate-pulse-amber { animation: pulse-amber 2s ease-in-out infinite; }

/* Focus ring gold for CC */
.focus-gold:focus-visible {
  outline: 2px solid var(--cc-gold-primary);
  outline-offset: 2px;
}
```

- [ ] **Step 4: Build check**

```bash
cd apps/command-center2/frontend && npm run build 2>&1 | grep -E "error|✓"
```

Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add apps/command-center2/frontend/app/globals.css
git commit -m "feat(cc): upgrade dark design tokens, add Inter font, pulse animations"
```

---

## Task 3: Upgrade Sidebar

**Files:**
- Modify: `apps/command-center2/frontend/components/sidebar.tsx`

Read the current sidebar first, then apply upgrades without changing nav item structure, href values, or badges logic.

- [ ] **Step 1: Read current sidebar**

```bash
cat apps/command-center2/frontend/components/sidebar.tsx
```

Note the exact className patterns on: outer wrapper, nav items, active state, section headers, badge elements, crisis/fraud indicators.

- [ ] **Step 2: Update sidebar outer wrapper background**

Find the sidebar container div (the one with `bg-canvas` or similar). Change to:

```tsx
className="... bg-[#0A0A0C] border-r border-[rgba(255,255,255,0.055)]"
```

- [ ] **Step 3: Update nav item active state**

Find the active nav item class (usually has `text-gold` or similar). Replace the active styling with:

```tsx
// Active item:
className="... bg-[rgba(201,168,76,0.07)] text-[#F2F2EA] font-semibold border-l-2 border-[#C9A84C]"
// Inactive item:
className="... text-[#5A5A52] hover:bg-[rgba(255,255,255,0.04)] hover:text-[#9A9A8A] transition-colors duration-200 border-l-2 border-transparent"
```

- [ ] **Step 4: Upgrade section separator labels**

Find nav section labels (like "Operations", "Observability", etc.). Update styling:

```tsx
className="px-4 py-1.5 text-[9px] font-mono uppercase tracking-[0.15em] text-[rgba(255,255,255,0.2)] mt-3"
```

- [ ] **Step 5: Upgrade crisis active indicator**

Find where `crisisActive` prop controls the crisis nav item styling. Replace with:

```tsx
// When crisis is active, nav item gets:
className={cn(
  baseNavItemClass,
  crisisActive
    ? "text-[#C44B4B] bg-[rgba(196,75,75,0.06)] border-l-2 border-[#C44B4B]"
    : "text-[#5A5A52] border-l-2 border-transparent"
)}
// And add an animated dot:
{crisisActive && (
  <span className="ml-auto w-2 h-2 rounded-full bg-[#C44B4B] animate-pulse-red" />
)}
```

- [ ] **Step 6: Upgrade fraud active indicator**

Same pattern for `fraudActive`:

```tsx
{fraudActive && (
  <span className="ml-auto w-2 h-2 rounded-full bg-[#FFD60A] animate-pulse-amber" />
)}
```

- [ ] **Step 7: Upgrade approval count badge**

Find the approval count badge (currently renders a number). Update styling:

```tsx
// Badge element:
<span className="ml-auto bg-[rgba(201,168,76,0.18)] text-[#C9A84C] text-[9px] font-mono px-1.5 py-0.5 rounded-[3px] border border-[rgba(201,168,76,0.25)]">
  {approvalCount}
</span>
```

- [ ] **Step 8: Upgrade tenant/user info section at bottom**

Find the tenant name and user section at the bottom of the sidebar. Update text colors:

```tsx
// Tenant name:
className="... text-[#F2F2EA] font-semibold text-[13px]"
// Tenant id / role labels:
className="... text-[#5A5A52] text-[11px] font-mono"
```

- [ ] **Step 9: Build check**

```bash
cd apps/command-center2/frontend && npm run build 2>&1 | grep -E "error TS|✓"
```

Expected: 0 TypeScript errors.

- [ ] **Step 10: Commit**

```bash
git add apps/command-center2/frontend/components/sidebar.tsx
git commit -m "feat(cc): upgrade sidebar — dark bg, gold active state, crisis/fraud pulse indicators"
```

---

## Task 4: Add Page Transitions to DashboardShell

**Files:**
- Modify: `apps/command-center2/frontend/components/dashboard-shell.tsx`

- [ ] **Step 1: Add framer-motion imports**

At the top of `dashboard-shell.tsx`, add:

```tsx
import { AnimatePresence, motion } from "framer-motion";
```

- [ ] **Step 2: Wrap children with AnimatePresence + motion.div**

Find the `{children}` render in DashboardShell (currently wrapped in `<div className="animate-cc-fade-in">`). Replace it:

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

- [ ] **Step 3: Upgrade header background**

Find the `<header>` element in DashboardShell. Update its className:

```tsx
<header
  className={cn(
    "sticky top-0 z-30 border-b",
    "border-[rgba(255,255,255,0.055)]",
    "bg-[rgba(10,10,12,0.92)] backdrop-blur-md"
  )}
>
```

- [ ] **Step 4: Upgrade header breadcrumb fonts**

Find the "Command Center / {eyebrow}" text in the header. Apply Inter:

```tsx
<div
  className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-[#5A5A52]"
  style={{ fontFamily: "var(--font-inter-cc)" }}
>
  <span>Command Center</span>
  <span className="text-[rgba(255,255,255,0.2)]">/</span>
  <span className="truncate text-[#C9A84C]">{activeMeta.eyebrow}</span>
</div>
<h1
  className="mt-0.5 truncate text-[15px] font-semibold tracking-[-0.005em] text-[#F2F2EA] sm:text-[16px]"
  style={{ fontFamily: "var(--font-inter-cc)" }}
>
  {activeMeta.title}
</h1>
```

- [ ] **Step 5: Upgrade command palette button styling**

Find the `⌘K` button in the header. Update:

```tsx
className="hidden h-8 items-center gap-2 rounded-md border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-2.5 text-[11px] uppercase tracking-[0.10em] text-[#5A5A52] transition-colors hover:border-[rgba(255,255,255,0.14)] hover:text-[#9A9A8A] sm:flex"
```

- [ ] **Step 6: Build check**

```bash
cd apps/command-center2/frontend && npm run build 2>&1 | grep -E "error TS|✓"
```

Expected: 0 TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add apps/command-center2/frontend/components/dashboard-shell.tsx
git commit -m "feat(cc): add Framer Motion page transitions, upgrade header dark styling"
```

---

## Task 5: Upgrade Operations Queue

**Files:**
- Modify: `apps/command-center2/frontend/components/operations-queue.tsx`

Preserve all data fetching, SSE connections, and business logic. Only upgrade the visual rendering of ticket rows.

- [ ] **Step 1: Read the current operations-queue**

```bash
cat apps/command-center2/frontend/components/operations-queue.tsx
```

Note: find the ticket/session row component and understand what data fields are available (classification, confidence, language, status, elapsed time, etc.).

- [ ] **Step 2: Add glass card container for each ticket row**

Find the container div for each ticket item in the list/map. Add glass card styling:

```tsx
// Ticket row container:
className={cn(
  "group relative p-4 rounded-xl border transition-all duration-300",
  "bg-[rgba(255,255,255,0.02)] border-[rgba(255,255,255,0.055)]",
  "hover:bg-[rgba(255,255,255,0.04)] hover:border-[rgba(201,168,76,0.16)]",
  "hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(0,0,0,0.3)]"
)}
```

- [ ] **Step 3: Style confidence score as colored badge**

Find where confidence score is rendered. Replace with a badge:

```tsx
{/* Confidence badge — derive color from score */}
{(() => {
  const score = typeof item.confidence === "number" ? item.confidence : parseFloat(item.confidence ?? "0");
  const color = score >= 0.9 ? "#30D158" : score >= 0.7 ? "#FFD60A" : "#FF453A";
  return (
    <span
      className="inline-flex items-center text-[9px] font-mono px-1.5 py-0.5 rounded border"
      style={{
        color,
        background: `${color}18`,
        borderColor: `${color}30`,
      }}
    >
      {score.toFixed(2)}
    </span>
  );
})()}
```

- [ ] **Step 4: Style governance status badge**

Find where ALLOW/DENY/PENDING is displayed. Replace with:

```tsx
{(() => {
  const statusMap: Record<string, { label: string; className: string }> = {
    allow: { label: "ALLOW", className: "bg-[rgba(48,209,88,0.1)] text-[#30D158] border-[rgba(48,209,88,0.25)]" },
    deny: { label: "DENY", className: "bg-[rgba(255,69,58,0.1)] text-[#FF453A] border-[rgba(255,69,58,0.25)]" },
    pending: { label: "PENDING", className: "bg-[rgba(201,168,76,0.1)] text-[#C9A84C] border-[rgba(201,168,76,0.25)]" },
  };
  const key = (item.governanceStatus ?? "pending").toLowerCase();
  const cfg = statusMap[key] ?? statusMap.pending;
  return (
    <span className={cn("text-[9px] font-mono uppercase px-2 py-0.5 rounded border tracking-[0.06em]", cfg.className)}>
      {cfg.label}
    </span>
  );
})()}
```

- [ ] **Step 5: Style language badge**

Find where language/locale is displayed:

```tsx
<span className="text-[10px] font-mono text-[#00C7FF] bg-[rgba(0,199,255,0.08)] px-1.5 py-0.5 rounded border border-[rgba(0,199,255,0.15)]">
  {item.language ?? "en"}
</span>
```

- [ ] **Step 6: Add time-elapsed color coding**

If elapsed time is available (look for `created_at` or `elapsed_seconds`). Add color coding:

```tsx
{(() => {
  const elapsed = item.elapsed_seconds ?? 0;
  const color = elapsed < 30 ? "#30D158" : elapsed < 120 ? "#FFD60A" : "#FF453A";
  const label = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;
  return (
    <span className="text-[10px] font-mono" style={{ color }}>
      {label}
    </span>
  );
})()}
```

If `elapsed_seconds` doesn't exist in the data type, skip this step.

- [ ] **Step 7: Build check**

```bash
cd apps/command-center2/frontend && npm run build 2>&1 | grep -E "error TS|✓"
```

Expected: 0 TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add apps/command-center2/frontend/components/operations-queue.tsx
git commit -m "feat(cc): upgrade operations queue — glass cards, confidence badges, status badges, lang badges"
```

---

## Task 6: Upgrade Fraud Monitor

**Files:**
- Modify: `apps/command-center2/frontend/components/fraud-monitoring-view.tsx`

Preserve all circuit state data fetching and quarantine cluster logic.

- [ ] **Step 1: Read current fraud monitoring view**

```bash
cat apps/command-center2/frontend/components/fraud-monitoring-view.tsx
```

Note: find where `state === "CLOSED"` vs `state === "TRIPPED"` is used to render circuit state indicators.

- [ ] **Step 2: Add pulse animation to circuit state indicators**

Find the circuit state display element. Add conditional pulse:

```tsx
{/* Circuit state indicator */}
<div
  className={cn(
    "flex items-center gap-3 px-4 py-3 rounded-xl border transition-all duration-300",
    circuitState === "TRIPPED"
      ? "bg-[rgba(196,75,75,0.08)] border-[rgba(196,75,75,0.3)]"
      : "bg-[rgba(75,140,90,0.06)] border-[rgba(75,140,90,0.2)]"
  )}
>
  <span
    className={cn(
      "w-3 h-3 rounded-full flex-shrink-0",
      circuitState === "TRIPPED"
        ? "bg-[#C44B4B] animate-pulse-red"
        : "bg-[#4B8C5A] animate-pulse-green"
    )}
  />
  <span
    className="text-[11px] font-mono uppercase tracking-[0.1em]"
    style={{ color: circuitState === "TRIPPED" ? "#C44B4B" : "#4B8C5A" }}
  >
    {circuitState}
  </span>
</div>
```

- [ ] **Step 3: Add similarity score bar to quarantine cards**

Find where quarantine cluster items are rendered. Add a color bar showing similarity score:

```tsx
{/* Similarity score bar */}
{typeof item.similarity_score === "number" && (
  <div className="mt-2">
    <div className="flex justify-between mb-1">
      <span className="text-[9px] font-mono text-[#5A5A52] uppercase tracking-[0.1em]">Similarity</span>
      <span className="text-[9px] font-mono text-[#9A9A8A]">{(item.similarity_score * 100).toFixed(0)}%</span>
    </div>
    <div className="h-1 bg-[rgba(255,255,255,0.06)] rounded-full overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{
          width: `${item.similarity_score * 100}%`,
          background: item.similarity_score > 0.8
            ? "linear-gradient(90deg, #FFD60A, #FF453A)"
            : "linear-gradient(90deg, #4B8C5A, #00C7FF)",
        }}
      />
    </div>
  </div>
)}
```

- [ ] **Step 4: Build check**

```bash
cd apps/command-center2/frontend && npm run build 2>&1 | grep -E "error TS|✓"
```

Expected: 0 TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add apps/command-center2/frontend/components/fraud-monitoring-view.tsx
git commit -m "feat(cc): upgrade fraud monitor — circuit state pulse, similarity score bar"
```

---

## Task 7: Upgrade Crisis Control Panel

**Files:**
- Modify: `apps/command-center2/frontend/components/crisis-control-panel.tsx`

Preserve all template button logic, API calls, and deployment state. Upgrade visual styling of buttons and TTL countdown.

- [ ] **Step 1: Read current crisis panel**

```bash
cat apps/command-center2/frontend/components/crisis-control-panel.tsx
```

Note: find the 4 template buttons (BLOCK_SKU, HALT_REFUNDS, ESCALATE_ALL, FREEZE_CATEGORY) and the active deployment cards.

- [ ] **Step 2: Apply color-coded button styles**

Find the template buttons and add semantic color styling while preserving onClick handlers:

```tsx
const templateButtonStyles: Record<string, string> = {
  BLOCK_SKU: "border-[rgba(255,214,10,0.4)] bg-[rgba(255,214,10,0.06)] text-[#FFD60A] hover:bg-[rgba(255,214,10,0.12)] hover:border-[rgba(255,214,10,0.6)]",
  HALT_REFUNDS: "border-[rgba(196,75,75,0.4)] bg-[rgba(196,75,75,0.06)] text-[#C44B4B] hover:bg-[rgba(196,75,75,0.12)] hover:border-[rgba(196,75,75,0.6)]",
  ESCALATE_ALL: "border-[rgba(255,214,10,0.4)] bg-[rgba(255,214,10,0.06)] text-[#FFD60A] hover:bg-[rgba(255,214,10,0.12)] hover:border-[rgba(255,214,10,0.6)]",
  FREEZE_CATEGORY: "border-[rgba(0,199,255,0.4)] bg-[rgba(0,199,255,0.06)] text-[#00C7FF] hover:bg-[rgba(0,199,255,0.12)] hover:border-[rgba(0,199,255,0.6)]",
};

// Apply to each button: className={cn("px-4 py-3 rounded-xl border text-[12px] font-mono uppercase tracking-[0.08em] transition-all duration-200 cursor-pointer", templateButtonStyles[template.type] ?? "")}
```

- [ ] **Step 3: Add TTL countdown for active deployments**

Find where active crisis deployments are displayed. If a `ttl_seconds` or `expires_at` field is available, add a countdown:

```tsx
"use client";
// Add at component level (or extract to sub-component):
function TtlCountdown({ expiresAt }: { expiresAt: string }) {
  const [remaining, setRemaining] = React.useState(0);
  React.useEffect(() => {
    const update = () => {
      const diff = Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000));
      setRemaining(diff);
    };
    update();
    const id = window.setInterval(update, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);
  const m = Math.floor(remaining / 60);
  const s = remaining % 60;
  return (
    <span className="text-[12px] font-mono text-[#FFD60A] tabular-nums">
      {m}:{String(s).padStart(2, "0")}
    </span>
  );
}
```

Use `<TtlCountdown expiresAt={deployment.expires_at} />` in the active deployment card if `expires_at` field exists. If it doesn't exist in the type, skip and leave existing TTL display as-is.

- [ ] **Step 4: Build check**

```bash
cd apps/command-center2/frontend && npm run build 2>&1 | grep -E "error TS|✓"
```

Expected: 0 TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add apps/command-center2/frontend/components/crisis-control-panel.tsx
git commit -m "feat(cc): upgrade crisis panel — color-coded buttons, TTL countdown"
```

---

## Task 8: Upgrade Trace Inspector

**Files:**
- Modify: `apps/command-center2/frontend/components/trace-inspector.tsx`

Preserve all existing timeline data, SSE, and span selection logic.

- [ ] **Step 1: Read current trace inspector**

```bash
cat apps/command-center2/frontend/components/trace-inspector.tsx | head -100
```

Note: find where individual timeline events/nodes are rendered and what fields are available (event type, governance outcome, etc.).

- [ ] **Step 2: Add glow to governance ALLOW nodes**

Find the event node element in the timeline. Add conditional glow styling:

```tsx
// For each event node circle/dot:
const isAllow = event.outcome === "ALLOW" || event.event_type?.includes("allow");
const isDeny  = event.outcome === "DENY"  || event.event_type?.includes("deny");

className={cn(
  "w-4 h-4 rounded-full border-2 flex-shrink-0 transition-all duration-300",
  isAllow ? "bg-[#4B8C5A] border-[#30D158] shadow-[0_0_12px_rgba(48,209,88,0.5)]" :
  isDeny  ? "bg-[#7A2A2A] border-[#C44B4B] shadow-[0_0_12px_rgba(196,75,75,0.5)]" :
  "bg-[#1A1A1E] border-[rgba(255,255,255,0.12)]"
)}
```

- [ ] **Step 3: Upgrade selected event ring**

Find where the currently selected event is highlighted. Replace with:

```tsx
// Selected event node gets an outer ring:
{isSelected && (
  <span className="absolute inset-[-4px] rounded-full border-2 border-[#C9A84C] shadow-[0_0_14px_rgba(201,168,76,0.3)]" />
)}
```

- [ ] **Step 4: Upgrade event detail panel**

Find the event detail panel (the right-side panel showing selected event details). Apply glass card styling:

```tsx
className="p-5 rounded-xl border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.02)] space-y-3"
```

For key/value pairs in the panel:

```tsx
// Key label:
className="text-[9px] font-mono uppercase tracking-[0.12em] text-[#5A5A52]"
// Value:
className="text-[12px] font-mono text-[#9A9A8A] mt-0.5"
```

- [ ] **Step 5: Build check**

```bash
cd apps/command-center2/frontend && npm run build 2>&1 | grep -E "error TS|✓"
```

Expected: 0 TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add apps/command-center2/frontend/components/trace-inspector.tsx
git commit -m "feat(cc): upgrade trace inspector — ALLOW green glow, DENY red glow, selected ring, glass detail panel"
```

---

## Task 9: Final Command Center Build Verification

- [ ] **Step 1: Clean build**

```bash
cd apps/command-center2/frontend && rm -rf .next && npm run build 2>&1
```

Expected: `✓ Compiled successfully` with 0 TypeScript errors.

- [ ] **Step 2: Check no TypeScript errors**

```bash
cd apps/command-center2/frontend && npx tsc --noEmit 2>&1 | grep -c "error TS"
```

Expected: `0`

- [ ] **Step 3: Final commit**

```bash
git add -A apps/command-center2/frontend/
git commit -m "feat(cc): command center redesign complete — dark tokens, page transitions, sidebar gold, queue/fraud/crisis/trace upgrades"
```

---

## Task 10: Cross-App Final Commit

- [ ] **Step 1: Verify both apps build**

```bash
cd apps/marketing2/frontend && npm run build 2>&1 | tail -3
cd apps/command-center2/frontend && npm run build 2>&1 | tail -3
```

Both expected: `✓ Compiled successfully`

- [ ] **Step 2: Push branch**

```bash
git push origin phase-2-2-stabilized
```

- [ ] **Step 3: Done**

Both apps redesigned. Summary of what changed:
- Marketing: Playfair Display + Inter, dark/cream dual palette, TextReveal, ContainerScroll, SkewCards, ZoomParallax, FlowArt, HoverPeek
- Command Center: Framer Motion page transitions, dark tokens, gold sidebar active state, pulse indicators, glass ticket cards, confidence/status badges
- All existing functionality, routing, API contracts, and auth preserved
