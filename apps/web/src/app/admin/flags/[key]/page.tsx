"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  getAdminFlag, setAdminFlagHouseholdOverride, setAdminFlagUserOverride,
} from "@/lib/api";
import type { FeatureFlagDetail } from "@/lib/types";

export default function AdminFlagDetailPage() {
  const { key } = useParams<{ key: string }>();
  const [flag, setFlag] = useState<FeatureFlagDetail | null>(null);
  const [newHh, setNewHh] = useState({ id: "", enabled: true });
  const [newU,  setNewU]  = useState({ id: "", enabled: true });

  const reload = () => getAdminFlag(decodeURIComponent(key)).then(setFlag);
  useEffect(() => { reload(); /* eslint-disable-line */ }, [key]);

  if (!flag) return <div className="p-8 text-stone-500">Loading…</div>;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/admin/flags" className="text-sm text-stone-500 hover:underline">
        ← Back to flags
      </Link>

      <header>
        <h1 className="font-serif text-2xl text-stone-900 font-mono break-all">{flag.key}</h1>
        <p className="text-sm text-stone-500">{flag.description ?? "—"}</p>
      </header>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <dl className="grid grid-cols-2 gap-y-2">
          <dt className="text-stone-500">Global enabled</dt>
          <dd>{flag.enabled_globally ? "yes" : "no"}</dd>
          <dt className="text-stone-500">Rollout %</dt>
          <dd>{flag.rollout_percent}</dd>
        </dl>
      </section>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <h2 className="font-serif text-base text-stone-900">
          Household overrides ({flag.household_overrides.length})
        </h2>
        <ul className="mt-2 space-y-1">
          {flag.household_overrides.map((o) => (
            <li key={o.id} className="font-mono text-xs">
              {o.household_id} → {o.enabled ? "ON" : "OFF"}
            </li>
          ))}
        </ul>
        <div className="mt-3 flex gap-2">
          <input
            placeholder="household UUID"
            value={newHh.id}
            onChange={(e) => setNewHh({ ...newHh, id: e.target.value })}
            className="flex-1 rounded border border-stone-300 px-2 py-1 text-xs font-mono"
          />
          <select
            value={String(newHh.enabled)}
            onChange={(e) => setNewHh({ ...newHh, enabled: e.target.value === "true" })}
            className="rounded border border-stone-300 px-2 py-1 text-xs"
          >
            <option value="true">ON</option>
            <option value="false">OFF</option>
          </select>
          <button
            onClick={async () => {
              await setAdminFlagHouseholdOverride(flag.key, newHh.id, newHh.enabled);
              setNewHh({ id: "", enabled: true });
              await reload();
            }}
            className="rounded bg-amber-600 px-3 text-xs text-white"
          >
            Add
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <h2 className="font-serif text-base text-stone-900">
          User overrides ({flag.user_overrides.length})
        </h2>
        <ul className="mt-2 space-y-1">
          {flag.user_overrides.map((o) => (
            <li key={o.id} className="font-mono text-xs">
              {o.user_id} → {o.enabled ? "ON" : "OFF"}
            </li>
          ))}
        </ul>
        <div className="mt-3 flex gap-2">
          <input
            placeholder="user UUID"
            value={newU.id}
            onChange={(e) => setNewU({ ...newU, id: e.target.value })}
            className="flex-1 rounded border border-stone-300 px-2 py-1 text-xs font-mono"
          />
          <select
            value={String(newU.enabled)}
            onChange={(e) => setNewU({ ...newU, enabled: e.target.value === "true" })}
            className="rounded border border-stone-300 px-2 py-1 text-xs"
          >
            <option value="true">ON</option>
            <option value="false">OFF</option>
          </select>
          <button
            onClick={async () => {
              await setAdminFlagUserOverride(flag.key, newU.id, newU.enabled);
              setNewU({ id: "", enabled: true });
              await reload();
            }}
            className="rounded bg-amber-600 px-3 text-xs text-white"
          >
            Add
          </button>
        </div>
      </section>
    </div>
  );
}
