"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  createAdminFlag, deleteAdminFlag, listAdminFlags, patchAdminFlag,
} from "@/lib/api";
import type { FeatureFlag } from "@/lib/types";

export default function AdminFlagsPage() {
  const [rows, setRows] = useState<FeatureFlag[]>([]);
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reload = () => listAdminFlags().then(setRows);
  useEffect(() => { reload(); }, []);

  const create = async () => {
    setError(null);
    try {
      await createAdminFlag({ key: newKey, description: newDesc });
      setNewKey(""); setNewDesc(""); setCreating(false);
      await reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <div className="flex items-center justify-between">
        <h1 className="font-serif text-2xl text-stone-900">Feature flags</h1>
        <button
          onClick={() => setCreating(!creating)}
          className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-700"
        >
          {creating ? "Cancel" : "+ New flag"}
        </button>
      </div>

      {creating && (
        <div className="rounded-lg border border-stone-200 bg-white p-4 space-y-2">
          <input
            placeholder="key (e.g. ai.experimental.feature.enabled)"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            className="w-full rounded border border-stone-300 px-3 py-1.5 text-sm"
          />
          <input
            placeholder="description"
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            className="w-full rounded border border-stone-300 px-3 py-1.5 text-sm"
          />
          <button onClick={create} className="rounded bg-amber-600 px-3 py-1 text-sm text-white">
            Create
          </button>
          {error && <div className="text-xs text-red-700">{error}</div>}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-wider text-stone-500">
            <tr>
              <th className="px-4 py-2">Key</th>
              <th className="px-4 py-2">Description</th>
              <th className="px-4 py-2">Enabled</th>
              <th className="px-4 py-2">Rollout %</th>
              <th className="px-4 py-2">Overrides</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {rows.map((f) => (
              <tr key={f.key} className="hover:bg-stone-50">
                <td className="px-4 py-2">
                  <Link href={`/admin/flags/${encodeURIComponent(f.key)}`} className="hover:underline font-mono text-xs">
                    {f.key}
                  </Link>
                </td>
                <td className="px-4 py-2 text-stone-500">{f.description ?? "—"}</td>
                <td className="px-4 py-2">
                  <input
                    type="checkbox"
                    checked={f.enabled_globally}
                    onChange={async (e) => {
                      await patchAdminFlag(f.key, { enabled_globally: e.target.checked });
                      await reload();
                    }}
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={f.rollout_percent}
                    onChange={async (e) => {
                      await patchAdminFlag(f.key, { rollout_percent: Number(e.target.value) });
                      await reload();
                    }}
                    className="w-32"
                  />
                  <span className="ml-2 text-xs text-stone-500">{f.rollout_percent}%</span>
                </td>
                <td className="px-4 py-2 text-xs text-stone-500">
                  hh: {f.household_override_count} · user: {f.user_override_count}
                </td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={async () => {
                      if (confirm(`Delete flag ${f.key}? Soft-delete; restore is not currently supported.`)) {
                        await deleteAdminFlag(f.key);
                        await reload();
                      }
                    }}
                    className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
