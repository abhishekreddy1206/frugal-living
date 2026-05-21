"use client";

import { useEffect, useState } from "react";
import { getBadges, getStreaks } from "@/lib/api";
import type { BadgeAward, Streak } from "@/lib/types";

const STREAK_LABELS: Record<string, string> = {
  cooked_from_pantry: "Cooked from pantry",
  zero_waste_week: "Zero-waste weeks",
  meal_planned_week: "Weeks planned",
};

export default function StreakBar() {
  const [streaks, setStreaks] = useState<Streak[]>([]);
  const [badges, setBadges] = useState<BadgeAward[]>([]);

  useEffect(() => {
    Promise.all([getStreaks(), getBadges()])
      .then(([s, b]) => {
        setStreaks(s);
        setBadges(b);
      })
      .catch(() => {
        /* silent — home should still render */
      });
  }, []);

  const interesting = streaks.filter(
    (s) => s.current_length > 0 || s.longest_length > 0,
  );
  if (interesting.length === 0 && badges.length === 0) return null;

  return (
    <section>
      <p className="eyebrow mb-3">Momentum</p>
      <div className="flex flex-wrap gap-3">
        {interesting.map((s) => (
          <div
            key={s.kind}
            className="min-w-[150px] flex-1 rounded-xl border border-line bg-raised p-4 shadow-warm"
          >
            <div className="flex items-baseline gap-1.5">
              <span className="font-display text-3xl font-semibold text-clay">
                {s.current_length}
              </span>
              {s.longest_length > s.current_length && (
                <span className="text-[11px] text-ink-faint">
                  best {s.longest_length}
                </span>
              )}
            </div>
            <div className="mt-0.5 text-[13px] text-ink-soft">
              {STREAK_LABELS[s.kind] ?? s.kind}
            </div>
          </div>
        ))}
        {badges.slice(0, 4).map((b) => (
          <div
            key={b.key}
            className="flex min-w-[150px] flex-1 items-center gap-2.5 rounded-xl border border-line bg-raised p-4 shadow-warm"
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ember/15 text-base">
              🏅
            </span>
            <div className="min-w-0">
              <div className="truncate text-[13px] font-semibold text-ink">
                {b.name}
              </div>
              {b.description && (
                <div className="truncate text-[11px] text-ink-faint">
                  {b.description}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
