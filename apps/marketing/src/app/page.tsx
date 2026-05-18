import { HeroSection } from '@/components/sections/hero';
import { ArchitectureVisionSection } from '@/components/sections/architecture-vision';
import { CognitionNarrativeSection } from '@/components/sections/cognition-narrative';
import { DeterministicInfrastructureSection } from '@/components/sections/deterministic-infrastructure';
import { GovernanceSection } from '@/components/sections/governance';
import { MultilingualSection } from '@/components/sections/multilingual';
import { CommandCenterPreviewSection } from '@/components/sections/command-center-preview';
import { PilotCtaSection } from '@/components/sections/pilot-cta';

export default function MarketingHome() {
  return (
    <>
      <HeroSection />
      <ArchitectureVisionSection />
      <CognitionNarrativeSection />
      <DeterministicInfrastructureSection />
      <GovernanceSection />
      <MultilingualSection />
      <CommandCenterPreviewSection />
      <PilotCtaSection />
    </>
  );
}
