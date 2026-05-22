"use client";

import { useState, useRef, useEffect } from "react";
import { motion, useScroll, useTransform, AnimatePresence } from "framer-motion";
import { ChevronDown, Menu, X } from "lucide-react";
import Link from "next/link";

// KernelSeal Logo Component - Hexagonal seal with geometric glyph
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
      {/* Outer hexagonal ring */}
      <path
        d="M16 2L28.124 9V23L16 30L3.876 23V9L16 2Z"
        stroke="#0A0F1C"
        strokeWidth="1.5"
        fill="none"
      />
      {/* Inner hexagonal ring */}
      <path
        d="M16 6L24.66 11V21L16 26L7.34 21V11L16 6Z"
        stroke="#A8882C"
        strokeWidth="1"
        fill="none"
      />
      {/* Central geometric kernel glyph - three interlocking triangles */}
      <path
        d="M16 10L20.5 17H11.5L16 10Z"
        fill="#0A0F1C"
      />
      <path
        d="M13 14L17.5 21H8.5L13 14Z"
        fill="#A8882C"
        fillOpacity="0.6"
      />
      <path
        d="M19 14L23.5 21H14.5L19 14Z"
        fill="#A8882C"
        fillOpacity="0.6"
      />
      {/* Central node */}
      <circle cx="16" cy="16" r="1.5" fill="#A8882C" />
    </svg>
  );
}

// Navigation dropdown data
const navigationItems = {
  Solutions: {
    columns: 2,
    items: [
      {
        title: "Hardware & Consumer Electronics",
        description: "End-to-end procurement governance for complex supply chains",
      },
      {
        title: "Financial Services & Insurance",
        description: "Regulatory-compliant execution infrastructure",
      },
      {
        title: "Healthcare Operations",
        description: "HIPAA-aligned multi-agent coordination",
      },
      {
        title: "Telecommunications",
        description: "Network-scale operational determinism",
      },
      {
        title: "Logistics & Supply Chain",
        description: "Real-time visibility with audit certainty",
      },
      {
        title: "Public Sector Operations",
        description: "FedRAMP-ready governance frameworks",
      },
    ],
  },
  Products: {
    columns: 2,
    items: [
      {
        title: "Operational Kernel",
        description: "Deterministic execution engine for enterprise workflows",
      },
      {
        title: "Command Center",
        description: "Unified control plane for multi-agent orchestration",
      },
      {
        title: "Governance Substrate",
        description: "Policy enforcement and compliance automation",
      },
      {
        title: "Trace Inspector",
        description: "Complete execution lineage and forensic replay",
      },
      {
        title: "Cognition Hub",
        description: "Centralized model routing and capability management",
      },
      {
        title: "Channel Boundaries",
        description: "Secure inter-agent communication protocols",
      },
    ],
  },
  Platform: {
    columns: 2,
    items: [
      {
        title: "Architecture Overview",
        description: "Core system design and execution model",
      },
      {
        title: "Substrate Model",
        description: "Foundation layer for deterministic operations",
      },
      {
        title: "Governance Doctrine",
        description: "Policy framework and compliance primitives",
      },
      {
        title: "Replay & Audit",
        description: "Complete execution history with forensic capability",
      },
      {
        title: "Security & Compliance",
        description: "SOC 2, HIPAA, FedRAMP certification details",
      },
      {
        title: "Integrations",
        description: "Enterprise connectors and API specifications",
      },
    ],
  },
  Resources: {
    columns: 2,
    items: [
      {
        title: "Documentation",
        description: "Technical guides and API reference",
      },
      {
        title: "Articles",
        description: "Deep dives on deterministic AI systems",
      },
      {
        title: "Newsletter",
        description: "Monthly insights on enterprise AI governance",
      },
      {
        title: "FAQs",
        description: "Common questions about Operious",
      },
      {
        title: "Engineering Blog",
        description: "Technical posts from our engineering team",
      },
      {
        title: "Case Studies",
        description: "Real-world implementation stories",
      },
    ],
  },
};

