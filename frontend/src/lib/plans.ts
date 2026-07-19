/** Grounded plan facts — mirrors plan_entitlements seeds. No dollar prices:
 * checkout is Stripe-hosted and the backend owns pricing. */

import type { Tier } from "./types";

export interface PlanFacts {
  tier: Tier;
  name: string;
  tagline: string;
  monthlyCredits: number | null; // null = custom / manual provisioning
  uploadCapMb: number;
  seats: number | null; // null = custom
  apiAccess: boolean;
  creditPacks: boolean;
  highlights: string[];
}

export const PLANS: PlanFacts[] = [
  {
    tier: "free",
    name: "Free",
    tagline: "Evaluate the review loop on real creatives.",
    monthlyCredits: 25,
    uploadCapMb: 10,
    seats: 1,
    apiAccess: false,
    creditPacks: false,
    highlights: [
      "25 credits every month",
      "Full four-layer review",
      "Findings with quoted evidence",
      "10 MB uploads · 1 seat",
    ],
  },
  {
    tier: "hobby",
    name: "Hobby",
    tagline: "For a founder or solo marketer shipping steadily.",
    monthlyCredits: 400,
    uploadCapMb: 20,
    seats: 2,
    apiAccess: false,
    creditPacks: true,
    highlights: [
      "400 credits every month",
      "Credit packs when you need more",
      "Carousel review up to 10 cards",
      "20 MB uploads · 2 seats",
    ],
  },
  {
    tier: "pro",
    name: "Pro",
    tagline: "For compliance teams reviewing every launch.",
    monthlyCredits: 6000,
    uploadCapMb: 30,
    seats: 8,
    apiAccess: true,
    creditPacks: true,
    highlights: [
      "6,000 credits every month",
      "API access with scoped keys",
      "3 concurrent runs",
      "30 MB uploads · 8 seats",
    ],
  },
  {
    tier: "design",
    name: "Design",
    tagline: "For agencies and studios running review at volume.",
    monthlyCredits: 50000,
    uploadCapMb: 50,
    seats: 20,
    apiAccess: true,
    creditPacks: true,
    highlights: [
      "50,000 credits every month",
      "Higher API rate limits",
      "6 concurrent runs",
      "50 MB uploads · 20 seats",
    ],
  },
  {
    tier: "enterprise",
    name: "Enterprise",
    tagline: "Custom provisioning, custom controls.",
    monthlyCredits: null,
    uploadCapMb: 50,
    seats: null,
    apiAccess: true,
    creditPacks: true,
    highlights: [
      "Contract-provisioned credits",
      "Highest rate limits · 10 concurrent runs",
      "Custom seats",
      "Manual credit grants for burst volume",
    ],
  },
];

export function planByTier(tier: Tier | string | undefined): PlanFacts | undefined {
  return PLANS.find((p) => p.tier === tier);
}

export const CREDIT_PACKS = [
  { id: "starter" as const, name: "Starter pack" },
  { id: "growth" as const, name: "Growth pack" },
  { id: "scale" as const, name: "Scale pack" },
];
