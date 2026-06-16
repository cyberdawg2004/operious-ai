"use client";

import { useState, useRef, useEffect } from "react";
import { motion, useScroll, useTransform, AnimatePresence } from "framer-motion";
import { ChevronDown, Menu, X } from "lucide-react";
import Link from "next/link";

function KernelSeal({ className }: { className?: string }) {
  return (
    <svg
      width="32"
      height="32"
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path d="M16 2L28.124 9V23L16 30L3.876 23V9L16 2Z" stroke="#C9A84C" strokeWidth="1.5" fill="none" />
      <path d="M16 6L24.66 11V21L16 26L7.34 21V11L16 6Z" stroke="#A8882C" strokeWidth="1" fill="none" />
      <path d="M16 10L20.5 17H11.5L16 10Z" fill="#C9A84C" />
      <path d="M13 14L17.5 21H8.5L13 14Z" fill="#A8882C" fillOpacity="0.6" />
      <path d="M19 14L23.5 21H14.5L19 14Z" fill="#A8882C" fillOpacity="0.6" />
      <circle cx="16" cy="16" r="1.5" fill="#A8882C" />
    </svg>
  );
}

const navigationItems = {
  Solutions: {
    columns: 2,
    items: [
      { title: "Hardware & Consumer Electronics", description: "End-to-end procurement governance for complex supply chains" },
      { title: "Financial Services & Insurance", description: "Regulatory-compliant execution infrastructure" },
      { title: "Healthcare Operations", description: "HIPAA-aligned multi-agent coordination" },
      { title: "Telecommunications", description: "Network-scale operational determinism" },
      { title: "Logistics & Supply Chain", description: "Real-time visibility with audit certainty" },
      { title: "Public Sector Operations", description: "FedRAMP-ready governance frameworks" },
    ],
  },
  Products: {
    columns: 2,
    items: [
      { title: "Operational Kernel", description: "Deterministic execution engine for enterprise workflows" },
      { title: "Command Center", description: "Unified control plane for multi-agent orchestration" },
      { title: "Governance Substrate", description: "Policy enforcement and compliance automation" },
      { title: "Trace Inspector", description: "Complete execution lineage and forensic replay" },
      { title: "Cognition Hub", description: "Centralized model routing and capability management" },
      { title: "Channel Boundaries", description: "Secure inter-agent communication protocols" },
    ],
  },
  Platform: {
    columns: 2,
    items: [
      { title: "Architecture Overview", description: "Core system design and execution model" },
      { title: "Substrate Model", description: "Foundation layer for deterministic operations" },
      { title: "Governance Doctrine", description: "Policy framework and compliance primitives" },
      { title: "Replay & Audit", description: "Complete execution history with forensic capability" },
      { title: "Security & Compliance", description: "SOC 2, HIPAA, FedRAMP certification details" },
      { title: "Integrations", description: "Enterprise connectors and API specifications" },
    ],
  },
  Resources: {
    columns: 2,
    items: [
      { title: "Documentation", description: "Technical guides and API reference" },
      { title: "Articles", description: "Deep dives on deterministic AI systems" },
      { title: "Newsletter", description: "Monthly insights on enterprise AI governance" },
      { title: "FAQs", description: "Common questions about Operious" },
      { title: "Engineering Blog", description: "Technical posts from our engineering team" },
      { title: "Case Studies", description: "Real-world implementation stories" },
    ],
  },
};

type NavKey = keyof typeof navigationItems;

