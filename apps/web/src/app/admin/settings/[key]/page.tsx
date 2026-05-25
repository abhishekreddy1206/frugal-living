"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  clearAdminSettingHousehold, clearAdminSettingUser, getAdminSetting,
  setAdminSettingHousehold, setAdminSettingUser,
} from "@/lib/api";
import type { SettingDetail } from "@/lib/types";

export default function AdminSettingDetailPage() {
  const { key } = useParams<{ key: string }>();
  const [detail, setDetail] = useState<SettingDetail | null>(null);
  const [newHh, setNewHh] = useState({ id: "", value: "" });
  const [newU,  setNewU]  = useState({ id: "", value: "" });

  const reload = () => getAdminSetting(decodeURIComponent(key)).then(setDetail);
  useEffect(() => { reload(); /* eslint-disable-line */ }, [key]);

  if (!detail) return <div className="p-8 text-stone-500">Loading…</div>;

  const parseValue = (raw: string): unknown => {
    if (detail.spec.type === "bool") return raw === "true" || raw === "1";
    if (detail.spec.type === "int")  return Number(raw);
    return raw;
  };

  const supportsHh = detail.spec.scopes.includes("household");
  const supportsU  = detail.spec.scopes.includes("user");

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/admin/settings" className="text-sm text-stone-500 hover:underline">
        ← Back to settings
      </Link>

      <header>
        <h1 className="font-serif text-2xl text-stone-900">{detail.key}</h1>
        <p className="text-sm text-stone-500">{detail.spec.description}</p>
        <p className="text-xs text-stone-400 mt-1">
          type {detail.spec.type} · scopes {detail.spec.scopes.join(", ")} ·{" "}
          {detail.spec.public ? "PUBLIC" : "private"}
        </p>
      </header>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <h2 className="font-serif text-base text-stone-900">Global</h2>
        <p className="mt-1">
          Current: <code>{JSON.stringify(detail.current_global)}</code>
          {detail.has_global_override ? " (overridden)" : " (registry default)"}
        </p>
      </section>

      {supportsHh && (
        <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
          <h2 className="font-serif text-base text-stone-900">
            Household overrides ({detail.household_overrides.length})
          </h2>
          <ul className="mt-2 space-y-1">
            {detail.household_overrides.map((o) => (
              <li key={o.household_id} className="flex items-center justify-between font-mono text-xs">
                <span>{o.household_id} → {JSON.stringify(o.value)}</span>
                <button
                  onClick={async () => {
                    await clearAdminSettingHousehold(detail.key, o.household_id);
                    await reload();
                  }}
                  className="rounded bg-stone-100 px-2 py-0.5 text-xs hover:bg-stone-200"
                >
                  clear
                </button>
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
            <input
              placeholder="value"
              value={newHh.value}
              onChange={(e) => setNewHh({ ...newHh, value: e.target.value })}
              className="w-32 rounded border border-stone-300 px-2 py-1 text-xs"
            />
            <button
              onClick={async () => {
                await setAdminSettingHousehold(detail.key, newHh.id, parseValue(newHh.value));
                setNewHh({ id: "", value: "" });
                await reload();
              }}
              className="rounded bg-amber-600 px-3 text-xs text-white"
            >
              Add
            </button>
          </div>
        </section>
      )}

      {supportsU && (
        <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
          <h2 className="font-serif text-base text-stone-900">
            User overrides ({detail.user_overrides.length})
          </h2>
          <ul className="mt-2 space-y-1">
            {detail.user_overrides.map((o) => (
              <li key={o.user_id} className="flex items-center justify-between font-mono text-xs">
                <span>{o.user_id} → {JSON.stringify(o.value)}</span>
                <button
                  onClick={async () => {
                    await clearAdminSettingUser(detail.key, o.user_id);
                    await reload();
                  }}
                  className="rounded bg-stone-100 px-2 py-0.5 text-xs hover:bg-stone-200"
                >
                  clear
                </button>
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
            <input
              placeholder="value"
              value={newU.value}
              onChange={(e) => setNewU({ ...newU, value: e.target.value })}
              className="w-32 rounded border border-stone-300 px-2 py-1 text-xs"
            />
            <button
              onClick={async () => {
                await setAdminSettingUser(detail.key, newU.id, parseValue(newU.value));
                setNewU({ id: "", value: "" });
                await reload();
              }}
              className="rounded bg-amber-600 px-3 text-xs text-white"
            >
              Add
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
