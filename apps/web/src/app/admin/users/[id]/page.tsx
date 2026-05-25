"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { RoleBadge } from "@/components/RoleBadge";
import { getAdminUser, listAdminAuditLog } from "@/lib/api";
import type { AdminUserDetail, AuditLogEntry } from "@/lib/types";

export default function AdminUserDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [user, setUser] = useState<AdminUserDetail | null>(null);
  const [audit, setAudit] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAdminUser(id).then(setUser).catch((e) => setError(String(e)));
    listAdminAuditLog({ limit: 50 })
      .then((rows) => setAudit(rows.filter((r) => r.target_id === id)))
      .catch(() => {/* nbd */});
  }, [id]);

  if (error) return <div className="p-8 text-red-700">{error}</div>;
  if (!user) return <div className="p-8 text-stone-500">Loading…</div>;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/admin/users" className="text-sm text-stone-500 hover:underline">
        ← Back to users
      </Link>

      <header>
        <h1 className="font-serif text-2xl text-stone-900">
          {user.display_name ?? user.email} <RoleBadge role={user.role} />
        </h1>
        <p className="text-sm text-stone-500">{user.email}</p>
      </header>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <dl className="grid grid-cols-2 gap-y-2">
          <dt className="text-stone-500">Role</dt><dd>{user.role}</dd>
          <dt className="text-stone-500">Active</dt><dd>{user.is_active ? "Yes" : "No"}</dd>
          <dt className="text-stone-500">Locked until</dt>
          <dd>{user.locked_until ? new Date(user.locked_until).toLocaleString() : "—"}</dd>
          <dt className="text-stone-500">Joined</dt>
          <dd>{new Date(user.created_at).toLocaleString()}</dd>
          <dt className="text-stone-500">Listings owned</dt><dd>{user.listing_count}</dd>
        </dl>
      </section>

      <section>
        <h2 className="mb-2 font-serif text-lg text-stone-900">Households</h2>
        <ul className="space-y-1 text-sm">
          {user.household_memberships.length === 0 && <li className="text-stone-400">None</li>}
          {user.household_memberships.map((m) => (
            <li key={m.household_id}>
              <span className="font-mono text-xs text-stone-400">{m.household_id}</span>
              <span className="ml-2 text-stone-700">{m.role}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="mb-2 font-serif text-lg text-stone-900">Recent audit ({audit.length})</h2>
        <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white text-sm">
          {audit.length === 0 && <li className="px-4 py-2 text-stone-400">No entries yet.</li>}
          {audit.map((r) => (
            <li key={r.id} className="px-4 py-2">
              <div className="text-xs text-stone-400">
                {new Date(r.created_at).toLocaleString()} ·{" "}
                <span className="font-mono">{r.actor_user_id?.slice(0, 8)}</span>
              </div>
              <div className="text-stone-800">{r.action}</div>
              {r.payload && Object.keys(r.payload).length > 0 && (
                <pre className="mt-1 max-h-32 overflow-auto rounded bg-stone-50 px-2 py-1 text-[11px] text-stone-600">
                  {JSON.stringify(r.payload, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
