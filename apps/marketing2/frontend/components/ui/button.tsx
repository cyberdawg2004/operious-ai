import { type ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

interface ButtonProps {
  href?: string;
  children: ReactNode;
  variant?: "primary" | "ghost";
  className?: string;
  onClick?: () => void;
  type?: "button" | "submit";
}

export function Button({
  href,
  children,
  variant = "primary",
  className,
  onClick,
  type = "button",
}: ButtonProps) {
  const base =
    "relative inline-flex items-center gap-3 px-7 py-3 " +
    "text-sm font-medium tracking-wider " +
    "transition-all duration-300 rounded-md overflow-hidden group " +
    "hover:-translate-y-0.5 hover:scale-[1.02] active:scale-[0.98]";

  const variants = {
    primary:
      "bg-[#C9A84C] text-[#05080F] " +
      "shadow-[0_10px_28px_rgba(201,168,76,0.18)] " +
      "hover:bg-[#D4B85A] hover:shadow-[0_18px_44px_rgba(201,168,76,0.40)]",
    ghost:
      "border border-[#1A2744] text-[#D8E4F4] " +
      "hover:border-[#2A5CAA] hover:text-white " +
      "hover:shadow-[0_14px_32px_rgba(42,107,204,0.22)]",
  };

  const classes = cn(base, variants[variant], className);

  const inner = (
    <>
      <span className="relative z-10">{children}</span>
      {variant === "ghost" && (
        <span
          className="h-px w-3 shrink-0 bg-[#2A5CAA]
                     transition-all duration-300 group-hover:w-5"
        />
      )}
      <span
        className="
          absolute inset-0
          -translate-x-full bg-gradient-to-r from-white/0 via-white/[0.06] to-white/0
          transition-transform duration-700 ease-in-out group-hover:translate-x-full
        "
      />
    </>
  );

  if (href) {
    return (
      <Link href={href} className={classes}>
        {inner}
      </Link>
    );
  }

  return (
    <button type={type} onClick={onClick} className={classes}>
      {inner}
    </button>
  );
}
