import Link from "next/link";
import { Logo } from "@/components/logo";

export function MarketingFooter() {
  return (
    <footer className="bg-canvas">
      <div className="h-px seam" aria-hidden />
      <div className="container-wide py-14">
        <div className="flex flex-col justify-between gap-10 md:flex-row">
          <div className="max-w-xs">
            <Logo />
            <p className="mt-4 text-[13px] leading-relaxed text-subtle">
              AI-assisted, evidence-first compliance review for US fintech
              advertising.
            </p>
          </div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-10 sm:grid-cols-3">
            <div>
              <p className="text-[11px] font-bold tracking-wider text-subtle uppercase">
                Product
              </p>
              <ul className="mt-3 space-y-2 text-[13.5px] font-medium">
                <li>
                  <a href="#how-it-works" className="text-muted hover:text-strong">
                    How it works
                  </a>
                </li>
                <li>
                  <a href="#live" className="text-muted hover:text-strong">
                    Live review
                  </a>
                </li>
                <li>
                  <a href="#pricing" className="text-muted hover:text-strong">
                    Pricing
                  </a>
                </li>
                <li>
                  <a href="#faq" className="text-muted hover:text-strong">
                    FAQ
                  </a>
                </li>
              </ul>
            </div>
            <div>
              <p className="text-[11px] font-bold tracking-wider text-subtle uppercase">
                App
              </p>
              <ul className="mt-3 space-y-2 text-[13.5px] font-medium">
                <li>
                  <Link href="/login" className="text-muted hover:text-strong">
                    Sign in
                  </Link>
                </li>
                <li>
                  <Link href="/signup" className="text-muted hover:text-strong">
                    Create account
                  </Link>
                </li>
                <li>
                  <Link href="/dashboard" className="text-muted hover:text-strong">
                    Dashboard
                  </Link>
                </li>
              </ul>
            </div>
            <div>
              <p className="text-[11px] font-bold tracking-wider text-subtle uppercase">
                Contact
              </p>
              <ul className="mt-3 space-y-2 text-[13.5px] font-medium">
                <li>
                  <a
                    href="mailto:sales@adcoherentlabs.com"
                    className="text-muted hover:text-strong"
                  >
                    Talk to sales
                  </a>
                </li>
              </ul>
            </div>
          </nav>
        </div>
        <div className="mt-12 flex flex-col items-start justify-between gap-3 border-t border-line pt-6 text-[12px] text-subtle sm:flex-row sm:items-center">
          <p>© {new Date().getFullYear()} AdCoherent Labs.</p>
          <p className="italic">
            Reports are decision support for your compliance process, not legal
            advice.
          </p>
        </div>
      </div>
    </footer>
  );
}
