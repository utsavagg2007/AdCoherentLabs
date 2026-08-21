import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google";
import Script from "next/script";
import { ThemeProvider, themeInitScript } from "@/components/theme";
import "./globals.css";

/* Inter carries the interface — it holds up at 11px in dense tables, which
   the report and ledger views lean on hard. Plus Jakarta Sans is the display
   voice: warmer than a grotesk, still enterprise. JetBrains Mono replaces the
   old `ui-monospace` stack, which rendered as a different face on every OS
   and was a real part of why evidence quotes looked ragged. */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
  variable: "--font-jakarta",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "AdCoherent Labs — AI ad compliance, verified",
    template: "%s · AdCoherent Labs",
  },
  description:
    "Upload a creative. Four AI layers surface claims, disclosures, and regulation-grounded findings your compliance team can verify. Decision support, not legal advice.",
};

export const viewport: Viewport = {
  // Matches --surface-canvas in each theme, so the browser chrome on mobile
  // never disagrees with the page behind it.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f6fb" },
    { media: "(prefers-color-scheme: dark)", color: "#07070e" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jakarta.variable} ${jetbrains.variable}`}
      data-scroll-behavior="smooth"
      // themeInitScript writes data-theme onto this element before React
      // hydrates, so the server markup and the DOM legitimately differ here.
      suppressHydrationWarning
    >
      <head>
        <Script
          id="adcoherent-theme-init"
          strategy="beforeInteractive"
          dangerouslySetInnerHTML={{ __html: themeInitScript }}
        />
      </head>
      <body className="min-h-dvh antialiased">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
