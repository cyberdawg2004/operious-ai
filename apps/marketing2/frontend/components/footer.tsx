import Link from "next/link";
import { Mail } from "lucide-react";
import { KernelSeal } from "./kernel-seal";
import { footerGroups } from "@/lib/site-links";

export function Footer() {
  const legalLinks = footerGroups.find((group) => group.label === "Legal")?.links ?? [];

  return (
    <footer className="bg-[#05080F] px-4 pb-6 pt-16 sm:px-8 sm:pb-8 sm:pt-20 lg:px-16 lg:pt-24">
      <div className="mx-auto max-w-[1440px]">
        <div className="flex items-center gap-3 sm:gap-4">
          <KernelSeal size={40} phase={3} />
          <span
            className="text-[22px] font-semibold text-[#D8E4F4] sm:text-[26px] lg:text-[28px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Operious
          </span>
        </div>
        <p
          className="mt-4 text-[10px] uppercase tracking-[0.18em] text-[#C9A84C] sm:text-[11px]"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          Governed execution infrastructure
        </p>

        <div className="mt-12 grid grid-cols-2 gap-8 sm:mt-14 sm:grid-cols-3 sm:gap-10 lg:mt-16 lg:grid-cols-6 lg:gap-12">
          {footerGroups.map((column) => (
            <div key={column.label}>
              <h4
                className="mb-6 text-[11px] uppercase tracking-[0.18em] text-[#7A90B4]"
                style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
              >
                {column.label}
              </h4>
              <ul>
                {column.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-[14px] leading-[2] text-[#D8E4F4] transition-colors duration-[160ms] hover:text-[#C9A84C]"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-10 flex flex-col gap-3 sm:flex-row sm:items-center">
          <a
            href="mailto:enterprise@operious.ai"
            className="flex items-center gap-2 text-[13px] text-[#7A90B4] transition-colors duration-[160ms] hover:text-[#C9A84C]"
          >
            <Mail className="h-3 w-3" />
            enterprise@operious.ai
          </a>
          <a
            href="mailto:security@operious.ai"
            className="flex items-center gap-2 text-[13px] text-[#7A90B4] transition-colors duration-[160ms] hover:text-[#C9A84C]"
          >
            <Mail className="h-3 w-3" />
            security@operious.ai
          </a>
        </div>

        <div className="mt-16 border-t border-[#1A2744] pt-6 sm:mt-20 sm:pt-8 lg:mt-24">
          <div className="flex flex-col items-center justify-between gap-6 lg:flex-row">
            <p className="text-center text-[12px] text-[#7A90B4] sm:text-[13px] lg:text-left">
              © 2026 Operious AI, Inc.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-4 sm:gap-6">
              {legalLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="text-[12px] text-[#7A90B4] transition-colors duration-[160ms] hover:text-[#C9A84C] sm:text-[13px]"
                >
                  {link.label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
