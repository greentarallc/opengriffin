import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://opengriffin.com"),
  title: "OpenGriffin — Self-evolving personal AI agent. OSS. Free forever.",
  description:
    "The personal AI agent that runs on your machine, remembers everything, schedules its own work, and gets smarter while you sleep. 21 AI providers, BYO key, Apache 2.0.",
  openGraph: {
    title: "OpenGriffin — Self-evolving personal agent",
    description:
      "OSS Telegram-first agent. 30 features. 21 providers BYO-key. Persistent memory, daily journal, skill hub, worker pool, dream cycle. Free forever.",
    url: "https://opengriffin.com",
    siteName: "OpenGriffin",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
