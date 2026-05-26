"use client";

import { Suspense, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { motion, useReducedMotion } from "framer-motion";
import { ClientErrorBoundary } from "@/components/client-error-boundary";

const Spline = dynamic(() => import("@splinetool/react-spline"), {
  ssr: false,
  loading: () => null,
});

const SCENE_URL =
  "https://prod.spline.design/2e9069e7-79f9-4864-a6e1-a18a6f197af6/scene.splinecode";

function TechnicalFallback() {
  const reducedMotion = useReducedMotion();

  return (
    <div className="absolute inset-0 overflow-hidden bg-[#05080F]">
      <div
        className="absolute inset-0 opacity-[0.08]"
        style={{
          backgroundImage:
            "linear-gradient(#D8E4F4 1px, transparent 1px), linear-gradient(90deg, #D8E4F4 1px, transparent 1px)",
          backgroundSize: "64px 64px",
        }}
      />
      <motion.div
        className="absolute left-0 right-0 top-1/3 h-px bg-gradient-to-r from-transparent via-[#2A5CAA]/80 to-transparent"
        animate={reducedMotion ? undefined : { x: ["-30%", "30%", "-30%"] }}
        transition={{ duration: 14, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute bottom-1/4 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[#C9A84C]/45 to-transparent"
        animate={reducedMotion ? undefined : { x: ["30%", "-30%", "30%"] }}
        transition={{ duration: 18, repeat: Infinity, ease: "easeInOut" }}
      />
    </div>
  );
}

export function SplineHeroBg() {
  const [canLoadScene, setCanLoadScene] = useState(false);

  useEffect(() => {
    let cancelled = false;

    fetch(SCENE_URL, { method: "HEAD", mode: "cors" })
      .then((response) => {
        if (!cancelled) {
          setCanLoadScene(response.ok);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCanLoadScene(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
      {canLoadScene ? (
        <ClientErrorBoundary fallback={<TechnicalFallback />} label="Spline hero failed">
          <Suspense fallback={<TechnicalFallback />}>
            <Spline scene={SCENE_URL} style={{ width: "100%", height: "100%" }} />
          </Suspense>
        </ClientErrorBoundary>
      ) : (
        <TechnicalFallback />
      )}
      <div className="absolute inset-0 bg-[#05080F]/70 backdrop-blur-[1px]" />
    </div>
  );
}
