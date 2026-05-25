"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ReasonModal } from "@/components/ReasonModal";
import {
  listAdminCommunities, restoreAdminCommunity, takeDownAdminCommunity,
} from "@/lib/api";
import type { AdminCommunityRow } from "@/lib/types";

export default function AdminCommunitiesPage() {
  const [rows, setRows] = useState<AdminCommunityRow[]>([]);
  const [q, setQ] = useState("");
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [modal, setModal] = useState<
    | null
    | { kind: "take-down"; row: AdminCommunityRow }
    | { kind: "restore"; row: AdminCommunityRow }
  >(null);

  const reload = () =>
    listAdminCommunities({ q: q || undefined, include_deleted: includeDeleted }).then(setRows);

  useEffect(() => { reload(); /* eslint-disable-line */ }, [includeDeleted]);

  const onConfirm = async (reason: string) => {
    if (!modal) return;
    if (modal.kind === "take-down") {
      await takeDownAdminCommunity(modal.row.id, reason);
    } else {
      await restoreAdminCommunity(modal.row.id, reason);
    }
    setModal(null);
    await reload();
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Communities</h1>

      <div className="flex items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") reload(); }}
          placeholder="Search by name"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        />
        <button onClick={() => reload()} className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white">
          Search
        </button>
        <label className="ml-4 text-sm text-stone-600">
          <input
            type="checkbox"
            checked={includeDeleted}
            onChange={(e) => setIncludeDeleted(e.target.checked)}
            className="mr-1"
          />
          Include taken-down
        </label>
      </div>

      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-wider text-stone-500">
            <tr>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Slug</th>
              <th className="px-4 py-2">Created</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {rows.map((c) => (
              <tr key={c.id} className="hover:bg-stone-50">
                <td className="px-4 py-2">
                  <Link href={`/admin/communities/${c.id}`} className="hover:underline">
                    {c.name}
                  </Link>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-stone-500">{c.slug}</td>
                <td className="px-4 py-2 text-stone-500">
                  {new Date(c.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-2">
                  {c.deleted_at ? (
                    <span className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-800">
                      Taken down
                    </span>
                  ) : (
                    <span className="text-stone-400 text-xs">live</span>
                  )}
                </td>
                <td className="px-4 py-2 text-right">
                  {c.deleted_at ? (
                    <button
                      onClick={() => setModal({ kind: "restore", row: c })}
                      className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                    >
                      Restore
                    </button>
                  ) : (
                    <button
                      onClick={() => setModal({ kind: "take-down", row: c })}
                      className="rounded bg-red-100 px-2 py-1 text-xs text-red-800 hover:bg-red-200"
                    >
                      Take down
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ReasonModal
        open={modal !== null}
        title={
          modal?.kind === "take-down" ? `Take down ${modal.row.name}` :
          modal?.kind === "restore"   ? `Restore ${modal.row.name}` : ""
        }
        actionLabel={modal?.kind === "take-down" ? "Take down" : "Restore"}
        destructive={modal?.kind === "take-down"}
        onCancel={() => setModal(null)}
        onConfirm={onConfirm}
      />
    </div>
  );
}
