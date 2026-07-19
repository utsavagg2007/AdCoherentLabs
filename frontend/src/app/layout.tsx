import type { Metadata, Viewport } from "next";
import { Manrope } from "next/font/google";
import "./globals.css";

const manrope = Manrope({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-manrope",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "AdCoherent Labs — AI-assisted fintech ad compliance",
    template: "%s · AdCoherent Labs",
  },
  description:
    "Upload a creative. Surface claims, disclosures, and regulation-grounded findings your compliance team can review. Decision support, not legal advice.",
};

export const viewport: Viewport = {
  themeColor: "#05060a",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={manrope.variable} data-scroll-behavior="smooth">
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
