# Marketing Site Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `apps/marketing2/frontend` to a premium, immersive $10k-tier website with Playfair Display + Inter, dark/cream dual palette, Framer Motion animations, GSAP FlowArt, ContainerScroll, SkewCards, TextReveal, ZoomParallax, and HoverPeek — preserving all existing content, routing, and functionality.

**Architecture:** Hero stays dark (`#050508`), body switches to cream (`#F8F5EE`) from the Command Center section onward, then dark GSAP narrative panels, back to cream for industries. All new 21st.dev/Aceternity components are added to `components/ui/`. Existing data/API/content is preserved exactly.

**Tech Stack:** Next.js 16, React 19, Tailwind CSS 4, Framer Motion 12, GSAP + @gsap/react, @radix-ui/react-hover-card, qss, TypeScript 5

---

## File Map

**Create:**
- `components/ui/container-scroll-animation.tsx` — Aceternity tilt card
- `components/ui/gradient-card-showcase.tsx` — SkewCards capabilities
- `components/ui/link-preview.tsx` — HoverPeek for insights
- `components/ui/text-reveal.tsx` — TextRevealByWord bridge
- `components/ui/zoom-parallax.tsx` — ZoomParallax showcase
- `components/ui/story-scroll.tsx` — FlowArt GSAP narrative
- `components/hero-canvas.tsx` — canvas particle field (extracted from page)

**Modify:**
- `package.json` — add gsap, @gsap/react, qss, @radix-ui/react-hover-card
- `app/layout.tsx` — add Playfair Display + Inter Google Fonts
- `app/globals.css` — add font variables, new tokens, keyframes
- `app/page.tsx` — full hero + new sections composition
- `components/navigation.tsx` — scroll state, font upgrade, underline wipe
- `components/animated-headline.tsx` — Playfair Display support
- `components/feature-card.tsx` — visual upgrade (used in pillars section)
- `components/containment-layer.tsx` — hover state upgrade
- `components/proof-marquee.tsx` — keep but add gold dot variant
- `components/live-evidence.tsx` — terminal visual upgrade

---

## Task 1: Install New Dependencies

**Files:**
- Modify: `apps/marketing2/frontend/package.json`

- [ ] **Step 1: Add dependencies**

```bash
cd apps/marketing2/frontend
npm install gsap @gsap/react qss @radix-ui/react-hover-card
```

Expected output: `added N packages` with no errors.

- [ ] **Step 2: Verify install**

```bash
node -e "require('gsap'); require('qss'); console.log('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add apps/marketing2/frontend/package.json apps/marketing2/frontend/package-lock.json
git commit -m "chore(marketing): add gsap, qss, radix hover-card deps"
```

---

## Task 2: Add Google Fonts (Playfair Display + Inter)

**Files:**
- Modify: `apps/marketing2/frontend/app/layout.tsx`
- Modify: `apps/marketing2/frontend/app/globals.css`

- [ ] **Step 1: Update layout.tsx to add font imports**

Replace the existing imports section in `app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Playfair_Display, Inter } from "next/font/google";
import "./globals.css";
import { MarketingLayout } from "@/components/marketing-layout";
import { CookieConsent } from "@/components/cookie-consent";

const playfair = Playfair_Display({
  subsets: ["latin"],
  weight: ["700", "800", "900"],
  style: ["normal", "italic"],
  variable: "--font-playfair",
  display: "swap",
});

const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});
```

Update the `<html>` tag in the same file:

```tsx
<html
  lang="en"
  className={`${GeistSans.variable} ${GeistMono.variable} ${playfair.variable} ${inter.variable} h-full antialiased bg-canvas`}
>
```

- [ ] **Step 2: Add font tokens to globals.css**

Add after the existing `:root {` block (after the `--duration-slow` line):

```css
/* Typography — Playfair Display serif + Inter sans */
--font-serif: var(--font-playfair), 'Playfair Display', Georgia, serif;
--font-inter: var(--font-inter), 'Inter', system-ui, sans-serif;

/* Hero section dark bg */
--bg-hero: #050508;
/* Cream/sugar body bg */
--bg-cream: #F8F5EE;
--bg-cream2: #FBF9F4;
```

- [ ] **Step 3: Verify build compiles**

```bash
cd apps/marketing2/frontend && npm run build 2>&1 | tail -5
```

Expected: `✓ Compiled successfully` with 0 TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add apps/marketing2/frontend/app/layout.tsx apps/marketing2/frontend/app/globals.css
git commit -m "feat(marketing): add Playfair Display + Inter fonts, cream bg token"
```

---

## Task 3: Create New UI Components (copy-paste 21st.dev/Aceternity)

**Files:**
- Create: `apps/marketing2/frontend/components/ui/container-scroll-animation.tsx`
- Create: `apps/marketing2/frontend/components/ui/gradient-card-showcase.tsx`
- Create: `apps/marketing2/frontend/components/ui/link-preview.tsx`
- Create: `apps/marketing2/frontend/components/ui/text-reveal.tsx`
- Create: `apps/marketing2/frontend/components/ui/zoom-parallax.tsx`
- Create: `apps/marketing2/frontend/components/ui/story-scroll.tsx`

- [ ] **Step 1: Create components/ui directory if missing**

```bash
mkdir -p apps/marketing2/frontend/components/ui
```

- [ ] **Step 2: Create container-scroll-animation.tsx**

Create `apps/marketing2/frontend/components/ui/container-scroll-animation.tsx`:

```tsx
"use client";
import React, { useRef } from "react";
import { useScroll, useTransform, motion, MotionValue } from "framer-motion";

export const ContainerScroll = ({
  titleComponent,
  children,
}: {
  titleComponent: string | React.ReactNode;
  children: React.ReactNode;
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: containerRef });
  const [isMobile, setIsMobile] = React.useState(false);

  React.useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth <= 768);
    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  const scaleDimensions = () => (isMobile ? [0.7, 0.9] : [1.05, 1]);
  const rotate = useTransform(scrollYProgress, [0, 1], [18, 0]);
  const scale = useTransform(scrollYProgress, [0, 1], scaleDimensions());
  const translate = useTransform(scrollYProgress, [0, 1], [0, -100]);

  return (
    <div
      className="h-[60rem] md:h-[80rem] flex items-center justify-center relative p-2 md:p-20"
      ref={containerRef}
    >
      <div className="py-10 md:py-40 w-full relative" style={{ perspective: "1000px" }}>
        <Header translate={translate} titleComponent={titleComponent} />
        <Card rotate={rotate} translate={translate} scale={scale}>
          {children}
        </Card>
      </div>
    </div>
  );
};

export const Header = ({ translate, titleComponent }: any) => (
  <motion.div style={{ translateY: translate }} className="max-w-5xl mx-auto text-center mb-8">
    {titleComponent}
  </motion.div>
);

