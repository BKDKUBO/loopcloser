import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "LoopCloser",
  description: "Every result has a next action, an owner, a deadline, and a documented outcome.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <Nav />
          <main id="main">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
