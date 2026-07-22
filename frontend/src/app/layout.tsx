import type { Metadata, Viewport } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const grotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-grotesk",
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
  themeColor: "#0a0b0d",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${grotesk.variable}`}
      data-scroll-behavior="smooth"
    >
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
