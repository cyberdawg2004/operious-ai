"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Menu, X } from "lucide-react";
import Link from "next/link";
import { Logo } from "./logo";
import { commandCenterUrl, headerGroups, type LinkGroup } from "@/lib/site-links";

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
        className="flex items-center gap-1 text-[14px] font-medium text-ink-primary hover:text-gold transition-colors duration-[160ms]"
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
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="absolute left-1/2 top-[calc(100%+12px)] min-w-[520px] -translate-x-1/2 rounded-lg border border-border-subtle bg-surface/95 p-6 shadow-[var(--shadow-dropdown)] backdrop-blur-[16px]"
            role="menu"
          >
            <div className="grid grid-cols-2 gap-4">
              {group.links.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="group -m-3 block rounded-md p-3 transition-colors duration-[160ms] hover:bg-surface-raised"
                  role="menuitem"
                >
                  <div className="text-[14px] font-semibold text-ink-primary transition-colors duration-[160ms] group-hover:text-gold">
                    {item.label}
                  </div>
                  <div className="mt-0.5 text-[12px] leading-relaxed text-ink-secondary">
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

function MobileNav({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const [expandedSection, setExpandedSection] = useState<string | null>(null);

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-40 bg-black/50 lg:hidden"
            onClick={onClose}
            aria-hidden="true"
          />

          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 32, stiffness: 360 }}
            className="fixed bottom-0 right-0 top-0 z-50 w-full max-w-[400px] overflow-y-auto overscroll-contain bg-surface will-change-transform lg:hidden"
          >
            <div className="p-6">
              <div className="mb-8 flex items-center justify-between">
                <Link href="/" className="flex items-center gap-3" onClick={onClose}>
                  <Logo className="h-9 w-auto text-ink-primary" height={36} tone="light" width={148} />
                </Link>
                <button
                  onClick={onClose}
                  className="flex h-11 w-11 items-center justify-center rounded text-ink-tertiary transition-colors hover:bg-surface-raised hover:text-ink-primary"
                  aria-label="Close menu"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <nav className="space-y-2">
                {headerGroups.map((group) => (
                  <div key={group.label} className="border-b border-border-subtle">
                    <button
                      onClick={() =>
                        setExpandedSection(
                          expandedSection === group.label ? null : group.label
                        )
                      }
                      className="flex w-full items-center justify-between py-4 text-[16px] font-medium text-ink-primary"
                    >
                      {group.label}
                      <ChevronDown
                        className={`h-5 w-5 text-ink-tertiary transition-transform duration-200 ${
                          expandedSection === group.label ? "rotate-180" : ""
                        }`}
                      />
                    </button>
                    <AnimatePresence>
                      {expandedSection === group.label && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          className="overflow-hidden"
                        >
                          <div className="space-y-3 pb-4">
                            {group.links.map((item) => (
                              <Link
                                key={item.href}
                                href={item.href}
                                className="block border-l-2 border-border-subtle py-2 pl-4 transition-colors hover:border-gold"
                                onClick={onClose}
                              >
                                <div className="text-[14px] font-medium text-ink-body">
                                  {item.label}
                                </div>
                                <div className="mt-0.5 text-[12px] text-ink-tertiary">
                                  {item.description}
                                </div>
                              </Link>
                            ))}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                ))}
              </nav>

              <div className="mt-8 space-y-3">
                <a
                  href={commandCenterUrl}
                  target="_blank"
                  rel="noreferrer"
                  onClick={onClose}
                  className="block w-full rounded-md border border-border-defined py-3 text-center text-[15px] font-medium text-ink-primary transition-colors hover:bg-surface-raised"
                >
                  Sign In
                </a>
                <Link
                  href="/company/contact"
                  onClick={onClose}
                  className="block w-full rounded-md bg-ink-primary py-3 text-center text-[15px] font-medium text-white transition-colors hover:bg-ink-body"
                >
                  Request Access
                </Link>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

export function Navigation() {
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);

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
        className="fixed left-0 right-0 top-0 z-50 h-[72px] border-b border-border-subtle bg-canvas/95 backdrop-blur-[16px]"
        role="navigation"
        aria-label="Main navigation"
      >
        <div className="mx-auto flex h-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link href="/" className="flex items-center gap-3">
            <Logo className="h-9 w-auto text-ink-primary" height={36} tone="light" width={148} />
          </Link>

          <div className="hidden items-center gap-8 lg:flex">
            {headerGroups.map((group) => (
              <NavDropdown
                key={group.label}
                group={group}
                isOpen={openDropdown === group.label}
                onToggle={() =>
                  setOpenDropdown((prev) => (prev === group.label ? null : group.label))
                }
              />
            ))}
          </div>

          <div className="hidden items-center gap-4 lg:flex">
            <a
              href={commandCenterUrl}
              target="_blank"
              rel="noreferrer"
              className="text-[14px] text-ink-primary transition-colors duration-[160ms] hover:text-gold"
            >
              Sign In
            </a>
            <Link
              href="/company/contact"
              className="rounded bg-ink-primary px-4 py-2 text-[14px] font-medium text-white transition-colors duration-[160ms] hover:bg-ink-body"
            >
              Request Access
            </Link>
          </div>

          <button
            onClick={() => setMobileMenuOpen(true)}
            className="flex h-11 w-11 items-center justify-center rounded text-ink-primary transition-colors hover:bg-surface-raised hover:text-gold lg:hidden"
            aria-label="Open menu"
            aria-expanded={mobileMenuOpen}
          >
            <Menu className="h-6 w-6" />
          </button>
        </div>
      </motion.nav>

      <MobileNav isOpen={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />
    </>
  );
}
