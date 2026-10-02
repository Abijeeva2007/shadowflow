import type { Metadata } from "next";
import Link from "next/link";
import {
  LayoutDashboard,
  Network,
  ShieldHalf,
  FlaskConical,
  Radio,
} from "lucide-react";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "ShadowFlow - Financial Crime Investigation",
  description:
    "Find coordinated money-laundering networks in bank transaction logs",
};

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/rings", label: "Rings", icon: Network },
  { href: "/federation", label: "Federation", icon: Radio },
  { href: "/adversary", label: "Adversary Lab", icon: FlaskConical },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-ink text-ink-text min-h-screen font-sans">
        <div className="flex min-h-screen">
          {/* ---------------- sidebar ---------------- */}
          <aside className="w-52 shrink-0 border-r border-ink-border flex flex-col sticky top-0 h-screen">
            <Link
              href="/"
              className="flex items-center gap-2 px-4 h-14 border-b border-ink-border"
            >
              <ShieldHalf size={18} className="text-risk-amber" />
              <span className="font-semibold tracking-tight">ShadowFlow</span>
            </Link>
            <nav className="flex flex-col py-2">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className="flex items-center gap-2.5 px-4 h-9 text-xs text-ink-muted hover:text-ink-text hover:bg-ink-panel transition-colors"
                >
                  <n.icon size={15} strokeWidth={1.75} />
                  {n.label}
                </Link>
              ))}
            </nav>
            <div className="mt-auto px-4 py-3 border-t border-ink-border">
              <div className="text-xxs uppercase tracking-[0.14em] text-ink-faint mb-1">
                Data
              </div>
              <div className="chip border-risk-amber/50 text-risk-amber">
                Synthetic - not real investigations
              </div>
            </div>
          </aside>

          {/* ---------------- content ---------------- */}
          <main className="flex-1 min-w-0 px-6 py-5">{children}</main>
        </div>
      </body>
    </html>
  );
}
