import { redirect } from "next/navigation";
import { getSessionState } from "@/lib/data";
import { Logo } from "@/components/logo";
import { OnboardingForm } from "./onboarding-form";

export const metadata = { title: "Create your organization" };

export default async function OnboardingPage() {
  const state = await getSessionState();
  if (state.kind === "unauthenticated") redirect("/login");
  if (state.kind === "ready") redirect("/dashboard");

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center px-5">
      <div className="bg-grid absolute inset-0 [mask-image:radial-gradient(50%_50%_at_50%_40%,black,transparent)]" />
      <div className="relative w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>
        <div className="rounded-2xl border border-line bg-surface p-7">
          <h1 className="text-lg font-semibold tracking-tight">
            Create your organization
          </h1>
          <p className="mt-1.5 text-xs leading-relaxed text-ink-dim">
            Everything in AdCoherent — submissions, runs, findings, billing —
            belongs to an organization. You&apos;ll be its owner and can invite
            your team after. Signed in as{" "}
            <span className="text-ink">{state.user.email}</span>.
          </p>
          <OnboardingForm />
        </div>
      </div>
    </div>
  );
}
