import Link from "next/link";
import { Logo } from "@/components/logo";

export function MarketingFooter() {
  return (
    <footer data-surface="dark" className="bg-ink-950">
      <div className="h-px seam-violet" aria-hidden />
      <div className="container-wide py-14">
        <div className="flex flex-col justify-between gap-10 md:flex-row">
          <div className="max-w-xs">
            <Logo tone="light" />
            <p className="mt-4 text-[13px] leading-relaxed text-white/45">
              AI-assisted, evidence-first compliance review for US fintech
              advertising.
            </p>
          </div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-10 sm:grid-cols-3">
            <div>
              <p className="text-[11px] font-bold tracking-wider text-white/40 uppercase">
                Product
              </p>
              <ul className="mt-3 space-y-2 text-[13.5px] font-medium">
                <li>
                  <a href="#how-it-works" className="text-white/70 hover:text-white">
                    How it works
                  </a>
                </li>
                <li>
                  <a href="#preview" className="text-white/70 hover:text-white">
                    The report
                  </a>
                </li>
                <li>
                  <a href="#pricing" className="text-white/70 hover:text-white">
                    Pricing
                  </a>
                </li>
                <li>
                  <a href="#faq" className="text-white/70 hover:text-white">
                    FAQ
                  </a>
                </li>
              </ul>
            </div>
            <div>
              <p className="text-[11px] font-bold tracking-wider text-white/40 uppercase">
                App
              </p>
              <ul className="mt-3 space-y-2 text-[13.5px] font-medium">
                <li>
                  <Link href="/login" className="text-white/70 hover:text-white">
                    Sign in
                  </Link>
                </li>
                <li>
                  <Link href="/signup" className="text-white/70 hover:text-white">
                    Create account
                  </Link>
                </li>
                <li>
                  <Link href="/dashboard" className="text-white/70 hover:text-white">
                    Dashboard
                  </Link>
                </li>
              </ul>
            </div>
            <div>
              <p className="text-[11px] font-bold tracking-wider text-white/40 uppercase">
                Contact
              </p>
              <ul className="mt-3 space-y-2 text-[13.5px] font-medium">
                <li>
                  <a
                    href="mailto:sales@adcoherentlabs.com"
                    className="text-white/70 hover:text-white"
                  >
                    Talk to sales
                  </a>
                </li>
              </ul>
            </div>
          </nav>
        </div>
        <div className="mt-12 flex flex-col items-start justify-between gap-3 border-t border-white/10 pt-6 text-[12px] text-white/35 sm:flex-row sm:items-center">
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
