"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ReasonModal } from "@/components/ReasonModal";
import {
  getAdminCommunity, restoreAdminCommunity, takeDownAdminCommunity,
} from "@/lib/api";
import type { AdminCommunityDetail } from "@/lib/types";

export default function AdminCommunityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [c, setC] = useState<AdminCommunityDetail | null>(null);
  const [modal, setModal] = useState<null | "take-down" | "restore">(null);
  const reload = () => getAdminCommunity(id).then(setC);

  useEffect(() => { reload(); /* eslint-disable-line */ }, [id]);

  if (!c) return <div className="p-8 text-stone-500">Loading…</div>;

  const onConfirm = async (reason: string) => {
    if (modal === "take-down") await takeDownAdminCommunity(id, reason);
    if (modal === "restore")   await restoreAdminCommunity(id, reason);
    setModal(null);
    await reload();
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/admin/communities" className="text-sm text-stone-500 hover:underline">
        ← Back to communities
      </Link>
      <header className="flex items-start justify-between">
        <div>
          <h1 className="font-serif text-2xl text-stone-900">{c.name}</h1>
          <p className="text-sm text-stone-500 font-mono">{c.slug}</p>
        </div>
        {c.deleted_at ? (
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
          <dt className="text-stone-500">Status</dt>
          <dd>{c.deleted_at ? `Taken down ${new Date(c.deleted_at).toLocaleString()}` : "Live"}</dd>
          <dt className="text-stone-500">Members</dt><dd>{c.member_count}</dd>
          <dt className="text-stone-500">Listings</dt><dd>{c.listing_count}</dd>
          <dt className="text-stone-500">Created</dt><dd>{new Date(c.created_at).toLocaleString()}</dd>
          <dt className="text-stone-500">Creator</dt>
          <dd className="font-mono text-xs">{c.created_by_user_id}</dd>
        </dl>
      </section>

      <ReasonModal
        open={modal !== null}
        title={modal === "take-down" ? `Take down ${c.name}` : `Restore ${c.name}`}
        actionLabel={modal === "take-down" ? "Take down" : "Restore"}
        destructive={modal === "take-down"}
        onCancel={() => setModal(null)}
        onConfirm={onConfirm}
      />
    </div>
  );
}
