"use client";

import { motion } from "framer-motion";

// Custom hexagonal SVG glyphs
function WarningHexagon() {
  return (
    <svg
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Outer hexagon */}
      <path
        d="M24 2L44 13.5V36.5L24 48L4 36.5V13.5L24 2Z"
        stroke="#A8882C"
        strokeWidth="1.5"
        fill="none"
      />
      {/* Warning triangle */}
      <path
        d="M24 14L34 32H14L24 14Z"
        stroke="#A8882C"
        strokeWidth="1.5"
        fill="none"
        strokeLinejoin="round"
      />
      {/* Exclamation mark */}
      <line
        x1="24"
        y1="20"
        x2="24"
        y2="26"
        stroke="#A8882C"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <circle cx="24" cy="29" r="1" fill="#A8882C" />
    </svg>
  );
}

function ConcentricHexagons() {
  return (
    <svg
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Outer hexagon */}
      <path
        d="M24 2L44 13.5V36.5L24 48L4 36.5V13.5L24 2Z"
        stroke="#A8882C"
        strokeWidth="1.5"
        fill="none"
      />
      {/* Middle hexagon - slightly faded */}
      <path
        d="M24 10L36 17.5V32.5L24 40L12 32.5V17.5L24 10Z"
        stroke="#A8882C"
        strokeWidth="1.5"
        fill="none"
        opacity="0.6"
      />
      {/* Inner hexagon - more faded */}
      <path
        d="M24 17L30 21V31L24 35L18 31V21L24 17Z"
        stroke="#A8882C"
        strokeWidth="1.5"
        fill="none"
        opacity="0.3"
      />
    </svg>
  );
}

function FracturedChainHexagon() {
  return (
    <svg
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Outer hexagon */}
      <path
        d="M24 2L44 13.5V36.5L24 48L4 36.5V13.5L24 2Z"
        stroke="#A8882C"
        strokeWidth="1.5"
        fill="none"
      />
      {/* Left chain link */}
      <rect
        x="10"
        y="20"
        width="10"
        height="8"
        rx="4"
        stroke="#A8882C"
        strokeWidth="1.5"
        fill="none"
      />
      {/* Right chain link - offset/broken */}
      <rect
        x="28"
        y="20"
        width="10"
        height="8"
        rx="4"
        stroke="#A8882C"
        strokeWidth="1.5"
        fill="none"
      />
      {/* Broken connection lines */}
      <line
        x1="20"
        y1="24"
        x2="22"
        y2="22"
        stroke="#A8882C"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <line
        x1="26"
        y1="26"
        x2="28"
        y2="24"
        stroke="#A8882C"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

const columns = [
  {
    icon: WarningHexagon,
    subtitle: "Workflows that improvise create liability.",
    body: "Language models trained to be helpful will exceed authorized parameters under pressure — granting refunds beyond limit, approving exceptions outside policy, generating communications that contradict legal guidance. Every helpful improvisation is an unaudited deviation from your operational contract.",
    resolution:
      "Operious agents cannot improvise. Behavior is locked to encoded governance.",
  },
  {
    icon: ConcentricHexagons,
    subtitle: "Outputs that hallucinate erode confidence.",
    body: "Generative systems produce plausible-sounding but factually incorrect outputs at unpredictable intervals. In customer-facing operations, a single hallucinated policy statement or fabricated case history can trigger regulatory scrutiny, legal exposure, and irreversible reputational damage.",
    resolution:
      "Operious outputs are deterministic. Every response traces to verified source.",
  },
  {
    icon: FracturedChainHexagon,
    subtitle: "Decisions that cannot be explained cannot be defended.",
    body: "When a regulatory body or legal proceeding demands explanation for an automated decision, 'the model thought it was right' is not a defensible answer. Black-box AI creates institutional risk that compounds with every unlogged interaction.",
    resolution:
      "Operious decisions are fully attributable. Every action has a compliance trail.",
  },
];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.15,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 24 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.6,
      ease: [0.25, 0.46, 0.45, 0.94],
    },
  },
};

export function ProblemSection() {
  return (
    <section className="bg-canvas py-[160px] px-[64px]">
      <div className="max-w-[1280px] mx-auto">
        {/* Section header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6 }}
        >
          {/* Section label */}
          <p
            className="font-mono text-[11px] uppercase tracking-[0.18em] text-gold mb-[24px]"
            style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
          >
            §01 · THE PROBLEM
          </p>

          {/* Section title */}
          <h2
            className="text-[64px] font-bold tracking-[-0.015em] leading-[1.08] text-ink-primary max-w-[880px] mb-[32px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            Enterprise operations were never built for autonomy.
          </h2>

          {/* Section intro */}
          <p className="text-[18px] leading-[1.55] text-ink-body max-w-[760px] mb-[96px]">
            For decades, mission-critical operational workflows have depended on
            human improvisation, undocumented knowledge, and audit trails that
            exist only in case management software. Generative AI promised
            automation but introduced three new failure modes that are
            structurally incompatible with regulated enterprise environments.
          </p>
        </motion.div>

        {/* Three-column grid */}
        <motion.div
          className="grid grid-cols-3 gap-[48px] items-start"
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-100px" }}
        >
          {columns.map((column, index) => {
            const IconComponent = column.icon;
            return (
              <motion.div key={index} variants={itemVariants}>
                {/* Hexagonal glyph */}
                <div className="w-[48px] h-[48px]">
                  <IconComponent />
                </div>

                {/* Subtitle */}
                <h3
                  className="text-[28px] font-semibold tracking-[-0.005em] leading-[1.25] text-ink-primary mt-[32px] mb-[16px]"
                  style={{ fontFamily: "var(--font-cormorant-sc)" }}
                >
                  {column.subtitle}
                </h3>

                {/* Body */}
                <p className="text-[16px] leading-[1.6] text-ink-body mb-[24px]">
                  {column.body}
                </p>

                {/* Resolution line */}
                <p
                  className="text-[14px] text-gold italic flex items-center gap-2"
                  style={{ fontFamily: "var(--font-cormorant)" }}
                >
                  <span className="w-[6px] h-[6px] rounded-full bg-gold flex-shrink-0" />
                  {column.resolution}
                </p>
              </motion.div>
            );
          })}
        </motion.div>
      </div>
    </section>
  );
}
