import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Plus_Jakarta_Sans } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { Providers } from "./providers";
import { ThemeProvider } from "@/components/layout/theme-provider";
import { THEME_STORAGE_KEY } from "@/lib/theme-store";

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

// REL-012 Phase A (2026-08-04): heading font for the new design direction (Phase 7 §1.1) --
// added alongside the existing IBM Plex Sans/Mono, which stay as the body/tabular-data faces.
const plexJakarta = Plus_Jakarta_Sans({
  variable: "--font-plex-jakarta",
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "TradingOS — Command Center",
  description: "AI Trading Operating System for Indian equity & F&O markets",
};

// Runs synchronously before first paint (next/script beforeInteractive) so <html data-mode>
// is correct on the very first frame -- avoids a flash of the wrong theme. Reads the same
// zustand-persist localStorage shape ThemeProvider's store writes; any parse failure or first
// visit (no stored value yet) falls back to "light", the approved direction's default.
const ANTI_FLASH_SCRIPT = `(function() {
  try {
    var raw = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
    var mode = raw ? JSON.parse(raw).state.mode : "light";
    document.documentElement.dataset.mode = mode === "dark" ? "dark" : "light";
  } catch (e) {
    document.documentElement.dataset.mode = "light";
  }
})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable} ${plexJakarta.variable} h-full antialiased dark`}
      // REL-012 Phase A: the anti-flash script below sets `data-mode` on this element before
      // React hydrates, which the server-rendered markup never included -- the standard,
      // documented fix for this exact "attribute set by a pre-hydration script" pattern
      // (Next.js's own dark-mode guidance recommends the same). Scoped to this one element,
      // not a blanket suppression -- any other real hydration mismatch still surfaces normally.
      suppressHydrationWarning
    >
      <head>
        <Script id="theme-anti-flash" strategy="beforeInteractive">
          {ANTI_FLASH_SCRIPT}
        </Script>
      </head>
      <body className="min-h-full flex flex-col bg-[#09090B] text-zinc-100">
        <Providers>
          <ThemeProvider>{children}</ThemeProvider>
        </Providers>
      </body>
    </html>
  );
}
