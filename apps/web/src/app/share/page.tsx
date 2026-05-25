"use client";

import { useEffect, useState } from "react";
import { getFeed, getMyCommunities } from "@/lib/api";
import type { CommunityMembership, FeedResponse } from "@/lib/types";

const CATEGORIES = [
  "all", "tools", "games", "books", "kitchen", "outdoor",
  "electronics", "furniture", "kids", "sports", "other",
] as const;

export default function SharePage() {
  const [feed, setFeed] = useState<FeedResponse | null>(null);
  const [memberships, setMemberships] = useState<CommunityMembership[]>([]);
  const [communityFilter, setCommunityFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setErr(null);
    try {
      const r = await getFeed({
        community_id: communityFilter === "all" ? undefined : communityFilter,
        category: categoryFilter === "all" ? undefined : categoryFilter,
      });
      setFeed(r);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    getMyCommunities().then((r) => setMemberships(r.memberships)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [communityFilter, categoryFilter]);

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-5xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-ink">Share</h1>
        <p className="text-stone-600 mt-1">Items neighbors and community members have offered.</p>
      </header>

      <section className="mb-6 flex flex-wrap gap-3">
        <select
          value={communityFilter}
          onChange={(e) => setCommunityFilter(e.target.value)}
          className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
        >
          <option value="all">All communities + radius</option>
          {memberships.map((m) => (
            <option key={m.community.id} value={m.community.id}>
              {m.community.name}
            </option>
          ))}
        </select>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </section>

      {err && (
        <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
          {err}
        </div>
      )}

      {feed && feed.rows.length === 0 ? (
        <p className="text-stone-500 text-sm">Nothing visible yet. Join a community or set your location to see nearby items.</p>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {feed?.rows.map((row) => (
            <li key={row.listing.id} className="rounded-lg border border-stone-200 bg-white p-4">
              <div className="font-medium text-ink">{row.listing.item.name}</div>
              <div className="text-xs text-stone-500 mt-0.5">
                {row.listing.item.category} ·{" "}
                {row.listing.allowed_exchange_types.join(" · ")}
                {row.distance_miles != null && ` · ${row.distance_miles} mi away`}
              </div>
              {row.listing.description_override && (
                <p className="text-sm text-stone-700 mt-2">{row.listing.description_override}</p>
              )}
              {row.listing.item.condition && (
                <div className="text-xs text-stone-500 mt-1">
                  Condition: {row.listing.item.condition.replace("_", " ")}
                </div>
              )}
              <div className="text-xs text-stone-400 mt-2">
                Qty available: {row.listing.quantity_available}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
