import { Hero } from "@/components/hero";
import { ProblemSection } from "@/components/problem-section";
import { SubstrateStack } from "@/components/substrate-stack";

export default function Home() {
  return (
    <main className="flex-1">
      <Hero />
      <ProblemSection />
      <SubstrateStack />
    </main>
  );
}
