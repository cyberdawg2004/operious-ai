"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Menu, X } from "lucide-react";
import Link from "next/link";
import { OperioussLogo } from "./logo";
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
                  <div className="text-[14px] font-semibold text-[#F2F0EA] transition-colors duration-200 group-hover:text-[#C9A84C]">
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
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
            onClick={onClose}
            aria-hidden="true"
          />

          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 32, stiffness: 360 }}
            className="fixed bottom-0 right-0 top-0 z-50 w-full max-w-[400px] overflow-y-auto overscroll-contain border-l border-white/10 bg-[#05080F] will-change-transform md:hidden"
          >
            <div className="p-6">
              <div className="mb-8 flex items-center justify-between">
                <Link href="/" className="flex items-center gap-3" onClick={onClose}>
                  <OperioussLogo size={28} showWordmark={true} />
                </Link>
                <button
                  onClick={onClose}
                  className="flex h-11 w-11 items-center justify-center rounded text-[#9FB0CA] transition-colors hover:bg-white/[0.05] hover:text-white"
                  aria-label="Close menu"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <nav className="space-y-2">
                {headerGroups.map((group) => (
                  <div key={group.label} className="border-b border-white/10">
                    <button
                      onClick={() =>
                        setExpandedSection(
                          expandedSection === group.label ? null : group.label
                        )
                      }
                      className="flex w-full items-center justify-between py-4 text-[16px] font-medium text-[#F2F0EA]"
                    >
                      {group.label}
                      <ChevronDown
                        className={`h-5 w-5 text-[#7A90B4] transition-transform duration-200 ${
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
                                className="block border-l-2 border-white/10 py-2 pl-4 transition-colors hover:border-[#C9A84C]"
                                onClick={onClose}
                              >
                                <div className="text-[14px] font-medium text-[#D8E4F4]">
                                  {item.label}
                                </div>
                                <div className="mt-0.5 text-[12px] text-[#7A90B4]">
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
                  className="block w-full rounded-md border border-white/10 py-3 text-center text-[15px] font-medium text-[#D8E4F4] transition-colors hover:bg-white/[0.05]"
                >
                  Sign In
                </a>
                <Link
                  href="/company/contact"
                  onClick={onClose}
                  className="block w-full rounded-md bg-[#C9A84C] py-3 text-center text-[15px] font-semibold text-[#05080F] transition-colors hover:bg-[#D4B85A]"
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
        initial={{ y: -24, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className="fixed inset-x-0 top-0 z-[60] border-b border-white/10 bg-black/50 backdrop-blur-md"
        role="navigation"
        aria-label="Main navigation"
      >
        <div className="mx-auto flex h-[68px] max-w-7xl items-center justify-between gap-6 px-4 sm:px-6 lg:px-8">
          {/* Left: Logo + (desktop) primary nav */}
          <div className="flex min-w-0 items-center gap-8">
            <Link
              href="/"
              aria-label="Operious home"
              className="shrink-0 transition-opacity duration-200 hover:opacity-90"
            >
              <OperioussLogo size={28} showWordmark={true} />
            </Link>
            <div className="hidden items-center gap-7 md:flex">
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

          {/* Right: auth + CTA + mobile toggle */}
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
      </motion.nav>

      <MobileNav isOpen={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />
    </>
  );
}
