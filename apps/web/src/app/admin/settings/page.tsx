"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  clearAdminSettingGlobal, listAdminSettings, setAdminSettingGlobal,
} from "@/lib/api";
import type { GlobalSettingRow } from "@/lib/types";

function ValueWidget({
  row, onSave,
}: { row: GlobalSettingRow; onSave: (v: unknown) => Promise<void> }) {
  const [local, setLocal] = useState<unknown>(row.current_global);

  const commit = async () => {
    let v = local;
    if (row.spec.type === "int")  v = Number(v);
    if (row.spec.type === "bool") v = Boolean(v);
    await onSave(v);
  };

  if (row.spec.type === "bool") {
    return (
      <input
        type="checkbox"
        checked={Boolean(local)}
        onChange={async (e) => { setLocal(e.target.checked); await onSave(e.target.checked); }}
      />
    );
  }
  if (row.spec.type === "int") {
    return (
      <div className="flex gap-1">
        <input
          type="number"
          value={String(local ?? "")}
          onChange={(e) => setLocal(e.target.value)}
          className="w-24 rounded border border-stone-300 px-2 py-0.5 text-sm"
        />
        <button onClick={commit} className="rounded bg-amber-600 px-2 text-xs text-white">save</button>
      </div>
    );
  }
  return (
    <div className="flex gap-1">
      <input
        type="text"
        value={String(local ?? "")}
        onChange={(e) => setLocal(e.target.value)}
        className="w-48 rounded border border-stone-300 px-2 py-0.5 text-sm"
      />
      <button onClick={commit} className="rounded bg-amber-600 px-2 text-xs text-white">save</button>
    </div>
  );
}

export default function AdminSettingsPage() {
  const [rows, setRows] = useState<GlobalSettingRow[]>([]);

  const reload = () => listAdminSettings().then(setRows);
  useEffect(() => { reload(); }, []);

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Settings</h1>
      <p className="text-sm text-stone-500">
        Globals are editable here. Click a key to manage per-household / per-user overrides.
      </p>

      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-wider text-stone-500">
            <tr>
              <th className="px-4 py-2">Key</th>
              <th className="px-4 py-2">Type</th>
              <th className="px-4 py-2">Scopes</th>
              <th className="px-4 py-2">Global value</th>
              <th className="px-4 py-2">Overrides</th>
              <th className="px-4 py-2 text-right">Reset</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {rows.map((row) => (
              <tr key={row.key} className="hover:bg-stone-50">
                <td className="px-4 py-2">
                  <Link href={`/admin/settings/${encodeURIComponent(row.key)}`} className="hover:underline">
                    {row.key}
                  </Link>
                  <div className="text-xs text-stone-400">{row.spec.description}</div>
                </td>
                <td className="px-4 py-2 text-stone-500">{row.spec.type}</td>
                <td className="px-4 py-2 text-stone-500 text-xs">{row.spec.scopes.join(", ")}</td>
                <td className="px-4 py-2">
                  {row.spec.scopes.includes("global") ? (
                    <ValueWidget
                      row={row}
                      onSave={async (v) => {
                        await setAdminSettingGlobal(row.key, v);
                        await reload();
                      }}
                    />
                  ) : (
                    <span className="text-stone-400 text-xs">no global scope</span>
                  )}
                </td>
                <td className="px-4 py-2 text-stone-500 text-xs">
                  hh: {row.household_override_count} · user: {row.user_override_count}
                </td>
                <td className="px-4 py-2 text-right">
                  {row.has_global_override && (
                    <button
                      onClick={async () => { await clearAdminSettingGlobal(row.key); await reload(); }}
                      className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                    >
                      Clear
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
