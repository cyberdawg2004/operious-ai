"use client";

import Link from "next/link";
import { Mail } from "lucide-react";
import { KernelSeal } from "./kernel-seal";

const footerColumns = [
  {
    title: "FEATURES",
    links: [
      "Operational Kernel",
      "Governance Substrate",
      "Trace Inspector",
      "Cognition Hub",
      "Channel Boundaries",
      "Topology Configurator",
      "Authority Context System",
      "Replay Engine",
    ],
  },
  {
    title: "SOLUTIONS",
    links: [
      "Hardware Operations",
      "Financial Services",
      "Healthcare Operations",
      "Telecommunications",
      "Logistics & Supply Chain",
      "Public Sector",
      "Custom Domains",
    ],
  },
  {
    title: "RESOURCES",
    links: [
      "Documentation",
      "Engineering Articles",
      "Newsletter",
      "FAQs",
      "Architecture Overview",
      "Security & Compliance",
      "Status Page",
    ],
  },
  {
    title: "POPULAR TOPICS",
    links: [
      "How Governance Substrate Works",
      "Cryptographic Decision Lineage",
      "Tenant Isolation Doctrine",
      "Why Fail-Closed Defaults Matter",
      "Organizational Cognition Patterns",
      "Replay-Safe Execution",
      "Multilingual Operational Boundaries",
    ],
  },
  {
    title: "COMPANY",
    links: ["About", "Careers", "Contact", "Press", "Partners"],
    emails: ["info@operious.com", "ops@operious.com", "career@operious.com"],
  },
];

const bottomLinks = [
  "Terms of Service",
  "Privacy Policy",
  "Security",
  "Accessibility",
];

const socialIcons = [
  { name: "LinkedIn", href: "#" },
  { name: "X", href: "#" },
  { name: "GitHub", href: "#" },
];

export function Footer() {
  return (
    <footer className="bg-[#05080F] pt-16 sm:pt-20 lg:pt-24 pb-6 sm:pb-8 px-4 sm:px-8 lg:px-16">
      <div className="max-w-[1440px] mx-auto">
        {/* Top section - Logo and tagline */}
        <div className="flex items-center gap-3 sm:gap-4">
          <KernelSeal size={40} phase={3} />
          <span
            className="text-[22px] sm:text-[26px] lg:text-[28px] font-semibold text-[#D8E4F4]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Operious
          </span>
        </div>
        <p
          className="mt-3 sm:mt-4 text-[10px] sm:text-[11px] uppercase tracking-[0.18em] text-[#C9A84C]"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          DETERMINISTIC ENTERPRISE OPERATIONS
        </p>

        {/* Five-column grid */}
        <div className="mt-12 sm:mt-14 lg:mt-16 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-8 sm:gap-10 lg:gap-12">
          {footerColumns.map((column) => (
            <div key={column.title}>
              <h4
                className="text-[11px] uppercase tracking-[0.18em] text-[#7A90B4] mb-6"
                style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
              >
                {column.title}
              </h4>
              <ul className="space-y-0">
                {column.links.map((link) => (
                  <li key={link}>
                    <Link
                      href="#"
                      className="text-[14px] text-[#D8E4F4] leading-[2] hover:text-[#C9A84C] transition-colors duration-[160ms]"
                    >
                      {link}
                    </Link>
                  </li>
                ))}
              </ul>
              {column.emails && (
                <div className="mt-6 space-y-2">
                  {column.emails.map((email) => (
                    <a
                      key={email}
                      href={`mailto:${email}`}
                      className="flex items-center gap-2 text-[13px] text-[#7A90B4] hover:text-[#C9A84C] transition-colors duration-[160ms]"
                    >
                      <Mail className="w-3 h-3" />
                      {email}
                    </a>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Bottom strip */}
        <div className="mt-16 sm:mt-20 lg:mt-24 pt-6 sm:pt-8 border-t border-[#1A2744]">
          <div className="flex flex-col lg:flex-row items-center justify-between gap-6">
            {/* Left - Copyright */}
            <p className="text-[12px] sm:text-[13px] text-[#7A90B4] text-center lg:text-left">
              © 2026 Operious AI. All operational guarantees reserved.
            </p>

            {/* Center - Links */}
            <div className="flex flex-wrap items-center justify-center gap-4 sm:gap-6">
              {bottomLinks.map((link) => (
                <Link
                  key={link}
                  href="#"
                  className="text-[12px] sm:text-[13px] text-[#7A90B4] hover:text-[#C9A84C] transition-colors duration-[160ms]"
                >
                  {link}
                </Link>
              ))}
            </div>

            {/* Right - Social icons */}
            <div className="flex items-center gap-3 sm:gap-4">
              {socialIcons.map((social) => (
                <a
                  key={social.name}
                  href={social.href}
                  className="w-8 h-8 rounded-full border border-[#1A2744] flex items-center justify-center text-[#7A90B4] hover:text-[#C9A84C] hover:border-[#C9A84C] transition-colors duration-[160ms]"
                  aria-label={social.name}
                >
                  {social.name === "LinkedIn" && (
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                    </svg>
                  )}
                  {social.name === "X" && (
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
                    </svg>
                  )}
                  {social.name === "GitHub" && (
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                    </svg>
                  )}
                </a>
              ))}
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
