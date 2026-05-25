"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { listAdminAuditLog } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";
import type { AuditLogEntry } from "@/lib/types";

interface Tile {
  href: string;
  title: string;
  description: string;
  adminOnly?: boolean;
}

const TILES: Tile[] = [
  { href: "/admin/users",       title: "Users",       description: "Search, lock, promote." },
  { href: "/admin/communities", title: "Communities", description: "Review and take down." },
  { href: "/admin/listings",    title: "Listings",    description: "Review and take down." },
  { href: "/admin/audit-log",   title: "Audit log",   description: "Every admin action, ever." },
  { href: "/admin/settings",    title: "Settings",    description: "Global, household, user.", adminOnly: true },
  { href: "/admin/flags",       title: "Flags",       description: "Feature flags + overrides.", adminOnly: true },
  { href: "/admin/banner",      title: "Banner",      description: "Public maintenance message.", adminOnly: true },
];

export default function AdminHome() {
  const { user } = useAuth();
  const role = user?.role ?? "user";
  const [recent, setRecent] = useState<AuditLogEntry[]>([]);

  useEffect(() => {
    listAdminAuditLog({ limit: 10 }).then(setRecent).catch(() => {/* nbd */});
  }, []);

  const visibleTiles = TILES.filter((t) => !t.adminOnly || role === "admin");

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-8">
      <h1 className="font-serif text-3xl text-stone-900">Admin</h1>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {visibleTiles.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className="rounded-lg border border-stone-200 bg-white p-5 transition hover:border-amber-300 hover:shadow"
          >
            <div className="font-serif text-lg text-stone-900">{t.title}</div>
            <div className="mt-1 text-sm text-stone-500">{t.description}</div>
          </Link>
        ))}
      </div>

      <section>
        <h2 className="mb-2 font-serif text-xl text-stone-900">Recent activity</h2>
        <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white">
          {recent.map((r) => (
            <li key={r.id} className="px-4 py-2 text-sm">
              <span className="font-mono text-xs text-stone-400">
                {new Date(r.created_at).toLocaleString()}
              </span>{" "}
              <span className="text-stone-800">{r.action}</span>
              {r.target_type && (
                <span className="text-stone-400"> · {r.target_type}</span>
              )}
            </li>
          ))}
          {recent.length === 0 && (
            <li className="px-4 py-3 text-sm text-stone-400">No activity yet.</li>
          )}
        </ul>
      </section>
    </div>
  );
}
