import { MarketingNav } from "@/components/marketing/nav";
import { ScrubHero } from "@/components/marketing/scrub-hero";
import { FrameworkRail } from "@/components/marketing/framework-rail";
import { EvidencePinned } from "@/components/marketing/evidence-pinned";
import { Metrics } from "@/components/marketing/metrics";
import { ProductPreview } from "@/components/marketing/product-preview";
import { Pricing } from "@/components/marketing/pricing";
import { Faq } from "@/components/marketing/faq";
import { FinalCta } from "@/components/marketing/final-cta";
import { MarketingFooter } from "@/components/marketing/footer";

export default function MarketingPage() {
  return (
    <>
      <MarketingNav />
      <main>
        <ScrubHero />
        <div className="h-px seam-violet" aria-hidden />
        <FrameworkRail />
        <Metrics />
        <EvidencePinned />
        <ProductPreview />
        <Pricing />
        <Faq />
        <FinalCta />
      </main>
      <MarketingFooter />
    </>
  );
}
