import type { PlanEntitlement, Tier } from "./types";

/**
 * Static mirror of the `plan_entitlements` seed in
 * supabase/migrations/0004_entitlements_and_quota.sql. The database row is
 * the source of truth at runtime; this copy backs demo mode and the public
 * pricing page. Prices are placeholders — set them from a real cost model
 * (playbook §9 margin note) and from the Stripe Prices you create.
 */
export const TIERS: Tier[] = ["free", "hobby", "pro", "design", "enterprise"];

export const ENTITLEMENTS: Record<Tier, PlanEntitlement> = {
  free: {
    tier: "free",
    llm_provider: "openrouter",
    llm_model: "qwen/qwen3.7-plus",
    max_output_tokens: 4000,
    scans_per_month: 20,
    seats: 1,
    api_access: false,
    sso: false,
    sla: false,
    frameworks: ["FTC"],
  },
  hobby: {
    tier: "hobby",
    llm_provider: "openrouter",
    llm_model: "qwen/qwen3.7-max",
    max_output_tokens: 6000,
    scans_per_month: 150,
    seats: 2,
    api_access: false,
    sso: false,
    sla: false,
    frameworks: ["FTC", "GDPR"],
  },
  pro: {
    tier: "pro",
    llm_provider: "anthropic",
    llm_model: "claude-sonnet-5",
    max_output_tokens: 8000,
    scans_per_month: 1000,
    seats: 8,
    api_access: true,
    sso: false,
    sla: false,
    frameworks: "all",
  },
  design: {
    tier: "design",
    llm_provider: "anthropic",
    llm_model: "claude-opus-4-8",
    max_output_tokens: 16000,
    scans_per_month: 4000,
    seats: 20,
    api_access: true,
    sso: false,
    sla: false,
    frameworks: "all",
  },
  enterprise: {
    tier: "enterprise",
    llm_provider: "anthropic",
    llm_model: "claude-opus-4-8",
    max_output_tokens: 32000,
    scans_per_month: null,
    seats: null,
    api_access: true,
    sso: true,
    sla: true,
    frameworks: "all",
  },
};

export interface TierDisplay {
  name: string;
  priceMonthly: number | null; // null = custom
  blurb: string;
  highlight?: boolean;
  features: string[];
}

export const TIER_DISPLAY: Record<Tier, TierDisplay> = {
  free: {
    name: "Free",
    priceMonthly: 0,
    blurb: "Try the engine on real creatives.",
    features: [
      "20 scans / month",
      "Qwen Turbo reasoning",
      "FTC framework",
      "1 seat",
      "Community support",
    ],
  },
  hobby: {
    name: "Hobby",
    priceMonthly: 29,
    blurb: "For solo marketers shipping regulated ads.",
    features: [
      "150 scans / month",
      "Qwen-Max reasoning",
      "FTC + GDPR frameworks",
      "2 seats",
      "Email support",
    ],
  },
  pro: {
    name: "Pro",
    priceMonthly: 149,
    blurb: "High-quality reasoning for growth teams.",
    highlight: true,
    features: [
      "1,000 scans / month",
      "Claude Sonnet 5 reasoning",
      "All frameworks (FTC · SEC · SEBI · RBI · GDPR)",
      "8 seats · API access",
      "Priority support",
    ],
  },
  design: {
    name: "Design",
    priceMonthly: 399,
    blurb: "Newest Opus, built for agency volume.",
    features: [
      "4,000 scans / month",
      "Claude Opus 4.8 (1M context)",
      "All frameworks",
      "20 seats · API access",
      "Priority support",
    ],
  },
  enterprise: {
    name: "Enterprise",
    priceMonthly: null,
    blurb: "Governance, capacity and residency guarantees.",
    features: [
      "Custom / uncapped quotas",
      "Opus 4.8 + optional Fable 5 routing",
      "SSO / SAML · audit exports",
      "Custom rule packs · data residency",
      "SLA-backed support",
    ],
  },
};

export function frameworksLabel(f: PlanEntitlement["frameworks"]) {
  return f === "all" ? "All frameworks" : f.join(", ");
}
