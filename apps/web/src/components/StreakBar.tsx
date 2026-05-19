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

  const interesting = streaks.filter((s) => s.current_length > 0 || s.longest_length > 0);
  if (interesting.length === 0 && badges.length === 0) return null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {interesting.length > 0 && (
        <div className="rounded-xl border border-stone-200 bg-white p-4">
          <div className="text-xs uppercase tracking-wide text-stone-500 mb-2">Streaks</div>
          <ul className="space-y-1.5 text-sm">
            {interesting.map((s) => (
              <li key={s.kind} className="flex items-center justify-between">
                <span className="text-stone-700">{STREAK_LABELS[s.kind] ?? s.kind}</span>
                <span className="text-stone-900 font-medium">
                  {s.current_length}
                  {s.longest_length > s.current_length && (
                    <span className="text-stone-400 text-xs ml-1">
                      (best: {s.longest_length})
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {badges.length > 0 && (
        <div className="rounded-xl border border-stone-200 bg-white p-4">
          <div className="text-xs uppercase tracking-wide text-stone-500 mb-2">
            Badges ({badges.length})
          </div>
          <ul className="space-y-1.5 text-sm">
            {badges.slice(0, 5).map((b) => (
              <li key={b.key} className="flex items-center gap-2">
                <span>🏅</span>
                <div className="min-w-0">
                  <div className="text-stone-900 font-medium truncate">{b.name}</div>
                  {b.description && (
                    <div className="text-xs text-stone-500 truncate">{b.description}</div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
