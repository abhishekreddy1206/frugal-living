"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ReasonModal } from "@/components/ReasonModal";
import {
  getAdminListing, restoreAdminListing, takeDownAdminListing,
} from "@/lib/api";
import type { AdminListingDetail } from "@/lib/types";

export default function AdminListingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [l, setL] = useState<AdminListingDetail | null>(null);
  const [modal, setModal] = useState<null | "take-down" | "restore">(null);
  const reload = () => getAdminListing(id).then(setL);

  useEffect(() => { reload(); /* eslint-disable-line */ }, [id]);

  if (!l) return <div className="p-8 text-stone-500">Loading…</div>;

  // AdminListingDetail has no title field; use description or a fallback.
  const displayTitle = l.description ?? `Listing ${l.id.slice(0, 8)}`;

  const onConfirm = async (reason: string) => {
    if (modal === "take-down") await takeDownAdminListing(id, reason);
    if (modal === "restore")   await restoreAdminListing(id, reason);
    setModal(null);
    await reload();
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/admin/listings" className="text-sm text-stone-500 hover:underline">
        ← Back to listings
      </Link>

      <header className="flex items-start justify-between">
        <div>
          <h1 className="font-serif text-2xl text-stone-900">{displayTitle}</h1>
          <p className="text-sm text-stone-500">
            Status: {l.availability_status} ·{" "}
            {l.deleted_at ? "Taken down" : "Live"}
          </p>
        </div>
        {l.deleted_at ? (
          <button
            onClick={() => setModal("restore")}
            className="rounded bg-stone-100 px-3 py-1.5 text-sm hover:bg-stone-200"
          >
            Restore
          </button>
        ) : (
          <button
            onClick={() => setModal("take-down")}
            className="rounded bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
          >
            Take down
          </button>
        )}
      </header>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <dl className="grid grid-cols-2 gap-y-2">
          <dt className="text-stone-500">Description</dt><dd>{l.description ?? "—"}</dd>
          <dt className="text-stone-500">Item</dt>
          <dd className="font-mono text-xs">{l.item_id}</dd>
          <dt className="text-stone-500">Exchange types</dt>
          <dd>{l.allowed_exchange_types.join(", ")}</dd>
          <dt className="text-stone-500">Qty available</dt>
          <dd>{l.quantity_available}</dd>
          <dt className="text-stone-500">Created</dt>
          <dd>{new Date(l.created_at).toLocaleString()}</dd>
          {l.deleted_at && (
            <>
              <dt className="text-stone-500">Taken down</dt>
              <dd>{new Date(l.deleted_at).toLocaleString()}</dd>
            </>
          )}
        </dl>
      </section>

      <section>
        <h2 className="mb-2 font-serif text-lg text-stone-900">
          Shared with ({l.shared_with_communities.length})
        </h2>
        <ul className="space-y-1 font-mono text-xs text-stone-500">
          {l.shared_with_communities.length === 0 && (
            <li className="text-stone-400">None — radius visibility only.</li>
          )}
          {l.shared_with_communities.map((cid) => (
            <li key={cid}>
              <Link href={`/admin/communities/${cid}`} className="hover:underline">
                {cid}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <ReasonModal
        open={modal !== null}
        title={modal === "take-down" ? `Take down "${displayTitle}"` : `Restore "${displayTitle}"`}
        actionLabel={modal === "take-down" ? "Take down" : "Restore"}
        destructive={modal === "take-down"}
        onCancel={() => setModal(null)}
        onConfirm={onConfirm}
      />
    </div>
  );
}
