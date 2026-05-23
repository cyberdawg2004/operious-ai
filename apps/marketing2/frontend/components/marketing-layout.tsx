import { Navigation } from "@/components/navigation";
import { Footer } from "@/components/footer";

export function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Navigation />
      {children}
      <Footer />
    </>
  );
}
