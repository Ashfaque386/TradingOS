import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { ThemeProvider } from "@/components/layout/theme-provider";

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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable} ${plexJakarta.variable} h-full antialiased`}
      // REL-012 Phase A/E: <html data-mode> is set client-side by ThemeProvider's
      // useLayoutEffect (see that component's own comment for the full history -- this used to
      // be a pre-hydration inline <head> script, removed 2026-08-04 after it was found to cause
      // a real hydration-mismatch crash in this Next.js version). The server-rendered markup
      // never includes this attribute at all, so suppressHydrationWarning is the correct,
      // standard fix for this exact "attribute set client-side only" pattern -- scoped to this
      // one element, not a blanket suppression; any other real hydration mismatch still surfaces
      // normally.
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-bg text-text">
        <Providers>
          <ThemeProvider>{children}</ThemeProvider>
        </Providers>
      </body>
    </html>
  );
}
