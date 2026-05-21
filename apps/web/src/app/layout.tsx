import "./globals.css";
import type { Metadata } from "next";
import { Fraunces, Hanken_Grotesk } from "next/font/google";
import ChatSidebar from "@/components/ChatSidebar";
import Sidebar from "@/components/Sidebar";

const display = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
  axes: ["SOFT", "WONK", "opsz"],
});

const sans = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Hearth — live well on less",
  description: "An AI-native suite for households living well on less.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable}`}>
      <body>
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="min-w-0 flex-1">{children}</main>
        </div>
        <ChatSidebar />
      </body>
    </html>
  );
}
