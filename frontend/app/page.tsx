import { Hero } from "@/components/hero";
import { ProblemSection } from "@/components/problem-section";
import { SubstrateStack } from "@/components/substrate-stack";
import { DomainCards } from "@/components/domain-cards";
import { TrustProof } from "@/components/trust-proof";
import { ArticleCards } from "@/components/article-cards";
import { FaqAccordion } from "@/components/faq-accordion";
import { Footer } from "@/components/footer";

export default function Home() {
  return (
    <main className="flex-1">
      <Hero />
      <ProblemSection />
      <SubstrateStack />
      <DomainCards />
      <TrustProof />
      <ArticleCards />
      <FaqAccordion />
      <Footer />
    </main>
  );
}
