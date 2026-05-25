"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ReasonModal } from "@/components/ReasonModal";
import {
  listAdminListings, restoreAdminListing, takeDownAdminListing,
} from "@/lib/api";
import type { AdminListingRow } from "@/lib/types";

export default function AdminListingsPage() {
  const [rows, setRows] = useState<AdminListingRow[]>([]);
  const [q, setQ] = useState("");
  const [stat, setStat] = useState<string>("");
  const [modal, setModal] = useState<
    | null
    | { kind: "take-down"; row: AdminListingRow }
    | { kind: "restore"; row: AdminListingRow }
  >(null);

  const reload = () =>
    listAdminListings({
      q: q || undefined,
      availability_status: stat || undefined,
    }).then(setRows);

  useEffect(() => { reload(); /* eslint-disable-line */ }, [stat]);

  const onConfirm = async (reason: string) => {
    if (!modal) return;
    if (modal.kind === "take-down") await takeDownAdminListing(modal.row.id, reason);
    if (modal.kind === "restore")   await restoreAdminListing(modal.row.id, reason);
    setModal(null);
    await reload();
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Listings</h1>

      <div className="flex items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") reload(); }}
          placeholder="Search title"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        />
        <select
          value={stat}
          onChange={(e) => setStat(e.target.value)}
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        >
          <option value="">All statuses</option>
          <option value="available">available</option>
          <option value="claimed">claimed</option>
          <option value="completed">completed</option>
          <option value="removed">removed</option>
        </select>
        <button onClick={() => reload()} className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white">
          Search
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-wider text-stone-500">
            <tr>
              <th className="px-4 py-2">Title</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Household</th>
              <th className="px-4 py-2">Created</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {rows.map((l) => (
              <tr key={l.id} className="hover:bg-stone-50">
                <td className="px-4 py-2">
                  <Link href={`/admin/listings/${l.id}`} className="hover:underline">
                    {l.item_name}
                  </Link>
                </td>
                <td className="px-4 py-2 text-stone-700">{l.availability_status}</td>
                <td className="px-4 py-2 font-mono text-xs text-stone-500">
                  {l.household_id.slice(0, 8)}
                </td>
                <td className="px-4 py-2 text-stone-500">
                  {new Date(l.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-2 text-right">
                  {l.deleted_at ? (
                    <button
                      onClick={() => setModal({ kind: "restore", row: l })}
                      className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                    >
                      Restore
                    </button>
                  ) : (
                    <button
                      onClick={() => setModal({ kind: "take-down", row: l })}
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
          modal?.kind === "take-down" ? `Take down "${modal.row.item_name}"` :
          modal?.kind === "restore"   ? `Restore "${modal.row.item_name}"` : ""
        }
        actionLabel={modal?.kind === "take-down" ? "Take down" : "Restore"}
        destructive={modal?.kind === "take-down"}
        onCancel={() => setModal(null)}
        onConfirm={onConfirm}
      />
    </div>
  );
}
