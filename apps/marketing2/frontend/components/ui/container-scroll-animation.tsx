"use client";
import React, { useRef } from "react";
import { useScroll, useTransform, motion, MotionValue, useReducedMotion } from "framer-motion";

export const ContainerScroll = ({
  titleComponent,
  children,
}: {
  titleComponent: string | React.ReactNode;
  children: React.ReactNode;
}) => {
  const reducedMotion = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: containerRef });
  const [isMobile, setIsMobile] = React.useState(false);

  React.useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth <= 768);
    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  const scaleDimensions = () => (isMobile ? [0.7, 0.9] : [1.05, 1]);
  const rotate = useTransform(scrollYProgress, [0, 1], [18, 0]);
  const scale = useTransform(scrollYProgress, [0, 1], scaleDimensions());
  const translate = useTransform(scrollYProgress, [0, 1], [0, -100]);

  if (reducedMotion) {
    return (
      <div className="py-10 md:py-20 w-full">
        <div className="max-w-5xl mx-auto text-center mb-8">{titleComponent}</div>
        <div className="max-w-5xl mx-auto h-[30rem] md:h-[40rem] w-full border border-[var(--border-subtle)] bg-[var(--surface)] rounded-[24px] overflow-hidden">
          {children}
        </div>
      </div>
    );
  }

  return (
    <div
      className="h-[60rem] md:h-[80rem] flex items-center justify-center relative p-2 md:p-20"
      ref={containerRef}
    >
      <div className="py-10 md:py-40 w-full relative" style={{ perspective: "1000px" }}>
        <Header translate={translate} titleComponent={titleComponent} />
        <Card rotate={rotate} scale={scale}>
          {children}
        </Card>
      </div>
    </div>
  );
};

const Header = ({ translate, titleComponent }: { translate: MotionValue<number>; titleComponent: React.ReactNode }) => (
  <motion.div style={{ translateY: translate }} className="max-w-5xl mx-auto text-center mb-8">
    {titleComponent}
  </motion.div>
);

const Card = ({
  rotate,
  scale,
  children,
}: {
  rotate: MotionValue<number>;
  scale: MotionValue<number>;
  children: React.ReactNode;
}) => (
  <motion.div
    style={{
      rotateX: rotate,
      scale,
      boxShadow:
        "0 0 #0000004d, 0 9px 20px #0000004a, 0 37px 37px #00000042, 0 84px 50px #00000026, 0 149px 60px #0000000a, 0 233px 65px #00000003",
    }}
    className="max-w-5xl -mt-12 mx-auto h-[30rem] md:h-[40rem] w-full border border-[var(--border-subtle)] p-2 md:p-4 bg-[var(--surface)] rounded-[24px] shadow-2xl"
  >
    <div className="h-full w-full overflow-hidden rounded-2xl bg-[var(--surface)]">
      {children}
    </div>
  </motion.div>
);
