"use client";

export function SplineHeroBg() {
  return (
    <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
      <iframe
        src="https://my.spline.design/motiontrails-LkkaFYHfse20s2oaEX8yXTPR/"
        frameBorder={0}
        width="100%"
        height="100%"
        className="absolute inset-0 h-full w-full"
        style={{ border: "none" }}
        loading="lazy"
        title="Operious motion trails background"
        aria-hidden="true"
      />
      {/* Dark overlay — keeps all text readable */}
      <div className="absolute inset-0 bg-[#05080F]/75" />
    </div>
  );
}
