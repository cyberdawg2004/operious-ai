"use client";

export interface SkewCardProps {
  title: string;
  desc: string;
  gradientFrom: string;
  gradientTo: string;
  ctaHref?: string;
  ctaLabel?: string;
}

export function SkewCard({
  title,
  desc,
  gradientFrom,
  gradientTo,
  ctaHref = "#",
  ctaLabel = "Learn more",
}: SkewCardProps) {
  return (
    <div className="group relative w-[300px] h-[380px] m-[20px_16px] transition-[transform,left,padding,width] duration-[400ms]">
      <span
        className="absolute top-0 left-[40px] w-1/2 h-full rounded-xl transform skew-x-[14deg] transition-[transform,left,width] duration-[400ms] group-hover:skew-x-0 group-hover:left-[16px] group-hover:w-[calc(100%-80px)]"
        style={{ background: `linear-gradient(315deg, ${gradientFrom}, ${gradientTo})` }}
        aria-hidden="true"
      />
      <span
        className="absolute top-0 left-[40px] w-1/2 h-full rounded-xl transform skew-x-[14deg] blur-[28px] opacity-50 transition-[transform,left,width] duration-[400ms] group-hover:skew-x-0 group-hover:left-[16px] group-hover:w-[calc(100%-80px)]"
        style={{ background: `linear-gradient(315deg, ${gradientFrom}, ${gradientTo})` }}
        aria-hidden="true"
      />
      <div className="relative z-20 left-0 h-full p-[20px_28px] bg-white/[0.07] backdrop-blur-[10px] shadow-lg rounded-xl text-white transition-[transform,left,padding,width] duration-[400ms] group-hover:left-[-20px] group-hover:p-[40px_28px] flex flex-col gap-3">
        <h3
          className="text-xl font-bold leading-tight"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          {title}
        </h3>
        <p
          className="text-sm leading-relaxed opacity-85 flex-1"
          style={{ fontFamily: "var(--font-inter, var(--type-geometric))" }}
        >
          {desc}
        </p>
        <a
          href={ctaHref}
          className="inline-block text-sm font-semibold text-[var(--ink-primary)] bg-white px-4 py-2 rounded-lg hover:bg-[var(--canvas)] transition-colors self-start cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          style={{ fontFamily: "var(--font-inter, var(--type-geometric))", letterSpacing: "0.03em", minHeight: "44px", display: "inline-flex", alignItems: "center" }}
        >
          {ctaLabel}
        </a>
      </div>
    </div>
  );
}

export default function SkewCards({ cards }: { cards: SkewCardProps[] }) {
  return (
    <div className="flex justify-center items-center flex-wrap py-4">
      {cards.map((card, idx) => (
        <SkewCard key={idx} {...card} />
      ))}
    </div>
  );
}
