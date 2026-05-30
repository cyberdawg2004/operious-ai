"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";
import { OperioussLogo } from "./logo";

const navItems = [
  { label: "Platform", href: "/#platform" },
  { label: "Solutions", href: "/#solutions" },
  { label: "Security", href: "/#security" },
  { label: "Pilot Program", href: "/#pilot" },
];

export function Navigation() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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
      <nav
        className="fixed inset-x-0 top-0 z-[60] border-b border-white/10 bg-[#050508]/92 backdrop-blur-xl"
        aria-label="Main navigation"
      >
        <div className="mx-auto flex h-[68px] max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <Link
            href="/"
            aria-label="Operious home"
            className="shrink-0 transition-opacity duration-200 hover:opacity-90"
          >
            <OperioussLogo size={28} showWordmark tone="dark" />
          </Link>

          <div className="hidden items-center gap-8 md:flex">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="text-[14px] font-medium text-white/72 transition-colors duration-200 hover:text-[#C9A84C]"
              >
                {item.label}
              </Link>
            ))}
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            <Link
              href="/company/contact?topic=architecture-review"
              className="inline-flex min-h-10 items-center justify-center rounded-md bg-[#C9A84C] px-3 text-[13px] font-semibold text-[#050508] transition-colors duration-200 hover:bg-[#D9B85A] sm:px-4"
            >
              Book a Review
            </Link>
            <button
              type="button"
              onClick={() => setMobileMenuOpen(true)}
              className="flex h-10 w-10 items-center justify-center rounded-md border border-white/10 text-white/85 transition-colors duration-200 hover:border-[#C9A84C]/50 hover:text-[#C9A84C] md:hidden"
              aria-label="Open menu"
              aria-expanded={mobileMenuOpen}
            >
              <Menu className="h-5 w-5" strokeWidth={1.8} />
            </button>
          </div>
        </div>
      </nav>

      {mobileMenuOpen && (
        <div className="fixed inset-0 z-[70] bg-[#050508] md:hidden">
          <div className="flex h-[68px] items-center justify-between border-b border-white/10 px-4">
            <Link href="/" onClick={() => setMobileMenuOpen(false)}>
              <OperioussLogo size={28} showWordmark tone="dark" />
            </Link>
            <button
              type="button"
              onClick={() => setMobileMenuOpen(false)}
              className="flex h-10 w-10 items-center justify-center rounded-md border border-white/10 text-white/85 transition-colors duration-200 hover:border-[#C9A84C]/50 hover:text-[#C9A84C]"
              aria-label="Close menu"
            >
              <X className="h-5 w-5" strokeWidth={1.8} />
            </button>
          </div>
          <div className="grid gap-2 px-4 py-8">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileMenuOpen(false)}
                className="border-b border-white/10 py-5 text-[18px] font-medium text-white"
              >
                {item.label}
              </Link>
            ))}
            <Link
              href="/company/contact?topic=architecture-review"
              onClick={() => setMobileMenuOpen(false)}
              className="mt-6 inline-flex min-h-12 items-center justify-center rounded-md bg-[#C9A84C] px-4 text-[14px] font-semibold text-[#050508]"
            >
              Book a Review
            </Link>
          </div>
        </div>
      )}
    </>
  );
}
