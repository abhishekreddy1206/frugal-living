"use client";

import { useEffect, useState } from "react";
import { getTodaysBriefing, markBriefingRead, regenerateBriefing } from "@/lib/api";
import type { Briefing } from "@/lib/types";

/** Minimal markdown — bold spans + paragraphs. The briefing only uses these. */
function renderBody(md: string) {
  return md
    .split(/\n{2,}|\n/)
    .filter((p) => p.trim())
    .map((para, i) => (
      <p key={i} className="text-[15px] leading-relaxed text-ink-soft">
        {para.split(/(\*\*[^*]+\*\*)/g).map((seg, j) =>
          seg.startsWith("**") && seg.endsWith("**") ? (
            <strong key={j} className="font-semibold text-ink">
              {seg.slice(2, -2)}
            </strong>
          ) : (
            <span key={j}>{seg}</span>
          ),
        )}
      </p>
    ));
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Today";
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

export default function BriefingCard() {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getTodaysBriefing()
      .then((b) => !cancelled && setBriefing(b))
      .catch((err) => !cancelled && setError((err as Error).message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  async function refresh() {
    setLoading(true);
    try {
      setBriefing(await regenerateBriefing());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function dismiss() {
    if (!briefing) return;
    try {
      setBriefing(await markBriefingRead(briefing.id));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (loading && !briefing) {
    return (
      <div className="rounded-2xl border border-line bg-raised p-6 shadow-warm">
        <div className="eyebrow">From the hearth</div>
        <div className="mt-3 h-5 w-2/3 animate-pulse rounded bg-line" />
        <div className="mt-3 h-4 w-full animate-pulse rounded bg-line" />
        <div className="mt-2 h-4 w-4/5 animate-pulse rounded bg-line" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-clay/30 bg-clay/[0.06] p-5 text-sm text-clay-deep">
        Couldn&apos;t load today&apos;s briefing — {error}
      </div>
    );
  }

  if (!briefing) return null;

  return (
    <article
      className={`relative overflow-hidden rounded-2xl border border-line bg-raised shadow-warm transition ${
        briefing.was_read ? "opacity-70" : ""
      }`}
    >
      <span
        className={`absolute inset-y-0 left-0 w-1 ${
          briefing.was_read ? "bg-line" : "bg-ember"
        }`}
      />
      <div className="p-6 pl-7">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="eyebrow">From the hearth</div>
            <p className="mt-1 text-[12px] text-ink-faint">
              {formatDate(briefing.for_date)}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              title="Regenerate"
              className="grid h-8 w-8 place-items-center rounded-lg text-ink-faint transition hover:bg-paper hover:text-ink disabled:opacity-40"
            >
              <span className={loading ? "inline-block animate-spin" : ""}>↻</span>
            </button>
            {!briefing.was_read && (
              <button
                type="button"
                onClick={dismiss}
                title="Mark read"
                className="grid h-8 w-8 place-items-center rounded-lg text-ink-faint transition hover:bg-paper hover:text-moss"
              >
                ✓
              </button>
            )}
          </div>
        </div>

        <h2 className="mt-3 max-w-xl text-[26px] font-semibold leading-snug text-ink">
          {briefing.headline ?? "Today"}
        </h2>

        <div className="mt-3 space-y-2.5">{renderBody(briefing.body_markdown)}</div>
      </div>
    </article>
  );
}
