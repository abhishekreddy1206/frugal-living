import "./globals.css";
import type { Metadata } from "next";
import ChatSidebar from "@/components/ChatSidebar";

export const metadata: Metadata = {
  title: "Frugal Living",
  description: "Live well on less.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="flex min-h-screen">
          <main className="flex-1">{children}</main>
          <ChatSidebar />
        </div>
      </body>
    </html>
  );
}