export const Card = ({
  rotate,
  scale,
  children,
}: {
  rotate: MotionValue<number>;
  scale: MotionValue<number>;
  translate: MotionValue<number>;
  children: React.ReactNode;
}) => (
  <motion.div
    style={{
      rotateX: rotate,
      scale,
      boxShadow:
        "0 0 #0000004d, 0 9px 20px #0000004a, 0 37px 37px #00000042, 0 84px 50px #00000026, 0 149px 60px #0000000a, 0 233px 65px #00000003",
    }}
    className="max-w-5xl -mt-12 mx-auto h-[30rem] md:h-[40rem] w-full border border-border-subtle p-2 md:p-4 bg-surface rounded-[24px] shadow-2xl"
  >
    <div className="h-full w-full overflow-hidden rounded-2xl bg-surface">
      {children}
    </div>
  </motion.div>
);
```

- [ ] **Step 3: Create gradient-card-showcase.tsx**

Create `apps/marketing2/frontend/components/ui/gradient-card-showcase.tsx`:

```tsx
"use client";
import React from "react";

export interface SkewCardProps {
  title: string;
  desc: string;
  gradientFrom: string;
  gradientTo: string;
  ctaHref?: string;
  ctaLabel?: string;
}

export function SkewCard({ title, desc, gradientFrom, gradientTo, ctaHref = "#", ctaLabel = "Learn more" }: SkewCardProps) {
  return (
    <div className="group relative w-[300px] h-[380px] m-[20px_16px] transition-all duration-500">
      <span
        className="absolute top-0 left-[40px] w-1/2 h-full rounded-xl transform skew-x-[14deg] transition-all duration-500 group-hover:skew-x-0 group-hover:left-[16px] group-hover:w-[calc(100%-80px)]"
        style={{ background: `linear-gradient(315deg, ${gradientFrom}, ${gradientTo})` }}
      />
      <span
        className="absolute top-0 left-[40px] w-1/2 h-full rounded-xl transform skew-x-[14deg] blur-[28px] opacity-50 transition-all duration-500 group-hover:skew-x-0 group-hover:left-[16px] group-hover:w-[calc(100%-80px)]"
        style={{ background: `linear-gradient(315deg, ${gradientFrom}, ${gradientTo})` }}
      />
      <div className="relative z-20 left-0 h-full p-[20px_28px] bg-white/[0.07] backdrop-blur-[10px] shadow-lg rounded-xl text-white transition-all duration-500 group-hover:left-[-20px] group-hover:p-[40px_28px] flex flex-col gap-3">
        <h3
          className="text-xl font-bold leading-tight"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          {title}
        </h3>
        <p className="text-sm leading-relaxed opacity-85 flex-1" style={{ fontFamily: "var(--font-inter)" }}>
          {desc}
        </p>
        <a
          href={ctaHref}
          className="inline-block text-sm font-semibold text-[#0A0F1C] bg-white px-4 py-2 rounded-lg hover:bg-[#F8F5EE] transition-colors self-start"
          style={{ fontFamily: "var(--font-inter)", letterSpacing: "0.03em" }}
        >
          {ctaLabel}
        </a>
      </div>
    </div>
  );
}

