import { HeroSection } from '@/components/sections/hero-section';
import { ProblemSection } from '@/components/sections/problem-section';
import { KernelSection } from '@/components/sections/kernel-section';
import { SolutionsSection } from '@/components/sections/solutions-section';
import { ProductsSection } from '@/components/sections/products-section';
import { TrustSection } from '@/components/sections/trust-section';
import { SubstrateChatSection } from '@/components/sections/substrate-chat-section';
import { EditorialSection } from '@/components/sections/editorial-section';
import { NewsletterSection } from '@/components/sections/newsletter-section';
import { FaqSection } from '@/components/sections/faq-section';
import { ContactSection } from '@/components/sections/contact-section';

export default function MarketingHome() {
  return (
    <>
      <HeroSection />
      <ProblemSection />
      <KernelSection />
      <SolutionsSection />
      <ProductsSection />
      <TrustSection />
      <SubstrateChatSection />
      <EditorialSection />
      <NewsletterSection />
      <FaqSection />
      <ContactSection />
    </>
  );
}