function NavDropdown({ label, isOpen, onToggle }: { label: NavKey; isOpen: boolean; onToggle: () => void }) {
  const data = navigationItems[label];

  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className="flex items-center gap-1 text-[14px] font-medium text-[#D8E4F4] hover:text-[#C9A84C] transition-colors duration-[160ms]"
        aria-expanded={isOpen}
        aria-haspopup="true"
      >
        {label}
        <ChevronDown className={`w-[14px] h-[14px] transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`} />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="absolute top-[calc(100%+12px)] left-1/2 -translate-x-1/2 min-w-[480px] rounded-[18px] border border-[#24324a] bg-[rgba(6,10,18,0.95)] p-6 shadow-[var(--shadow-dropdown)] backdrop-blur"
            role="menu"
          >
            <div className={`grid gap-4 ${data.columns === 2 ? "grid-cols-2" : "grid-cols-1"}`}>
              {data.items.map((item) => (
                <Link key={item.title} href="#" className="group block rounded-[12px] p-3 -m-3 transition-colors duration-[160ms] hover:bg-[#10182b]" role="menuitem">
                  <div className="text-[14px] font-semibold text-[#D8E4F4] transition-colors duration-[160ms] group-hover:text-[#C9A84C]">{item.title}</div>
                  <div className="mt-0.5 text-[12px] leading-relaxed text-[#7A90B4]">{item.description}</div>
                </Link>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function MobileNav({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const [expandedSection, setExpandedSection] = useState<NavKey | null>(null);

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={onClose} aria-hidden="true" />
          <motion.div initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", damping: 30, stiffness: 300 }} className="fixed inset-y-0 right-0 z-50 w-full max-w-[400px] overflow-y-auto border-l border-[#24324a] bg-[#05080F] lg:hidden">
            <div className="p-6">
              <div className="mb-8 flex items-center justify-between">
                <Link href="/" className="flex items-center gap-3" onClick={onClose}>
                  <KernelSeal />
                  <span className="text-[20px] font-semibold tracking-[-0.01em] text-[#D8E4F4]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>
                    Operious
                  </span>
                </Link>
                <button onClick={onClose} className="-m-2 p-2 text-[#7A90B4] transition-colors hover:text-[#C9A84C]" aria-label="Close menu">
                  <X className="h-6 w-6" />
                </button>
              </div>

              <nav className="space-y-2">
                {(Object.keys(navigationItems) as NavKey[]).map((key) => (
                  <div key={key} className="border-b border-[#24324a]">
                    <button onClick={() => setExpandedSection(expandedSection === key ? null : key)} className="flex w-full items-center justify-between py-4 text-[16px] font-medium text-[#D8E4F4]">
                      {key}
                      <ChevronDown className={`h-5 w-5 text-[#7A90B4] transition-transform duration-200 ${expandedSection === key ? "rotate-180" : ""}`} />
                    </button>
                    <AnimatePresence>
                      {expandedSection === key && (
                        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden">
                          <div className="space-y-3 pb-4">
                            {navigationItems[key].items.map((item) => (
                              <Link key={item.title} href="#" className="block border-l-2 border-[#24324a] py-2 pl-4 transition-colors hover:border-[#C9A84C]" onClick={onClose}>
                                <div className="text-[14px] font-medium text-[#D8E4F4]">{item.title}</div>
                                <div className="mt-0.5 text-[12px] text-[#7A90B4]">{item.description}</div>
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
                <Link href="/signin" onClick={onClose} className="block w-full rounded-[12px] border border-[#24324a] px-4 py-3 text-center text-[15px] font-medium text-[#D8E4F4] transition-colors hover:bg-[#10182b]">Sign In</Link>
                <Link href="/register" onClick={onClose} className="block w-full rounded-[12px] border border-[#C9A84C] px-4 py-3 text-center text-[15px] font-medium text-[#D8E4F4] transition-colors hover:bg-[#C9A84C]/10">Register</Link>
                <Link href="/contact" onClick={onClose} className="block w-full rounded-[12px] bg-[#C9A84C] px-4 py-3 text-center text-[15px] font-medium text-[#05080F] transition-colors hover:bg-[#D4B85A]">Contact Us</Link>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

export function Navigation() {
  const [openDropdown, setOpenDropdown] = useState<NavKey | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { scrollY } = useScroll();
  const navRef = useRef<HTMLElement>(null);

  const backgroundColor = useTransform(scrollY, [0, 80], ["rgba(5, 8, 15, 0)", "rgba(5, 8, 15, 0.9)"]);
  const borderOpacity = useTransform(scrollY, [0, 80], [0, 1]);
  const backdropBlur = useTransform(scrollY, [0, 80], ["blur(0px)", "blur(18px)"]);

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
    if (mobileMenuOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileMenuOpen]);

  const handleToggle = (key: NavKey) => {
    setOpenDropdown((prev) => (prev === key ? null : key));
  };

  return (
    <>
      <motion.nav ref={navRef} className="fixed left-0 right-0 top-0 z-50 h-[72px]" style={{ backgroundColor, backdropFilter: backdropBlur }} role="navigation" aria-label="Main navigation">
        <motion.div className="absolute inset-x-0 bottom-0 h-px bg-[#24324a]" style={{ opacity: borderOpacity }} />

        <div className="mx-auto flex h-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link href="/" className="flex items-center gap-3">
            <KernelSeal />
            <span className="text-[18px] font-semibold tracking-[-0.01em] text-[#D8E4F4] sm:text-[20px]" style={{ fontFamily: "var(--font-cormorant-sc)" }}>
              Operious
            </span>
          </Link>

          <div className="hidden items-center gap-8 lg:flex">
            {(Object.keys(navigationItems) as NavKey[]).map((key) => (
              <NavDropdown key={key} label={key} isOpen={openDropdown === key} onToggle={() => handleToggle(key)} />
            ))}
          </div>

          <div className="hidden items-center gap-4 lg:flex">
            <Link href="/signin" className="text-[14px] text-[#D8E4F4] transition-colors duration-[160ms] hover:text-[#C9A84C]">Sign In</Link>
            <Link href="/register" className="rounded-[10px] border border-[#C9A84C] px-4 py-2 text-[14px] font-medium text-[#D8E4F4] transition-colors duration-[160ms] hover:bg-[#C9A84C]/10">Register</Link>
            <Link href="/contact" className="rounded-[10px] bg-[#C9A84C] px-4 py-2 text-[14px] font-medium text-[#05080F] transition-colors duration-[160ms] hover:bg-[#D4B85A]">Contact Us</Link>
          </div>

          <button onClick={() => setMobileMenuOpen(true)} className="-m-2 p-2 text-[#D8E4F4] transition-colors hover:text-[#C9A84C] lg:hidden" aria-label="Open menu" aria-expanded={mobileMenuOpen}>
            <Menu className="h-6 w-6" />
          </button>
        </div>
      </motion.nav>

      <MobileNav isOpen={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />
    </>
  );
}
