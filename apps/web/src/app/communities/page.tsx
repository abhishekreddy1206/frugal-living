"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { createCommunity, getCommunityPreview, getMyCommunities, requestToJoin } from "@/lib/api";
import type { CommunityMembership, CommunityPreview } from "@/lib/types";

export default function CommunitiesPage() {
  const [memberships, setMemberships] = useState<CommunityMembership[]>([]);
  const [findSlug, setFindSlug] = useState("");
  const [preview, setPreview] = useState<CommunityPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // New community form
  const [newSlug, setNewSlug] = useState("");
  const [newName, setNewName] = useState("");

  async function refresh() {
    try {
      const r = await getMyCommunities();
      setMemberships(r.memberships);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onFind(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setPreview(null);
    try {
      const p = await getCommunityPreview(findSlug.trim());
      setPreview(p);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function onRequest(communityId: string) {
    setBusy(true); setErr(null);
    try {
      await requestToJoin(communityId);
      const p = await getCommunityPreview(findSlug.trim());
      setPreview(p);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await createCommunity({ slug: newSlug.trim(), name: newName.trim() });
      setNewSlug(""); setNewName("");
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-4xl mx-auto">
      <header className="mb-10">
        <h1 className="text-3xl font-bold text-ink">Communities</h1>
        <p className="mt-1 text-stone-600">Groups your household shares items with.</p>
      </header>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-stone-900 mb-4">My communities</h2>
        {memberships.length === 0 ? (
          <p className="text-stone-500 text-sm">You haven&apos;t joined any communities yet.</p>
        ) : (
          <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
            {memberships.map((m) => (
              <li key={m.community.id} className="px-4 py-3">
                <Link
                  href={`/communities/${encodeURIComponent(m.community.slug)}`}
                  className="font-medium text-ink hover:text-clay"
                >
                  {m.community.name}
                </Link>
                <div className="text-xs text-stone-500 mt-0.5">
                  {m.role} · joined {new Date(m.joined_at).toLocaleDateString()}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-stone-900 mb-4">Find a community</h2>
        <form onSubmit={onFind} className="flex gap-2 mb-4">
          <input
            value={findSlug}
            onChange={(e) => setFindSlug(e.target.value)}
            placeholder="community-slug"
            className="flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={!findSlug.trim()}
            className="rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper disabled:opacity-50"
          >
            Look up
          </button>
        </form>
        {preview && (
          <div className="rounded-lg border border-stone-200 bg-white p-4">
            <div className="font-medium text-ink">{preview.name}</div>
            <div className="text-xs text-stone-500 mb-2">
              {preview.member_count} member{preview.member_count !== 1 && "s"}
            </div>
            {preview.description && <p className="text-sm text-stone-700 mb-3">{preview.description}</p>}
            {preview.your_membership_role ? (
              <Link
                href={`/communities/${encodeURIComponent(preview.slug)}`}
                className="text-sm text-clay underline"
              >
                You&apos;re already a {preview.your_membership_role}. Go to the community.
              </Link>
            ) : preview.your_join_request_status === "pending" ? (
              <p className="text-sm text-stone-500">Your request is pending.</p>
            ) : (
              <button
                onClick={() => onRequest(preview.id)}
                disabled={busy}
                className="rounded-lg bg-clay px-3 py-1.5 text-sm font-semibold text-paper disabled:opacity-50"
              >
                {busy ? "Requesting…" : "Request to join"}
              </button>
            )}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-xl font-semibold text-stone-900 mb-4">Create a community</h2>
        <form onSubmit={onCreate} className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col">
            <label htmlFor="new-slug" className="text-xs text-stone-500 mb-1">Slug</label>
            <input
              id="new-slug" value={newSlug}
              onChange={(e) => setNewSlug(e.target.value)}
              placeholder="park-slope-tools"
              className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
            />
          </div>
          <div className="flex flex-col">
            <label htmlFor="new-name" className="text-xs text-stone-500 mb-1">Name</label>
            <input
              id="new-name" value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Park Slope Tools"
              className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={!newSlug.trim() || !newName.trim()}
            className="rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper disabled:opacity-50"
          >
            Create
          </button>
        </form>
      </section>

      {err && (
        <div className="mt-6 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
          {err}
        </div>
      )}
    </div>
  );
}
