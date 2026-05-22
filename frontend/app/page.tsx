import { Hero } from "@/components/hero";
import { ProblemSection } from "@/components/problem-section";

export default function Home() {
  return (
    <main className="flex-1">
      <Hero />
      <ProblemSection />
    </main>
  );
}
