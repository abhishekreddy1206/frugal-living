"use client";

import { useEffect, useState } from "react";
import { getTodaysBriefing, markBriefingRead, regenerateBriefing } from "@/lib/api";
import type { Briefing } from "@/lib/types";

export default function BriefingCard() {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getTodaysBriefing()
      .then((b) => {
        if (!cancelled) setBriefing(b);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function refresh() {
    setLoading(true);
    try {
      const b = await regenerateBriefing();
      setBriefing(b);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function dismiss() {
    if (!briefing) return;
    try {
      const b = await markBriefingRead(briefing.id);
      setBriefing(b);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (loading && !briefing) {
    return (
      <div className="rounded-xl bg-amber-50 border border-amber-200 p-4 text-sm text-amber-800">
        Loading today&apos;s briefing…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl bg-red-50 border border-red-200 p-4 text-sm text-red-800">
        {error}
      </div>
    );
  }

  if (!briefing) return null;

  return (
    <div
      className={`rounded-xl border p-5 transition ${
        briefing.was_read
          ? "bg-stone-50 border-stone-200 opacity-60"
          : "bg-amber-50 border-amber-200"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-lg font-semibold text-stone-900">
          {briefing.headline ?? "Today"}
        </h2>
        <div className="flex gap-2 shrink-0">
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="text-xs text-stone-500 hover:text-stone-700"
            title="Regenerate"
          >
            ↻
          </button>
          {!briefing.was_read && (
            <button
              type="button"
              onClick={dismiss}
              className="text-xs text-stone-500 hover:text-stone-700"
              title="Dismiss"
            >
              ✓
            </button>
          )}
        </div>
      </div>
      <div className="mt-2 text-sm text-stone-700 whitespace-pre-line">
        {briefing.body_markdown}
      </div>
    </div>
  );
}
