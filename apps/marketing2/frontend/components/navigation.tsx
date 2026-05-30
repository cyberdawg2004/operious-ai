"use client";

import { useEffect, useRef, useState } from "react";
import {
  AnimatePresence,
  motion,
  useScroll,
  useSpring,
} from "framer-motion";
import { ArrowUpRight, ChevronDown, Menu, X } from "lucide-react";
import Link from "next/link";
import { OperioussLogo } from "./logo";
import { commandCenterUrl, headerGroups, type LinkGroup } from "@/lib/site-links";
import { cn } from "@/lib/utils";

function NavDropdown({
  group,
  isOpen,
  onToggle,
}: {
  group: LinkGroup;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className="flex items-center gap-1 text-[14px] font-medium text-[#D8E4F4]/85 transition-colors duration-200 hover:text-[#C9A84C]"
        aria-expanded={isOpen}
        aria-haspopup="true"
      >
        {group.label}
        <ChevronDown
          className={`h-[14px] w-[14px] transition-transform duration-200 ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="absolute left-0 top-[calc(100%+14px)] min-w-[520px] rounded-lg border border-white/10 bg-black/80 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.6)] backdrop-blur-xl"
            role="menu"
          >
            <div className="grid grid-cols-2 gap-4">
              {group.links.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="group -m-3 block rounded-md p-3 transition-colors duration-200 hover:bg-white/[0.04]"
                  role="menuitem"
                >
                  <div className="relative text-[14px] font-semibold text-[#F2F0EA] transition-colors duration-200 group-hover:text-[#C9A84C] after:absolute after:bottom-0 after:left-0 after:h-px after:w-0 after:bg-[var(--gold)] after:transition-all after:duration-300 group-hover:after:w-full">
                    {item.label}
                  </div>
                  <div className="mt-0.5 text-[12px] leading-relaxed text-[#9FB0CA]">
                    {item.description}
                  </div>
                </Link>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/**
 * Mobile menu: grouped overlay (Zendesk / ServiceNow style).
 * No accordion hairlines — instead, section headers + soft grid of links.
 */
function MobileNav({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm md:hidden"
            onClick={onClose}
            aria-hidden="true"
          />

          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 34, stiffness: 360 }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[440px] flex-col overflow-y-auto overscroll-contain border-l border-white/10 bg-gradient-to-b from-[#05080F] via-[#070B16] to-[#05080F] will-change-transform md:hidden"
            role="dialog"
            aria-modal="true"
            aria-label="Site navigation"
          >
            <header className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-white/[0.05] bg-[#05080F]/85 px-6 py-5 backdrop-blur-xl">
              <Link href="/" onClick={onClose} aria-label="Operious home">
                <OperioussLogo size={26} showWordmark tone="dark" />
              </Link>
              <button
                onClick={onClose}
                className="flex h-10 w-10 items-center justify-center rounded-full border border-white/10 text-[#D8E4F4]/85 transition-colors duration-200 hover:border-[#C9A84C]/40 hover:bg-white/[0.04] hover:text-[#C9A84C]"
                aria-label="Close menu"
              >
                <X className="h-4 w-4" strokeWidth={1.8} />
              </button>
            </header>

            <nav className="flex flex-1 flex-col gap-8 px-6 py-8">
              {headerGroups.map((group) => (
                <section key={group.label}>
                  <h3
                    className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#C9A84C]"
                    style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
                  >
                    {group.label}
                  </h3>
                  <ul className="mt-3 grid gap-1.5">
                    {group.links.map((item) => (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          onClick={onClose}
                          className="group flex items-start gap-3 rounded-lg px-3 py-2.5 transition-all duration-200 hover:bg-white/[0.04]"
                        >
                          <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[#2A5CAA] transition-all duration-200 group-hover:scale-150 group-hover:bg-[#C9A84C]" />
                          <span className="flex flex-1 flex-col">
                            <span className="text-[15px] font-medium text-[#F2F0EA] transition-colors duration-200 group-hover:text-[#C9A84C]">
                              {item.label}
                            </span>
                            <span className="mt-0.5 text-[12px] leading-snug text-[#7A90B4]">
                              {item.description}
                            </span>
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </nav>

            <footer className="sticky bottom-0 z-10 grid gap-2 border-t border-white/[0.05] bg-[#05080F]/90 px-6 py-5 backdrop-blur-xl">
              <a
                href={commandCenterUrl}
                target="_blank"
                rel="noreferrer"
                onClick={onClose}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-md border border-white/10 px-4 text-[14px] font-medium text-[#D8E4F4] transition-all duration-200 hover:border-white/20 hover:bg-white/[0.04]"
              >
                Sign In
                <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={1.8} />
              </a>
              <Link
                href="/company/contact"
                onClick={onClose}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-[#C9A84C] px-4 text-[14px] font-semibold text-[#05080F] shadow-[0_10px_28px_rgba(201,168,76,0.30)] transition-all duration-200 hover:bg-[#D4B85A] hover:shadow-[0_16px_40px_rgba(201,168,76,0.46)]"
              >
                Request Access
              </Link>
            </footer>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

export function Navigation() {
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const navRef = useRef<HTMLElement>(null);

  // Page-scroll progress bar baked into the navbar.
  const { scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, {
    stiffness: 220,
    damping: 30,
    mass: 0.3,
  });

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(event.target as Node)) {
        setOpenDropdown(null);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 60);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    document.body.style.overflow = mobileMenuOpen ? "hidden" : "";
    document.documentElement.style.overflow = mobileMenuOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
      document.documentElement.style.overflow = "";
    };
  }, [mobileMenuOpen]);

  return (
    <>
      <motion.nav
        ref={navRef}
        initial={{ y: -24, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className={cn(
          "fixed inset-x-0 top-0 z-[60] border-b transition-colors duration-300",
          scrolled
            ? "bg-[rgba(5,5,8,0.92)] backdrop-blur-xl border-white/[0.05]"
            : "border-white/[0.06] bg-black/45 backdrop-blur-md"
        )}
        role="navigation"
        aria-label="Main navigation"
      >
        <div className="mx-auto flex h-[68px] max-w-7xl items-center justify-between gap-6 px-4 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-8">
            <Link
              href="/"
              aria-label="Operious home"
              className="shrink-0 transition-opacity duration-200 hover:opacity-90"
            >
              <OperioussLogo size={28} showWordmark tone="dark" />
            </Link>
            <div
              className="hidden items-center gap-7 md:flex"
              style={{ fontFamily: "var(--font-inter, var(--type-geometric))" }}
            >
              {headerGroups.map((group) => (
                <NavDropdown
                  key={group.label}
                  group={group}
                  isOpen={openDropdown === group.label}
                  onToggle={() =>
                    setOpenDropdown((prev) =>
                      prev === group.label ? null : group.label
                    )
                  }
                />
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <a
              href={commandCenterUrl}
              target="_blank"
              rel="noreferrer"
              className="hidden text-[14px] font-medium text-[#D8E4F4]/80 transition-colors duration-200 hover:text-[#C9A84C] md:inline-flex"
            >
              Sign In
            </a>
            <Link
              href="/company/contact"
              className="group hidden items-center gap-2 rounded-md bg-[#C9A84C] px-4 py-2 text-[13px] font-semibold text-[#05080F] shadow-[0_6px_18px_rgba(201,168,76,0.25)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-[#D4B85A] hover:shadow-[0_10px_28px_rgba(201,168,76,0.45)] md:inline-flex"
            >
              Request Access
            </Link>

            <button
              onClick={() => setMobileMenuOpen(true)}
              className="flex h-11 w-11 items-center justify-center rounded text-[#D8E4F4] transition-colors duration-200 hover:bg-white/[0.05] hover:text-[#C9A84C] md:hidden"
              aria-label="Open menu"
              aria-expanded={mobileMenuOpen}
            >
              <Menu className="h-6 w-6" />
            </button>
          </div>
        </div>

        {/* Scroll progress strip — kinetic feedback as the user scrolls. */}
        <motion.div
          aria-hidden="true"
          className="absolute inset-x-0 bottom-0 h-px origin-left bg-gradient-to-r from-[#C9A84C] via-[#D4B85A] to-[#2A5CAA]"
          style={{ scaleX: progress }}
        />
      </motion.nav>

      <MobileNav isOpen={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />
    </>
  );
}