export default function SkewCards({ cards }: { cards: SkewCardProps[] }) {
  return (
    <div className="flex justify-center items-center flex-wrap py-4">
      {cards.map((card, idx) => (
        <SkewCard key={idx} {...card} />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Create text-reveal.tsx**

Create `apps/marketing2/frontend/components/ui/text-reveal.tsx`:

```tsx
"use client";
import { FC, ReactNode, useRef } from "react";
import { motion, MotionValue, useScroll, useTransform } from "framer-motion";
import { cn } from "@/lib/utils";

interface TextRevealByWordProps {
  text: string;
  className?: string;
}

const TextRevealByWord: FC<TextRevealByWordProps> = ({ text, className }) => {
  const targetRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: targetRef });
  const words = text.split(" ");

  return (
    <div ref={targetRef} className={cn("relative z-0 h-[200vh]", className)}>
      <div className="sticky top-0 mx-auto flex h-[50%] max-w-4xl items-center bg-transparent px-[1rem] py-[5rem]">
        <p
          className="flex flex-wrap p-5 text-2xl font-bold md:p-8 md:text-3xl lg:p-10 lg:text-4xl xl:text-5xl"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          {words.map((word, i) => {
            const start = i / words.length;
            const end = start + 1 / words.length;
            return (
              <Word key={i} progress={scrollYProgress} range={[start, end]}>
                {word}
              </Word>
            );
          })}
        </p>
      </div>
    </div>
  );
};

interface WordProps {
  children: ReactNode;
  progress: MotionValue<number>;
  range: [number, number];
}

const Word: FC<WordProps> = ({ children, progress, range }) => {
  const opacity = useTransform(progress, range, [0, 1]);
  return (
    <span className="xl:lg-3 relative mx-1 lg:mx-2.5">
      <span className="absolute text-ink-tertiary/30">{children}</span>
      <motion.span style={{ opacity }} className="text-ink-primary">
        {children}
      </motion.span>
    </span>
  );
};

export { TextRevealByWord };
```

- [ ] **Step 5: Create zoom-parallax.tsx**

Create `apps/marketing2/frontend/components/ui/zoom-parallax.tsx`:

```tsx
"use client";
import { useScroll, useTransform, motion } from "framer-motion";
import { useRef } from "react";

interface ZoomImage {
  src: string;
  alt?: string;
}

interface ZoomParallaxProps {
  images: ZoomImage[];
}

export function ZoomParallax({ images }: ZoomParallaxProps) {
  const container = useRef(null);
  const { scrollYProgress } = useScroll({
    target: container,
    offset: ["start start", "end end"],
  });

  const scale4 = useTransform(scrollYProgress, [0, 1], [1, 4]);
  const scale5 = useTransform(scrollYProgress, [0, 1], [1, 5]);
  const scale6 = useTransform(scrollYProgress, [0, 1], [1, 6]);
  const scale8 = useTransform(scrollYProgress, [0, 1], [1, 8]);
  const scale9 = useTransform(scrollYProgress, [0, 1], [1, 9]);
  const scales = [scale4, scale5, scale6, scale5, scale6, scale8, scale9];

  return (
    <div ref={container} className="relative h-[300vh]">
      <div className="sticky top-0 h-screen overflow-hidden">
        {images.map(({ src, alt }, index) => {
          const scale = scales[index % scales.length];
          return (
            <motion.div
              key={index}
              style={{ scale }}
              className={`absolute top-0 flex h-full w-full items-center justify-center ${
                index === 1 ? "[&>div]:!-top-[30vh] [&>div]:!left-[5vw] [&>div]:!h-[30vh] [&>div]:!w-[35vw]" : ""
              } ${index === 2 ? "[&>div]:!-top-[10vh] [&>div]:!-left-[25vw] [&>div]:!h-[45vh] [&>div]:!w-[20vw]" : ""} ${
                index === 3 ? "[&>div]:!left-[27.5vw] [&>div]:!h-[25vh] [&>div]:!w-[25vw]" : ""
              } ${index === 4 ? "[&>div]:!top-[27.5vh] [&>div]:!left-[5vw] [&>div]:!h-[25vh] [&>div]:!w-[20vw]" : ""} ${
                index === 5 ? "[&>div]:!top-[27.5vh] [&>div]:!-left-[22.5vw] [&>div]:!h-[25vh] [&>div]:!w-[30vw]" : ""
              } ${index === 6 ? "[&>div]:!top-[22.5vh] [&>div]:!left-[25vw] [&>div]:!h-[15vh] [&>div]:!w-[15vw]" : ""}`}
            >
              <div className="relative h-[25vh] w-[25vw]">
                <img src={src} alt={alt || `Image ${index + 1}`} className="h-full w-full object-cover" />
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Create story-scroll.tsx**

Create `apps/marketing2/frontend/components/ui/story-scroll.tsx`:

```tsx
"use client";
import React, { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(ScrollTrigger);

function cx(...parts: Array<string | undefined | false | null>): string {
  return parts.filter(Boolean).join(" ");
}

export interface FlowSectionProps {
  className?: string;
  style?: React.CSSProperties;
  children: React.ReactNode;
  "aria-label"?: string;
}

export const FlowSection: React.FC<FlowSectionProps> = ({
  className,
  style = {},
  children,
  "aria-label": ariaLabel,
}) => (
  <section
    data-flow-section
    aria-label={ariaLabel}
    className={cx("relative min-h-screen w-full overflow-hidden", className)}
  >
    <div
      data-flow-inner
      className={cx(
        "flow-art-container relative flex min-h-screen w-full flex-col justify-between gap-6 px-[4vw] pt-[clamp(2rem,8vw,4vw)] pb-[4vw]",
        "will-change-transform"
      )}
      style={{ transformOrigin: "bottom left", ...style }}
    >
      {children}
    </div>
  </section>
);

export interface FlowArtProps {
  children: React.ReactNode;
  className?: string;
  "aria-label"?: string;
}

const childCount = (children: React.ReactNode) => React.Children.count(children);

const FlowArt: React.FC<FlowArtProps> = ({
  children,
  className,
  "aria-label": ariaLabel = "Story scroll",
}) => {
  const containerRef = useRef<HTMLElement>(null);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  useGSAP(
    () => {
      if (!containerRef.current || reducedMotion) return;
      const sections = Array.from(
        containerRef.current.querySelectorAll<HTMLElement>("[data-flow-section]")
      );
      if (sections.length === 0) return;
      const triggers: ScrollTrigger[] = [];
      sections.forEach((section, i) => {
        gsap.set(section, { zIndex: i + 1 });
        const inner = section.querySelector<HTMLElement>(".flow-art-container");
        if (!inner) return;
        if (i > 0) {
          gsap.set(inner, { rotation: 30, transformOrigin: "bottom left" });
          const tween = gsap.to(inner, {
            rotation: 0,
            ease: "none",
            scrollTrigger: {
              trigger: section,
              start: "top bottom",
              end: "top 25%",
              scrub: true,
            },
          });
          if (tween.scrollTrigger) triggers.push(tween.scrollTrigger);
        }
        if (i < sections.length - 1) {
          triggers.push(
            ScrollTrigger.create({
              trigger: section,
              start: "bottom bottom",
              end: "bottom top",
              pin: true,
              pinSpacing: false,
            })
          );
        }
      });
      ScrollTrigger.refresh();
      return () => triggers.forEach((t) => t.kill());
    },
    { scope: containerRef, dependencies: [childCount(children), reducedMotion] }
  );

  return (
    <main ref={containerRef} aria-label={ariaLabel} className={cx("w-full overflow-x-hidden", className)}>
      {children}
    </main>
  );
};

export default FlowArt;
```

- [ ] **Step 7: Create link-preview.tsx**

Create `apps/marketing2/frontend/components/ui/link-preview.tsx`:

```tsx
"use client";
import * as RdxHoverCard from "@radix-ui/react-hover-card";
import { encode } from "qss";
import React, { useState, useMemo, useCallback, useEffect } from "react";
import { AnimatePresence, motion, useMotionValue, useSpring } from "framer-motion";
import { cn } from "@/lib/utils";

function usePreviewSource(url: string, width: number, height: number, isStatic: boolean, staticImageSrc?: string) {
  return useMemo(() => {
    if (isStatic) return staticImageSrc || "";
    const params = encode({
      url,
      screenshot: true,
      meta: false,
      embed: "screenshot.url",
      colorScheme: "dark",
      "viewport.isMobile": true,
      "viewport.deviceScaleFactor": 1,
      "viewport.width": width * 2.5,
      "viewport.height": height * 2.5,
    });
    return `https://api.microlink.io/?${params}`;
  }, [isStatic, staticImageSrc, url, width, height]);
}

function useHoverState(followMouse: boolean) {
  const [isPeeking, setPeeking] = useState(false);
  const mouseX = useMotionValue(0);
  const followX = useSpring(mouseX, { stiffness: 120, damping: 20 });
  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      if (!followMouse) return;
      const target = event.currentTarget;
      const rect = target.getBoundingClientRect();
      mouseX.set((event.clientX - rect.left - rect.width / 2) * 0.3);
    },
    [mouseX, followMouse]
  );
  const handleOpenChange = useCallback(
    (open: boolean) => {
      setPeeking(open);
      if (!open) mouseX.set(0);
    },
    [mouseX]
  );
  return { isPeeking, handleOpenChange, handlePointerMove, followX };
}

type HoverPeekProps = {
  children: React.ReactNode;
  url: string;
  className?: string;
  peekWidth?: number;
  peekHeight?: number;
  enableMouseFollow?: boolean;
} & ({ isStatic: true; imageSrc: string } | { isStatic?: false; imageSrc?: never });

export const HoverPeek = ({
  children,
  url,
  className,
  peekWidth = 200,
  peekHeight = 125,
  isStatic = false,
  imageSrc = "",
  enableMouseFollow = true,
}: HoverPeekProps) => {
  const [imageLoadFailed, setImageLoadFailed] = useState(false);
  const finalImageSrc = usePreviewSource(url, peekWidth, peekHeight, isStatic, imageSrc);
  const { isPeeking, handleOpenChange, handlePointerMove, followX } = useHoverState(enableMouseFollow);

  useEffect(() => { setImageLoadFailed(false); }, [finalImageSrc]);
  useEffect(() => { if (!isPeeking) setImageLoadFailed(false); }, [isPeeking]);

  const triggerChild = React.isValidElement(children)
    ? React.cloneElement(children as React.ReactElement<any>, {
        className: cn((children.props as any).className, className),
        onPointerMove: handlePointerMove,
      })
    : <span className={className} onPointerMove={handlePointerMove}>{children}</span>;

  return (
    <RdxHoverCard.Root openDelay={75} closeDelay={150} onOpenChange={handleOpenChange}>
      <RdxHoverCard.Trigger asChild>{triggerChild}</RdxHoverCard.Trigger>
      <RdxHoverCard.Portal>
        <RdxHoverCard.Content className="[perspective:800px] z-50" side="top" align="center" sideOffset={12}>
          <AnimatePresence>
            {isPeeking && (
              <motion.div
                initial={{ opacity: 0, rotateY: -90 }}
                animate={{ opacity: 1, rotateY: 0, transition: { type: "spring", stiffness: 200, damping: 18 } }}
                exit={{ opacity: 0, rotateY: 90, transition: { duration: 0.15 } }}
                style={{ x: enableMouseFollow ? followX : 0 }}
              >
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="relative block overflow-hidden rounded-lg border border-border-subtle bg-surface shadow-lg p-0.5"
                >
                  {imageLoadFailed ? (
                    <div className="flex items-center justify-center bg-surface-raised text-ink-tertiary text-xs" style={{ width: peekWidth, height: peekHeight }}>
                      Preview unavailable
                    </div>
                  ) : (
                    <img
                      src={finalImageSrc}
                      width={peekWidth}
                      height={peekHeight}
                      className="block rounded-[5px] pointer-events-none bg-surface-raised"
                      alt={`Preview for ${url}`}
                      onError={() => setImageLoadFailed(true)}
                      loading="lazy"
                    />
                  )}
                </a>
              </motion.div>
            )}
          </AnimatePresence>
        </RdxHoverCard.Content>
      </RdxHoverCard.Portal>
    </RdxHoverCard.Root>
  );
};
```

- [ ] **Step 8: Verify TypeScript compiles**

```bash
cd apps/marketing2/frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: 0 errors (warnings about existing code are acceptable).

- [ ] **Step 9: Commit all new components**

```bash
git add apps/marketing2/frontend/components/ui/
git commit -m "feat(marketing): add 21st.dev/Aceternity UI components to components/ui/"
```

---

## Task 4: Upgrade Navigation

**Files:**
- Modify: `apps/marketing2/frontend/components/navigation.tsx`

The existing navigation is sophisticated — preserve all dropdown logic, links, and mobile behavior. Only upgrade visual styling.

- [ ] **Step 1: Add scroll-state background effect**

In `navigation.tsx`, locate the outer `<nav>` element. Add a `useEffect` that tracks scroll position:

```tsx
// Add at top of the Navigation component (after existing state declarations):
const [scrolled, setScrolled] = React.useState(false);
React.useEffect(() => {
  const onScroll = () => setScrolled(window.scrollY > 60);
  window.addEventListener("scroll", onScroll, { passive: true });
  return () => window.removeEventListener("scroll", onScroll);
}, []);
```

Update the outer nav `className` to include scroll state:

```tsx
// Find the outer <nav> element and update its className:
<nav
  className={cn(
    "fixed top-0 left-0 right-0 z-50 transition-all duration-500",
    scrolled
      ? "border-b border-white/5 bg-[rgba(5,5,8,0.92)] backdrop-blur-xl"
      : "bg-transparent backdrop-blur-sm"
  )}
>
```

- [ ] **Step 2: Apply Playfair Display to nav wordmark**

Find the `OperioussLogo` usage or wordmark text. The logo component uses monospace — keep it. Apply Inter to nav link text:

```tsx
// In NavDropdown and any nav link text, add font-[family-name:var(--font-inter)] or use class:
// Find existing link text classes and add: style={{ fontFamily: "var(--font-inter)" }}
// For the top-level nav links (Platform, Industries, Trust, Insights):
className="flex items-center gap-1 text-[13px] font-medium text-[#D8E4F4]/80 transition-colors duration-200 hover:text-[#C9A84C]"
style={{ fontFamily: "var(--font-inter)", letterSpacing: "0.02em" }}
```

- [ ] **Step 3: Add underline wipe hover on link items**

For individual link items inside dropdowns (the `<Link>` elements inside `NavDropdown`), update their base class to include:

```tsx
className="group -m-3 block rounded-md p-3 transition-colors duration-200 hover:bg-white/[0.04] relative"
```

And the link title:

```tsx
<div className="text-[13px] font-semibold text-[#F2F0EA] transition-colors duration-200 group-hover:text-[#C9A84C] relative after:absolute after:bottom-0 after:left-0 after:h-px after:w-0 after:bg-[#C9A84C] after:transition-all after:duration-300 group-hover:after:w-full">
  {item.label}
</div>
```

- [ ] **Step 4: Build check**

```bash
cd apps/marketing2/frontend && npm run build 2>&1 | tail -5
```

Expected: 0 TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add apps/marketing2/frontend/components/navigation.tsx
git commit -m "feat(marketing): upgrade nav with scroll blur, Inter font, underline hover"
```

---

## Task 5: Redesign Hero Section

**Files:**
- Modify: `apps/marketing2/frontend/app/page.tsx`
- Modify: `apps/marketing2/frontend/components/animated-headline.tsx`

The hero is the most critical section. Keep the existing `SplineHeroBg`, `Reveal`, `RevealGroup`, and `Button` components. Replace the headline, layout, and add canvas particles.

- [ ] **Step 1: Upgrade AnimatedHeadline for Playfair Display**

Replace the contents of `components/animated-headline.tsx`:

```tsx
"use client";
import { motion, useReducedMotion } from "framer-motion";

interface AnimatedHeadlineProps {
  children: string;
  className?: string;
  /** Words to render in italic gold gradient */
  accentWords?: string[];
}

export function AnimatedHeadline({
  children,
  className,
  accentWords = [],
}: AnimatedHeadlineProps) {
  const reducedMotion = useReducedMotion();
  const words = children.split(" ");

  if (reducedMotion) {
    return <h1 className={className} style={{ fontFamily: "var(--font-serif)" }}>{children}</h1>;
  }

  return (
    <h1 className={className} aria-label={children} style={{ fontFamily: "var(--font-serif)" }}>
      {words.map((word, index) => {
        const isAccent = accentWords.includes(word);
        return (
          <motion.span
            aria-hidden="true"
            key={`${word}-${index}`}
            className="inline-block overflow-hidden align-bottom"
            initial={{ opacity: 0, y: "100%" }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: 0.3 + index * 0.08,
              duration: 0.75,
              ease: [0.16, 1, 0.3, 1],
            }}
          >
            {isAccent ? (
              <span
                className="italic"
                style={{
                  background: "linear-gradient(130deg, #A8882C 0%, #C9A84C 35%, #E8C76A 65%, #C9A84C 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}
              >
                {word}
              </span>
            ) : (
              word
            )}
            {index < words.length - 1 ? " " : ""}
          </motion.span>
        );
      })}
    </h1>
  );
}
```

- [ ] **Step 2: Update hero section in page.tsx**

In `app/page.tsx`, find the first `<section>` (the hero section). Replace the headline and eyebrow while keeping `SplineHeroBg`, background gradient div, grid overlay div, and `RevealGroup` structure:

```tsx
// Replace the hero section content (keep SplineHeroBg and bg divs):
<RevealGroup
  className="relative z-10 mx-auto flex max-w-[1320px] flex-col items-center gap-12 lg:min-h-[calc(100vh-160px)] lg:justify-center text-center"
  mode="load"
>
  {/* Eyebrow */}
  <Reveal>
    <div className="inline-flex items-center gap-3">
      <span className="w-7 h-px bg-gold-bright" />
      <span
        className="text-[9px] uppercase tracking-[0.22em] text-gold-bright"
        style={{ fontFamily: "var(--font-mono)" }}
      >
        Governed Execution Infrastructure
      </span>
      <span className="w-7 h-px bg-gold-bright" />
    </div>
  </Reveal>

  {/* Headline */}
  <div className="w-full max-w-[960px]">
    <Reveal>
      <AnimatedHeadline
        className="text-[52px] font-extrabold leading-[0.93] tracking-[-0.02em] sm:text-[72px] lg:text-[108px] text-[#D8E4F4]"
        accentWords={["governs", "AI"]}
      >
        The runtime that governs AI at scale.
      </AnimatedHeadline>
    </Reveal>
  </div>

  {/* Subheadline */}
  <Reveal>
    <p
      className="max-w-[640px] text-[18px] leading-[1.75] text-[#7A90B4] font-normal"
      style={{ fontFamily: "var(--font-inter)" }}
    >
      The runtime between AI decisions and enterprise actions — governed by policy,
      permanently reconstructible, and auditable to the byte.
    </p>
  </Reveal>

  {/* CTAs */}
  <Reveal>
    <div className="flex flex-col gap-3 sm:flex-row justify-center">
      <Button
        href="/company/contact"
        variant="primary"
        className="shadow-[0_12px_34px_rgba(201,168,76,0.22)] hover:shadow-[0_18px_44px_rgba(201,168,76,0.34)]"
      >
        Request enterprise access
        <ArrowRight className="ml-2 h-4 w-4" />
      </Button>
      <Button
        href="/platform"
        variant="ghost"
        className="bg-[#0B1120]/60 hover:shadow-[0_16px_36px_rgba(42,107,204,0.22)]"
      >
        Explore the architecture
        <ArrowRight className="ml-2 h-4 w-4" />
      </Button>
    </div>
  </Reveal>

  {/* 7-substrate strip */}
  <Reveal>
    <div className="flex border border-white/5 rounded-xl overflow-hidden bg-white/[0.014] backdrop-blur-md max-w-[700px] w-full">
      {["Boundary","Coordination","Governance","Session","Execution","Supervisor","Arbitration"].map((name, i) => (
        <div
          key={name}
          className="flex-1 py-[14px] px-2 text-center border-r border-white/[0.04] last:border-r-0 hover:bg-[rgba(201,168,76,0.05)] transition-colors group cursor-default"
        >
          <div
            className="text-[8px] text-gold/45 font-mono tracking-[0.12em] mb-1 group-hover:text-gold transition-colors"
          >
            {String(i + 1).padStart(2, "0")}
          </div>
          <div className="text-[10px] text-[#2E3E50] font-medium tracking-[0.03em] group-hover:text-[#7A90B4] transition-colors">
            {name}
          </div>
        </div>
      ))}
    </div>
  </Reveal>
</RevealGroup>
```

- [ ] **Step 3: Apply magnetic button effect to primary CTA**

Add a client-side wrapper for magnetic effect. Create `components/magnetic-button.tsx`:

```tsx
"use client";
import { useRef, ReactNode } from "react";

export function MagneticWrapper({ children, strength = 0.07 }: { children: ReactNode; strength?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const x = (e.clientX - (r.left + r.width / 2)) * strength;
    const y = (e.clientY - (r.top + r.height / 2)) * strength;
    ref.current.style.transform = `translate(${x}px, ${y}px)`;
  };
  const handleMouseLeave = () => {
    if (ref.current) ref.current.style.transform = "";
  };
  return (
    <div ref={ref} onMouseMove={handleMouseMove} onMouseLeave={handleMouseLeave} style={{ transition: "transform 0.2s cubic-bezier(0.16,1,0.3,1)", display: "inline-flex" }}>
      {children}
    </div>
  );
}
```

Wrap the primary CTA button in `page.tsx` hero section inside `<MagneticWrapper>`.

- [ ] **Step 4: Build check**

```bash
cd apps/marketing2/frontend && npm run build 2>&1 | grep -E "error|Error|✓"
```

Expected: 0 TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add apps/marketing2/frontend/app/page.tsx apps/marketing2/frontend/components/animated-headline.tsx apps/marketing2/frontend/components/magnetic-button.tsx
git commit -m "feat(marketing): redesign hero with Playfair Display, substrate strip, magnetic CTA"
```

---

## Task 6: Add TextRevealByWord Bridge + ProofMarquee

**Files:**
- Modify: `apps/marketing2/frontend/app/page.tsx`
- Modify: `apps/marketing2/frontend/components/proof-marquee.tsx`

- [ ] **Step 1: Add TextRevealByWord after hero section in page.tsx**

After the closing `</section>` of the hero and after `<ProofMarquee />`, add:

```tsx
{/* TextRevealByWord bridge */}
<section className="bg-[#050508] py-0">
  <TextRevealByWord
    text="Every enterprise AI deployment needs a governance layer between what the model proposes and what the system executes. Operious is that layer."
    className="text-[#D8E4F4]/20"
  />
</section>
```

Add the import at the top of `page.tsx`:

```tsx
import { TextRevealByWord } from "@/components/ui/text-reveal";
```

- [ ] **Step 2: Upgrade ProofMarquee with gold dots**

Replace `components/proof-marquee.tsx` content:

```tsx
"use client";

const proofPoints = [
  "Cryptographically Audited",
  "UUID5 Identity",
  "Force RLS on Every Table",
  "Append-Only Timelines",
  "Fail-Closed Governance",
  "ToolInvoker Enforcement",
  "Deterministic Replay",
  "Tenant-Isolated",
  "Multi-Agent Coordination",
  "Zero Silent Drops",
  "Six Languages Native",
];

export function ProofMarquee() {
  const doubled = [...proofPoints, ...proofPoints];
  return (
    <div className="w-full overflow-hidden border-y border-white/[0.04] bg-[#050508] py-5">
      <div className="flex animate-marquee gap-0 whitespace-nowrap">
        {doubled.map((item, i) => (
          <span key={i} className="flex shrink-0 items-center gap-3 px-7">
            <span className="w-[3px] h-[3px] rounded-full bg-[#30D158] shadow-[0_0_5px_rgba(48,209,88,0.7)]" />
            <span
              className="text-[9px] uppercase tracking-[0.12em] text-[#1A2E3E]"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {item}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Build check**

```bash
cd apps/marketing2/frontend && npm run build 2>&1 | grep -E "error|✓"
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add apps/marketing2/frontend/app/page.tsx apps/marketing2/frontend/components/proof-marquee.tsx
git commit -m "feat(marketing): add TextRevealByWord bridge, upgrade ProofMarquee with gold dots"
```

---

## Task 7: Add ContainerScroll — Command Center Reveal

**Files:**
- Modify: `apps/marketing2/frontend/app/page.tsx`
- Create: `apps/marketing2/frontend/components/command-center-preview.tsx`

- [ ] **Step 1: Create command-center-preview.tsx**

This is the content rendered inside the ContainerScroll card — a static but realistic-looking Command Center mockup:

```tsx
"use client";
export function CommandCenterPreview() {
  const sessions = [
    { id: "df6139ba", classification: "charging_issue", confidence: "0.93", lang: "ar → en", status: "ALLOW" },
    { id: "a82c4f01", classification: "warranty_claim", confidence: "0.88", lang: "en", status: "APPROVAL" },
    { id: "7e3b91d5", classification: "refund_request", confidence: "0.71", lang: "ar", status: "ALLOW" },
    { id: "c29f3a88", classification: "replacement_order", confidence: "0.95", lang: "en", status: "ALLOW" },
  ];

  const badgeClass = (status: string) => {
    if (status === "ALLOW") return "bg-green-500/10 text-green-700 border border-green-500/20";
    if (status === "APPROVAL") return "bg-amber-500/10 text-amber-700 border border-amber-500/20";
    return "bg-red-500/10 text-red-700 border border-red-500/20";
  };

  return (
    <div className="w-full h-full bg-[#F8F8FC] rounded-[18px] flex flex-col overflow-hidden text-[#0A0F1C]">
      {/* Window chrome */}
      <div className="flex items-center gap-2 px-4 py-3 bg-white border-b border-[#F0EEF8]">
        <span className="w-3 h-3 rounded-full bg-[#FF453A]" />
        <span className="w-3 h-3 rounded-full bg-[#FFD60A]" />
        <span className="w-3 h-3 rounded-full bg-[#30D158]" />
        <span className="ml-3 text-[9px] font-mono tracking-[0.12em] text-[#9AA0B0] uppercase">
          Operious · Command Center · anker-pilot
        </span>
        <span className="ml-auto bg-[rgba(201,168,76,0.12)] text-[#A8882C] text-[8px] font-mono px-2 py-0.5 rounded">
          3 Active Sessions
        </span>
      </div>
      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <div className="w-48 bg-white border-r border-[#F0EEF8] py-2 flex-shrink-0">
          {[
            { label: "Operations Queue", active: true },
            { label: "Conversations", active: false },
            { label: "Approvals", active: false, badge: "2" },
            { label: "Trace Inspector", active: false },
            { label: "Fraud Monitor", active: false },
            { label: "Crisis Control", active: false, danger: true },
          ].map(({ label, active, badge, danger }) => (
            <div
              key={label}
              className={`flex items-center justify-between px-4 py-2 text-[10px] cursor-default transition-colors ${
                active
                  ? "font-semibold text-[#0A0F1C] bg-[rgba(201,168,76,0.06)] border-l-2 border-[#C9A84C]"
                  : danger
                  ? "text-[#DC2626] opacity-75"
                  : "text-[#9AA0B0]"
              }`}
            >
              {label}
              {badge && (
                <span className="bg-[rgba(201,168,76,0.15)] text-[#A8882C] text-[8px] px-1.5 py-0.5 rounded font-mono">
                  {badge}
                </span>
              )}
            </div>
          ))}
        </div>
        {/* Main content */}
        <div className="flex-1 p-4 flex flex-col gap-3 overflow-hidden">
          {/* KPI row */}
          <div className="grid grid-cols-4 gap-2">
            {[
              { n: "3", l: "Active Sessions", color: "#0A0F1C" },
              { n: "47", l: "Resolved Today", color: "#1A7A3A" },
              { n: "2", l: "Pending Approval", color: "#8A6018" },
              { n: "0", l: "DLQ Items", color: "#0A0F1C" },
            ].map(({ n, l, color }) => (
              <div key={l} className="bg-white border border-[#F0EEF8] rounded-xl p-3 text-center">
                <div className="text-lg font-extrabold" style={{ color, fontFamily: "var(--font-inter)" }}>{n}</div>
                <div className="text-[8px] font-mono uppercase tracking-[0.08em] text-[#9AA0B0] mt-0.5">{l}</div>
              </div>
            ))}
          </div>
          {/* Table */}
          <div className="flex-1 bg-white border border-[#F0EEF8] rounded-xl overflow-hidden">
            <div className="grid grid-cols-[90px_1fr_60px_80px] gap-0 px-3 py-2 bg-[#F8F8FC] border-b border-[#F0EEF8]">
              {["Session", "Classification", "Lang", "Status"].map((h) => (
                <div key={h} className="text-[8px] font-mono uppercase tracking-[0.1em] text-[#9AA0B0]">{h}</div>
              ))}
            </div>
            {sessions.map(({ id, classification, confidence, lang, status }) => (
              <div key={id} className="grid grid-cols-[90px_1fr_60px_80px] gap-0 px-3 py-2.5 border-b border-[#F8F8FC] hover:bg-[#FDFCFB] transition-colors">
                <div className="text-[10px] font-mono text-[#9AA0B0]">{id}</div>
                <div className="text-[11px] text-[#2A3548]" style={{ fontFamily: "var(--font-inter)" }}>
                  {classification} <span className="text-[#9AA0B0] text-[10px]">· {confidence}</span>
                </div>
                <div className="text-[10px] font-mono text-[#2A5CAA]">{lang}</div>
                <div>
                  <span className={`text-[8px] font-mono px-2 py-0.5 rounded ${badgeClass(status)}`}>
                    {status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add ContainerScroll section to page.tsx**

After the TextRevealByWord section (before the existing features section), add:

```tsx
{/* ContainerScroll: Command Center Reveal */}
<section className="bg-[#F8F5EE] pt-20 pb-0">
  <ContainerScroll
    titleComponent={
      <div className="mb-8">
        <p
          className="text-[9px] uppercase tracking-[0.2em] text-gold-bright mb-3"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          Command Center
        </p>
        <h2
          className="text-[38px] font-extrabold leading-[1.05] tracking-[-0.02em] text-ink-primary sm:text-[54px]"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          The operational intelligence layer
          <br />
          your team actually uses.
        </h2>
        <p className="mt-4 text-[16px] text-ink-secondary max-w-[520px] mx-auto leading-[1.7]" style={{ fontFamily: "var(--font-inter)" }}>
          A live view of every session, every governance decision, every approval — in one place. Built for operators, not engineers.
        </p>
      </div>
    }
  >
    <CommandCenterPreview />
  </ContainerScroll>
</section>
```

Add imports:

```tsx
import { ContainerScroll } from "@/components/ui/container-scroll-animation";
import { CommandCenterPreview } from "@/components/command-center-preview";
```

- [ ] **Step 3: Build check**

```bash
cd apps/marketing2/frontend && npm run build 2>&1 | grep -E "error|✓"
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add apps/marketing2/frontend/app/page.tsx apps/marketing2/frontend/components/command-center-preview.tsx
git commit -m "feat(marketing): add ContainerScroll Command Center reveal section on cream bg"
```

---

## Task 8: Replace Feature Grid with SkewCards

**Files:**
- Modify: `apps/marketing2/frontend/app/page.tsx`

The existing features section uses a `pillars` array with 4 items and `FeatureCard` component. Replace with `SkewCards` + expand to 6 cards covering all capabilities.

- [ ] **Step 1: Replace the Core Features section in page.tsx**

Find the section labeled `"Core features"` and replace it:

```tsx
{/* Capabilities — SkewCards */}
<section className="bg-[#F8F5EE] px-4 py-20 sm:px-8 sm:py-24 lg:px-16">
  <div className="mx-auto max-w-[1280px]">
    <RevealGroup>
      <Reveal>
        <SectionLabel>Capabilities</SectionLabel>
        <h2
          className="mt-5 max-w-[760px] text-[38px] font-extrabold leading-tight text-ink-primary sm:text-[54px]"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          The infrastructure enterprise AI actually requires.
        </h2>
      </Reveal>
    </RevealGroup>
    <SkewCards
      cards={[
        {
          title: "Constitutional Governance",
          desc: "Policy chains evaluate every proposed action. Fail-closed: no model output executes without passing governance. Empty chains return DENY — no implicit allow.",
          gradientFrom: "#A8882C",
          gradientTo: "#C9A84C",
          ctaHref: "/platform/governance",
        },
        {
          title: "Forensic Reconstructibility",
          desc: "Replay any decision at any point in time. UUID5 identity, HMAC signatures, and append-only timelines make every outcome defensible in any audit.",
          gradientFrom: "#1A4A9A",
          gradientTo: "#00C7FF",
          ctaHref: "/platform/replay",
        },
        {
          title: "Multi-Agent Coordination",
          desc: "Deterministic orchestration across Diagnostic, Resolution, Supervisor, and Trainer agents — structural guarantees against deadlock and cross-tenant contamination.",
          gradientFrom: "#0D4A2A",
          gradientTo: "#30D158",
          ctaHref: "/platform/agents",
        },
        {
          title: "Multilingual Operations",
          desc: "Arabic, English, and four further languages — language context preserved through triage, governance, and customer reply. Never silently dropped.",
          gradientFrom: "#4A1A7A",
          gradientTo: "#8B5CF6",
        },
        {
          title: "Crisis Override Control",
          desc: "Emergency rules activate in milliseconds. Block a SKU, halt a refund class, escalate a category — with automatic expiry and full audit evidence.",
          gradientFrom: "#7A1A1A",
          gradientTo: "#FF453A",
        },
        {
          title: "SOP Citation Intelligence",
          desc: "Every proposed resolution cited against your tenant SOP documents. No uncited claims. Every customer reply grounded in your own policies.",
          gradientFrom: "#3A4A1A",
          gradientTo: "#84CC16",
        },
      ]}
    />
  </div>
</section>
```

Add import:

```tsx
import SkewCards from "@/components/ui/gradient-card-showcase";
```

- [ ] **Step 2: Build check**

```bash
cd apps/marketing2/frontend && npm run build 2>&1 | grep -E "error|✓"
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add apps/marketing2/frontend/app/page.tsx
git commit -m "feat(marketing): replace feature grid with 6-card SkewCards on cream bg"
```

---

## Task 9: Add ZoomParallax Showcase

**Files:**
- Modify: `apps/marketing2/frontend/app/page.tsx`

- [ ] **Step 1: Add ZoomParallax section after SkewCards**

After the SkewCards section, add:

```tsx
{/* ZoomParallax: Platform showcase */}
<section className="bg-[#050508] relative">
  <div className="absolute top-16 left-16 z-10">
    <p
      className="text-[9px] uppercase tracking-[0.2em] text-gold/60"
      style={{ fontFamily: "var(--font-mono)" }}
    >
      Platform
    </p>
  </div>
  <div className="absolute bottom-16 left-16 z-10 pointer-events-none">
    <h2
      className="text-[clamp(32px,5vw,64px)] font-extrabold leading-[1.05] tracking-[-0.02em] text-[#D8E4F4]"
      style={{ fontFamily: "var(--font-serif)" }}
    >
      Built for the<br />
      <em className="italic" style={{
        background: "linear-gradient(135deg,#A8882C,#C9A84C,#E8C76A)",
        WebkitBackgroundClip: "text",
        WebkitTextFillColor: "transparent",
        backgroundClip: "text",
      }}>regulated</em> enterprise.
    </h2>
  </div>
  <ZoomParallax
    images={[
      { src: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=1280&h=720&fit=crop&auto=format&q=80", alt: "Data analytics dashboard" },
      { src: "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=800&h=600&fit=crop&auto=format&q=80", alt: "Business operations" },
      { src: "https://images.unsplash.com/photo-1518770660439-4636190af475?w=600&h=800&fit=crop&auto=format&q=80", alt: "Technology infrastructure" },
      { src: "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=1280&h=720&fit=crop&auto=format&q=80", alt: "Secure computing" },
      { src: "https://images.unsplash.com/photo-1498050108023-c5249f4df085?w=600&h=800&fit=crop&auto=format&q=80", alt: "Software development" },
      { src: "https://images.unsplash.com/photo-1504868584819-f8e8b4b6d7e3?w=1280&h=720&fit=crop&auto=format&q=80", alt: "Data processing" },
      { src: "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1280&h=720&fit=crop&auto=format&q=80", alt: "Global network" },
    ]}
  />
</section>
```

Add import:

```tsx
import { ZoomParallax } from "@/components/ui/zoom-parallax";
```

- [ ] **Step 2: Build check**

```bash
cd apps/marketing2/frontend && npm run build 2>&1 | grep -E "error|✓"
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add apps/marketing2/frontend/app/page.tsx
git commit -m "feat(marketing): add ZoomParallax platform showcase section"
```

---

## Task 10: Add FlowArt Architecture Narrative

**Files:**
- Modify: `apps/marketing2/frontend/app/page.tsx`

Replace the existing "substrate diagram" / value proposition section (the `architectureLayers` section with the dark background) with the GSAP FlowArt panels.

- [ ] **Step 1: Add FlowArt section**

Find the dark section that renders `architectureLayers` (the section with "A substrate diagram for governed execution") and replace it with:

```tsx
{/* FlowArt: Architecture narrative */}
<FlowArt aria-label="Operious architecture narrative">
  <FlowSection
    aria-label="Boundary — Governed admission"
    style={{ backgroundColor: "#050508", color: "#D8E4F4" }}
  >
    <p
      className="text-[9px] font-bold uppercase tracking-[0.2em] text-gold/60"
      style={{ fontFamily: "var(--font-mono)" }}
    >
      01 — Boundary
    </p>
    <hr className="border-none border-t border-white/10 my-[2vw]" />
    <div>
      <h2
        className="text-[clamp(3.5rem,10vw,12rem)] font-extrabold leading-[0.88] uppercase tracking-tight"
        style={{ fontFamily: "var(--font-serif)" }}
      >
        Admit<br />Only<br />The<br />Governed.
      </h2>
    </div>
    <hr className="border-none border-t border-white/10 my-[2vw]" />
    <p
      className="mt-auto max-w-[50ch] text-[clamp(1rem,2vw,1.5rem)] font-normal leading-relaxed text-[#7A90B4]"
      style={{ fontFamily: "var(--font-inter)" }}
    >
      No request enters the system without passing the admission gate. Language is detected,
      fingerprint computed, and rate limits enforced — before any AI model sees the input.
    </p>
  </FlowSection>

  <FlowSection
    aria-label="Governance — Policy executes"
    style={{ backgroundColor: "#0A0F1C", color: "#D8E4F4" }}
  >
    <p
      className="text-[9px] font-bold uppercase tracking-[0.2em] text-[#00C7FF]/60"
      style={{ fontFamily: "var(--font-mono)" }}
    >
      02 — Governance
    </p>
    <hr className="border-none border-t border-white/8 my-[2vw]" />
    <div>
      <h2
        className="text-[clamp(3.5rem,10vw,12rem)] font-extrabold leading-[0.88] uppercase tracking-tight"
        style={{ fontFamily: "var(--font-serif)" }}
      >
        Policy<br />Executes.<br />Not<br />Suggests.
      </h2>
    </div>
    <hr className="border-none border-t border-white/8 my-[2vw]" />
    <p
      className="mt-auto max-w-[50ch] text-[clamp(1rem,2vw,1.5rem)] font-normal leading-relaxed text-[#7A90B4]"
      style={{ fontFamily: "var(--font-inter)" }}
    >
      Policy chains evaluate every proposed action. Empty chains return DENY. There is no path
      to ALLOW without a passing policy — no matter what the model proposes.
    </p>
  </FlowSection>

  <FlowSection
    aria-label="Execution — Governed actions"
    style={{ backgroundColor: "#F8F5EE", color: "#0A0F1C" }}
  >
    <p
      className="text-[9px] font-bold uppercase tracking-[0.2em] text-gold-dim"
      style={{ fontFamily: "var(--font-mono)" }}
    >
      03 — Execution
    </p>
    <hr className="border-none border-t border-black/15 my-[2vw]" />
    <div>
      <h2
        className="text-[clamp(3.5rem,10vw,12rem)] font-extrabold leading-[0.88] uppercase tracking-tight text-ink-primary"
        style={{ fontFamily: "var(--font-serif)" }}
      >
        Every<br />Action.<br />Permitted<br />First.
      </h2>
    </div>
    <hr className="border-none border-t border-black/15 my-[2vw]" />
    <p
      className="mt-auto max-w-[50ch] text-[clamp(1rem,2vw,1.5rem)] font-normal leading-relaxed text-ink-body"
      style={{ fontFamily: "var(--font-inter)" }}
    >
      Warranty claims, refund requests, replacements — each action is governed, SOP-cited,
      and optionally manager-approved before touching a customer.
    </p>
  </FlowSection>

  <FlowSection
    aria-label="Audit — Permanent record"
    style={{ backgroundColor: "#050508", color: "#D8E4F4" }}
  >
    <p
      className="text-[9px] font-bold uppercase tracking-[0.2em] text-gold/60"
      style={{ fontFamily: "var(--font-mono)" }}
    >
      04 — Audit
    </p>
    <hr className="border-none border-t border-white/10 my-[2vw]" />
    <div>
      <h2
        className="text-[clamp(3.5rem,10vw,12rem)] font-extrabold leading-[0.88] uppercase tracking-tight"
        style={{ fontFamily: "var(--font-serif)" }}
      >
        Every<br />Decision.<br />Permanent<br />Record.
      </h2>
    </div>
    <hr className="border-none border-t border-white/10 my-[2vw]" />
    <p
      className="mt-auto max-w-[50ch] text-[clamp(1rem,2vw,1.5rem)] font-normal leading-relaxed text-[#7A90B4]"
      style={{ fontFamily: "var(--font-inter)" }}
    >
      UUID5 identity. HMAC-SHA256 signatures. Append-only timelines. Replay any operational
      decision at any point in time with cryptographic certainty.
    </p>
  </FlowSection>
</FlowArt>
```

Add imports:

```tsx
import FlowArt, { FlowSection } from "@/components/ui/story-scroll";
```

- [ ] **Step 2: Build check**

```bash
cd apps/marketing2/frontend && npm run build 2>&1 | grep -E "error|✓"
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add apps/marketing2/frontend/app/page.tsx
git commit -m "feat(marketing): add FlowArt GSAP architecture narrative — 4 panels"
```

---

## Task 11: Upgrade Remaining Sections

**Files:**
- Modify: `apps/marketing2/frontend/app/page.tsx`
- Modify: `apps/marketing2/frontend/components/containment-layer.tsx`
- Modify: `apps/marketing2/frontend/components/live-evidence.tsx`

- [ ] **Step 1: Upgrade section headings to Playfair Display**

In `page.tsx`, find every `<h2>` with `style={{ fontFamily: "var(--font-cormorant-sc)" }}` and replace with:

```tsx
style={{ fontFamily: "var(--font-serif)" }}
```

This applies to: Trust section, Insights section, CTA section, the Industries section, and the "Value proposition" section.

- [ ] **Step 2: Upgrade Industries section background to cream**

Find the industries section:

```tsx
// Find this section opening:
<section className="border-y border-border-subtle bg-canvas px-4 py-8 sm:px-8 lg:px-16">
```

Keep the existing structure but ensure background is `bg-[#F8F5EE]` (canvas is already `#F8F5EE` — verify it matches). Apply `font-family: var(--font-inter)` to industry card text:

```tsx
// In each industry Link, update the span:
<span className="text-[12px] font-semibold text-ink-primary" style={{ fontFamily: "var(--font-inter)" }}>
  {industry.title}
</span>
```

- [ ] **Step 3: Add HoverPeek to Insights articles**

In `page.tsx`, find the Insights section that renders `featuredArticles`. Wrap each article title with `HoverPeek`:

```tsx
// Import at top:
import { HoverPeek } from "@/components/ui/link-preview";

// In the insights grid, wrap article titles:
<Link href={article.href} className="group block h-full ...">
  <HoverPeek url={`https://www.operious.com${article.href}`}>
    <h3
      className="text-[24px] font-semibold leading-tight text-ink-primary cursor-pointer hover:text-gold transition-colors"
      style={{ fontFamily: "var(--font-serif)" }}
    >
      {article.title}
    </h3>
  </HoverPeek>
  <p className="mt-3 text-[15px] leading-relaxed text-ink-body" style={{ fontFamily: "var(--font-inter)" }}>
    {article.body}
  </p>
  <span className="mt-6 inline-flex items-center text-[13px] font-medium text-gold">
    Read article
    <ArrowRight className="ml-1.5 h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
  </span>
</Link>
```

- [ ] **Step 4: Upgrade ContainmentLayer hover states**

In `components/containment-layer.tsx`, find the component and add hover state classes. Without seeing the full implementation, search for the container element and add:

```tsx
// Add to the outer div of each ContainmentLayer:
className="... group cursor-default"
// Add to the number text:
className="... group-hover:text-gold transition-colors duration-300"
// Add to any vertical bar/divider if present:
className="... group-hover:bg-gold group-hover:shadow-[0_0_8px_rgba(201,168,76,0.4)] transition-all duration-300"
// Add to the title text:
className="... group-hover:text-[#D8E4F4] transition-colors duration-300"
// Add to the description text:
className="... group-hover:text-[#7A90B4] transition-colors duration-300"
```

- [ ] **Step 5: Upgrade CTA section with magnetic button**

Find the final CTA section. Apply Playfair Display to headline and `MagneticWrapper` to the CTA link:

```tsx
<h2
  className="text-[36px] font-extrabold leading-tight sm:text-[50px]"
  style={{ fontFamily: "var(--font-serif)" }}
>
  See how Operious eliminates the trust gap in enterprise AI operations.
</h2>
<MagneticWrapper>
  <Link href="/company/contact" className="mt-8 inline-flex h-12 ...">
    Request enterprise access
    <ArrowRight className="ml-2 h-4 w-4" />
  </Link>
</MagneticWrapper>
```

- [ ] **Step 6: Final build check**

```bash
cd apps/marketing2/frontend && npm run build 2>&1
```

Expected: 0 TypeScript errors, successful build.

- [ ] **Step 7: Commit**

```bash
git add apps/marketing2/frontend/app/page.tsx apps/marketing2/frontend/components/containment-layer.tsx apps/marketing2/frontend/components/live-evidence.tsx
git commit -m "feat(marketing): upgrade section headings to Playfair, cream bg industries, HoverPeek insights, magnetic CTA"
```

---

## Task 12: Final Marketing Build Verification

- [ ] **Step 1: Clean build**

```bash
cd apps/marketing2/frontend && rm -rf .next && npm run build 2>&1
```

Expected: `✓ Compiled successfully` with 0 TypeScript errors.

- [ ] **Step 2: Check responsive breakpoints compile**

```bash
cd apps/marketing2/frontend && npm run build 2>&1 | grep -E "error TS|Error:"
```

Expected: no output (no errors).

- [ ] **Step 3: Final commit**

```bash
git add -A apps/marketing2/frontend/
git commit -m "feat(marketing): world-class frontend redesign complete — Playfair Display, cream sections, FlowArt, ContainerScroll, SkewCards, ZoomParallax, HoverPeek, TextReveal"
```
