import { MarketingNav } from "@/components/marketing/nav";
import { Hero } from "@/components/marketing/hero";
import { FrameworkRail } from "@/components/marketing/framework-rail";
import { Metrics } from "@/components/marketing/metrics";
import { HowItWorks } from "@/components/marketing/how-it-works";
import { LiveReview } from "@/components/marketing/live-review";
import { Pricing } from "@/components/marketing/pricing";
import { Faq } from "@/components/marketing/faq";
import { FinalCta } from "@/components/marketing/final-cta";
import { MarketingFooter } from "@/components/marketing/footer";

export default function MarketingPage() {
  return (
    <>
      <MarketingNav />
      <main>
        <Hero />
        <FrameworkRail />
        <Metrics />
        <HowItWorks />
        <LiveReview />
        <Pricing />
        <Faq />
        <FinalCta />
      </main>
      <MarketingFooter />
    </>
  );
}