type NavKey = keyof typeof navigationItems;

function NavDropdown({
  label,
  isOpen,
  onToggle,
}: {
  label: NavKey;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const dropdownRef = useRef<HTMLDivElement>(null);
  const data = navigationItems[label];

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={onToggle}
        className="flex items-center gap-1 text-[14px] font-medium text-ink-primary hover:text-gold transition-colors duration-[160ms]"
        aria-expanded={isOpen}
        aria-haspopup="true"
      >
        {label}
        <ChevronDown
          className={`w-[14px] h-[14px] transition-transform duration-200 ${
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
            className="absolute top-[calc(100%+12px)] left-1/2 -translate-x-1/2 min-w-[480px] bg-surface/95 backdrop-blur-[16px] border border-border-subtle rounded-lg p-6 shadow-[var(--shadow-dropdown)]"
            role="menu"
          >
            <div
              className={`grid gap-4 ${
                data.columns === 2 ? "grid-cols-2" : "grid-cols-1"
              }`}
            >
              {data.items.map((item) => (
                <Link
                  key={item.title}
                  href="#"
                  className="group block p-3 -m-3 rounded-md hover:bg-surface-raised transition-colors duration-[160ms]"
                  role="menuitem"
                >
                  <div className="text-[14px] font-semibold text-ink-primary group-hover:text-gold transition-colors duration-[160ms]">
                    {item.title}
                  </div>
                  <div className="text-[12px] text-ink-secondary mt-0.5 leading-relaxed">
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

// Mobile Navigation Menu
function MobileNav({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const [expandedSection, setExpandedSection] = useState<NavKey | null>(null);

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 bg-black/50 z-40 lg:hidden"
            onClick={onClose}
            aria-hidden="true"
          />

          {/* Panel */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className="fixed top-0 right-0 bottom-0 w-full max-w-[400px] bg-surface z-50 lg:hidden overflow-y-auto"
          >
            <div className="p-6">
              {/* Header */}
              <div className="flex items-center justify-between mb-8">
                <Link href="/" className="flex items-center gap-3" onClick={onClose}>
                  <KernelSeal />
                  <span
                    className="text-[20px] font-semibold tracking-[-0.01em] text-ink-primary"
                    style={{ fontFamily: "var(--font-cormorant-sc)" }}
                  >
                    Operious
                  </span>
                </Link>
                <button
                  onClick={onClose}
                  className="p-2 -m-2 text-ink-tertiary hover:text-ink-primary transition-colors"
                  aria-label="Close menu"
                >
                  <X className="w-6 h-6" />
                </button>
              </div>

              {/* Navigation Sections */}
              <nav className="space-y-2">
                {(Object.keys(navigationItems) as NavKey[]).map((key) => (
                  <div key={key} className="border-b border-border-subtle">
                    <button
                      onClick={() =>
                        setExpandedSection(expandedSection === key ? null : key)
                      }
                      className="w-full flex items-center justify-between py-4 text-[16px] font-medium text-ink-primary"
                    >
                      {key}
                      <ChevronDown
                        className={`w-5 h-5 text-ink-tertiary transition-transform duration-200 ${
                          expandedSection === key ? "rotate-180" : ""
                        }`}
                      />
                    </button>
                    <AnimatePresence>
                      {expandedSection === key && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          className="overflow-hidden"
                        >
                          <div className="pb-4 space-y-3">
                            {navigationItems[key].items.map((item) => (
                              <Link
                                key={item.title}
                                href="#"
                                className="block py-2 pl-4 border-l-2 border-border-subtle hover:border-gold transition-colors"
                                onClick={onClose}
                              >
                                <div className="text-[14px] font-medium text-ink-body">
                                  {item.title}
                                </div>
                                <div className="text-[12px] text-ink-tertiary mt-0.5">
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

              {/* Actions */}
              <div className="mt-8 space-y-3">
                <Link
                  href="/signin"
                  onClick={onClose}
                  className="block w-full text-center py-3 text-[15px] font-medium text-ink-primary border border-border-defined rounded-md hover:bg-surface-raised transition-colors"
                >
                  Sign In
                </Link>
                <Link
                  href="/register"
                  onClick={onClose}
                  className="block w-full text-center py-3 text-[15px] font-medium text-ink-primary border border-gold rounded-md hover:bg-gold/5 transition-colors"
                >
                  Register
                </Link>
                <Link
                  href="/contact"
                  onClick={onClose}
                  className="block w-full text-center py-3 text-[15px] font-medium text-white bg-ink-primary rounded-md hover:bg-ink-body transition-colors"
                >
                  Contact Us
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
  const [openDropdown, setOpenDropdown] = useState<NavKey | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { scrollY } = useScroll();
  const navRef = useRef<HTMLElement>(null);

  // Transform background based on scroll position
  const backgroundColor = useTransform(
    scrollY,
    [0, 80],
    ["rgba(248, 245, 238, 0)", "rgba(248, 245, 238, 0.95)"]
  );

  const borderOpacity = useTransform(scrollY, [0, 80], [0, 1]);
  const backdropBlur = useTransform(scrollY, [0, 80], ["blur(0px)", "blur(16px)"]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(event.target as Node)) {
        setOpenDropdown(null);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Prevent scroll when mobile menu is open
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
      <motion.nav
        ref={navRef}
        className="fixed top-0 left-0 right-0 z-50 h-[72px]"
        style={{
          backgroundColor,
          backdropFilter: backdropBlur,
        }}
        role="navigation"
        aria-label="Main navigation"
      >
        <motion.div
          className="absolute inset-x-0 bottom-0 h-px bg-border-subtle"
          style={{ opacity: borderOpacity }}
        />

        <div className="max-w-7xl mx-auto h-full px-4 sm:px-6 lg:px-8 flex items-center justify-between">
          {/* Left side - Logo and Wordmark */}
          <Link href="/" className="flex items-center gap-3">
            <KernelSeal />
            <span
              className="text-[18px] sm:text-[20px] font-semibold tracking-[-0.01em] text-ink-primary"
              style={{ fontFamily: "var(--font-cormorant-sc)" }}
            >
              Operious
            </span>
          </Link>

          {/* Center - Navigation Items (Desktop only) */}
          <div className="hidden lg:flex items-center gap-8">
            {(Object.keys(navigationItems) as NavKey[]).map((key) => (
              <NavDropdown
                key={key}
                label={key}
                isOpen={openDropdown === key}
                onToggle={() => handleToggle(key)}
              />
            ))}
          </div>

          {/* Right side - Actions (Desktop) */}
          <div className="hidden lg:flex items-center gap-4">
            <Link
              href="/signin"
              className="text-[14px] text-ink-primary hover:text-gold transition-colors duration-[160ms]"
            >
              Sign In
            </Link>
            <Link
              href="/register"
              className="text-[14px] font-medium text-ink-primary border border-gold px-4 py-2 rounded hover:bg-gold/5 transition-colors duration-[160ms]"
            >
              Register
            </Link>
            <Link
              href="/contact"
              className="text-[14px] font-medium text-white bg-ink-primary px-4 py-2 rounded hover:bg-ink-body transition-colors duration-[160ms]"
            >
              Contact Us
            </Link>
          </div>

          {/* Mobile menu button */}
          <button
            onClick={() => setMobileMenuOpen(true)}
            className="lg:hidden p-2 -m-2 text-ink-primary hover:text-gold transition-colors"
            aria-label="Open menu"
            aria-expanded={mobileMenuOpen}
          >
            <Menu className="w-6 h-6" />
          </button>
        </div>
      </motion.nav>

      {/* Mobile Navigation */}
      <MobileNav isOpen={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />
    </>
  );
}
