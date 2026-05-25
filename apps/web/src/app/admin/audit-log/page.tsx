"use client";
import { useEffect, useState } from "react";

import { listAdminAuditLog } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/types";

const PAGE_SIZE = 50;

export default function AuditLogPage() {
  const [rows, setRows] = useState<AuditLogEntry[]>([]);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [actionPrefix, setActionPrefix] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const reload = () =>
    listAdminAuditLog({
      actor_user_id: actor || undefined,
      action: action || undefined,
      action_prefix: actionPrefix || undefined,
      limit: PAGE_SIZE, offset,
    }).then(setRows);

  useEffect(() => { reload(); /* eslint-disable-line */ }, [offset]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Audit log</h1>

      <div className="flex flex-wrap items-center gap-2">
        <input
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          placeholder="actor user UUID"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm font-mono"
        />
        <input
          value={action}
          onChange={(e) => setAction(e.target.value)}
          placeholder="exact action"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        />
        <input
          value={actionPrefix}
          onChange={(e) => setActionPrefix(e.target.value)}
          placeholder="action prefix (e.g. admin.user)"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        />
        <button onClick={() => { setOffset(0); reload(); }} className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white">
          Filter
        </button>
      </div>

      <div className="rounded-lg border border-stone-200 bg-white">
        <ul className="divide-y divide-stone-100 text-sm">
          {rows.length === 0 && <li className="p-4 text-stone-400">No entries.</li>}
          {rows.map((r) => (
            <li key={r.id} className="px-4 py-2">
              <button
                onClick={() => toggle(r.id)}
                className="w-full text-left"
              >
                <div className="flex items-baseline justify-between gap-4">
                  <div className="text-stone-800">{r.action}</div>
                  <div className="text-xs text-stone-400">
                    {new Date(r.created_at).toLocaleString()}
                  </div>
                </div>
                <div className="text-xs text-stone-500">
                  actor <span className="font-mono">{r.actor_user_id?.slice(0, 8) ?? "—"}</span>
                  {r.target_type && (
                    <> · target {r.target_type}{" "}
                      <span className="font-mono">{r.target_id?.slice(0, 8)}</span>
                    </>
                  )}
                </div>
              </button>
              {expanded.has(r.id) && (
                <pre className="mt-2 max-h-60 overflow-auto rounded bg-stone-50 px-2 py-1 text-[11px] text-stone-700">
                  {JSON.stringify(r.payload, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </div>

      <div className="flex items-center justify-between text-sm">
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          className="rounded border border-stone-300 px-3 py-1 disabled:opacity-50"
        >
          ← Prev
        </button>
        <span className="text-stone-500">offset {offset}</span>
        <button
          disabled={rows.length < PAGE_SIZE}
          onClick={() => setOffset(offset + PAGE_SIZE)}
          className="rounded border border-stone-300 px-3 py-1 disabled:opacity-50"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
