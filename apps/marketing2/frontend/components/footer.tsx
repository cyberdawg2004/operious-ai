import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { OperioussLogo } from "./logo";
import { footerGroups } from "@/lib/site-links";

export function Footer() {
  const legalLinks = footerGroups.find((group) => group.label === "Legal")?.links ?? [];

  return (
    <footer className="bg-[#05080F] px-4 pb-6 pt-16 sm:px-8 sm:pb-8 sm:pt-20 lg:px-16 lg:pt-24">
      <div className="mx-auto max-w-[1440px]">
        <OperioussLogo size={36} showWordmark={true} />
        <p
          className="mt-4 text-[10px] uppercase tracking-[0.18em] text-[#C9A84C] sm:text-[11px]"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          Governed execution infrastructure
        </p>

        <div className="mt-12 grid grid-cols-2 gap-8 sm:mt-14 sm:grid-cols-3 sm:gap-10 lg:mt-16 lg:grid-cols-7 lg:gap-10">
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
                      className="inline-flex min-h-11 items-center text-[14px] text-[#D8E4F4] transition-colors duration-[160ms] hover:text-[#C9A84C]"
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
          <Link
            href="/company/contact"
            className="group inline-flex min-h-11 items-center gap-2 rounded-md border border-white/10 bg-white/[0.02] px-4 text-[13px] font-medium text-[#D8E4F4] transition-all duration-200 hover:-translate-y-0.5 hover:border-[#C9A84C]/40 hover:bg-white/[0.04] hover:text-[#C9A84C]"
          >
            Reach out to our sales team
            <ArrowRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
          </Link>
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
                  className="inline-flex min-h-11 items-center text-[12px] text-[#7A90B4] transition-colors duration-[160ms] hover:text-[#C9A84C] sm:text-[13px]"
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
