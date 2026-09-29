import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Press_Start_2P } from "next/font/google";

import "./globals.css";

const sans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-plex-sans" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });
const pixel = Press_Start_2P({ subsets: ["latin"], weight: "400", variable: "--font-press-start" });

export const metadata: Metadata = {
  title: "Nightshift lab floor",
  description: "Watch Nightshift's research seats work: every prompt, experiment, conversation and decision.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} ${pixel.variable}`}>
      <body>{children}</body>
    </html>
  );
}
