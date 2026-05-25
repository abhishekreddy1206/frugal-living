"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  approveJoinRequest,
  declineJoinRequest,
  getCommunityPreview,
  leaveCommunity,
  listJoinRequests,
} from "@/lib/api";
import type { CommunityPreview, JoinRequest } from "@/lib/types";

export default function CommunityDetailPage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const [preview, setPreview] = useState<CommunityPreview | null>(null);
  const [requests, setRequests] = useState<JoinRequest[]>([]);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setErr(null);
    try {
      const p = await getCommunityPreview(slug);
      setPreview(p);
      if (p.your_membership_role === "owner") {
        const r = await listJoinRequests(p.id);
        setRequests(r);
      } else {
        setRequests([]);
      }
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    load();
  }, [slug]);

  async function onApprove(requestId: string) {
    if (!preview) return;
    await approveJoinRequest(preview.id, requestId);
    await load();
  }

  async function onDecline(requestId: string) {
    if (!preview) return;
    await declineJoinRequest(preview.id, requestId);
    await load();
  }

  async function onLeave() {
    if (!preview) return;
    if (!confirm("Leave this community?")) return;
    try {
      await leaveCommunity(preview.id);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (!preview) {
    return <div className="px-6 py-10 text-stone-500">{err ?? "Loading…"}</div>;
  }

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-4xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-ink">{preview.name}</h1>
        <p className="text-xs text-stone-500 mt-1">
          {preview.member_count} member{preview.member_count !== 1 && "s"} ·{" "}
          {preview.your_membership_role ?? "not a member"}
        </p>
        {preview.description && (
          <p className="mt-3 text-stone-700">{preview.description}</p>
        )}
      </header>

      {preview.your_membership_role && (
        <button
          onClick={onLeave}
          className="rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm text-stone-700 hover:bg-stone-50 mb-8"
        >
          Leave community
        </button>
      )}

      {preview.your_membership_role === "owner" && (
        <section>
          <h2 className="text-xl font-semibold text-stone-900 mb-4">
            Pending join requests ({requests.length})
          </h2>
          {requests.length === 0 ? (
            <p className="text-stone-500 text-sm">No pending requests.</p>
          ) : (
            <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
              {requests.map((r) => (
                <li key={r.id} className="flex items-center justify-between px-4 py-3">
                  <div className="text-sm text-stone-700">
                    Request from <span className="font-mono">{r.user_id.slice(0, 8)}…</span>{" "}
                    on {new Date(r.requested_at).toLocaleDateString()}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => onApprove(r.id)}
                      className="rounded-md bg-ink px-3 py-1 text-xs font-semibold text-paper"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => onDecline(r.id)}
                      className="rounded-md border border-stone-300 bg-white px-3 py-1 text-xs text-stone-700"
                    >
                      Decline
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {err && (
        <div className="mt-6 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
          {err}
        </div>
      )}
    </div>
  );
}
