"use client";

import { useEffect, useState } from "react";
import { getSavingsRollup, logWaste } from "@/lib/api";
import type { PantryItem, SavingsRollup } from "@/lib/types";

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; rollup: SavingsRollup }
  | { kind: "error"; message: string };

export default function WastePage() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [form, setForm] = useState<{ name: string; quantity: string; unit: string; reason: string }>(
    { name: "", quantity: "", unit: "", reason: "spoiled" },
  );

  async function refresh() {
    try {
      const rollup = await getSavingsRollup();
      setStatus({ kind: "ready", rollup });
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleLog(item?: PantryItem) {
    try {
      await logWaste(
        item
          ? {
              pantryItemId: item.id,
              ingredientName: item.raw_name,
              quantity: item.quantity ?? undefined,
              unit: item.unit ?? undefined,
              reason: "spoiled",
            }
          : {
              ingredientName: form.name,
              quantity: form.quantity === "" ? undefined : Number(form.quantity),
              unit: form.unit || undefined,
              reason: form.reason as "spoiled" | "forgotten" | "over_cooked" | "over_purchased" | "other",
            },
      );
      if (!item) setForm({ name: "", quantity: "", unit: "", reason: "spoiled" });
      await refresh();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-3xl mx-auto">
      <header className="mb-8">
        <a href="/" className="text-sm text-stone-500 hover:text-stone-700">
          ← Home
        </a>
        <h1 className="mt-3 text-3xl font-bold text-stone-900">Waste &amp; savings</h1>
        <p className="mt-1 text-stone-600">
          Tracks what got eaten versus what got tossed. Aim for net positive.
        </p>
      </header>

      {status.kind === "ready" && (
        <section className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-8">
          <Stat
            label="Cooked from pantry"
            value={`$${status.rollup.cooked_from_pantry_value_usd.toFixed(2)}`}
            sub={`${status.rollup.cooked_meals_count} meals`}
            tone="emerald"
          />
          <Stat
            label="Wasted"
            value={`$${status.rollup.waste_value_usd.toFixed(2)}`}
            sub={`${status.rollup.waste_events_count} events`}
            tone="red"
          />
          <Stat
            label={`Net (${status.rollup.period_days}d)`}
            value={`$${status.rollup.net_savings_usd.toFixed(2)}`}
            sub={status.rollup.net_savings_usd >= 0 ? "in your favor" : "deficit"}
            tone={status.rollup.net_savings_usd >= 0 ? "amber" : "red"}
          />
        </section>
      )}

      {status.kind === "ready" && status.rollup.expiring_soon.length > 0 && (
        <section className="mb-8">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-600 mb-2">
            Expiring within 3 days
          </h2>
          <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
            {status.rollup.expiring_soon.map((item) => (
              <li key={item.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <div className="font-medium text-stone-900">{item.raw_name}</div>
                  <div className="text-xs text-stone-500">
                    {item.quantity != null && `${item.quantity} ${item.unit ?? ""} · `}
                    expires {item.expires_at}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleLog(item)}
                  className="rounded-md bg-red-50 text-red-700 border border-red-200 px-2 py-1 text-xs font-medium hover:bg-red-100 transition"
                >
                  Tossed
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-600 mb-2">
          Log waste manually
        </h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.name.trim()) return;
            handleLog();
          }}
          className="rounded-xl border border-stone-200 bg-white p-4 grid grid-cols-1 md:grid-cols-5 gap-2"
        >
          <input
            type="text"
            placeholder="What got wasted"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="md:col-span-2 rounded border border-stone-300 px-2 py-1 text-sm"
          />
          <input
            type="number"
            placeholder="Qty"
            step="0.1"
            value={form.quantity}
            onChange={(e) => setForm({ ...form, quantity: e.target.value })}
            className="rounded border border-stone-300 px-2 py-1 text-sm"
          />
          <input
            type="text"
            placeholder="Unit"
            value={form.unit}
            onChange={(e) => setForm({ ...form, unit: e.target.value })}
            className="rounded border border-stone-300 px-2 py-1 text-sm"
          />
          <select
            value={form.reason}
            onChange={(e) => setForm({ ...form, reason: e.target.value })}
            className="rounded border border-stone-300 px-2 py-1 text-sm"
          >
            <option value="spoiled">Spoiled</option>
            <option value="forgotten">Forgotten</option>
            <option value="over_cooked">Over-cooked</option>
            <option value="over_purchased">Over-purchased</option>
            <option value="other">Other</option>
          </select>
          <button
            type="submit"
            className="md:col-span-5 rounded-md bg-stone-900 text-white py-2 text-sm font-medium hover:bg-stone-700 transition"
          >
            Log waste
          </button>
        </form>
      </section>

      {status.kind === "error" && (
        <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-800">
          {status.message}
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  tone: "emerald" | "red" | "amber";
}) {
  const styles: Record<typeof tone, string> = {
    emerald: "bg-emerald-50 border-emerald-200 text-emerald-900",
    red: "bg-red-50 border-red-200 text-red-900",
    amber: "bg-amber-50 border-amber-200 text-amber-900",
  };
  return (
    <div className={`rounded-xl border p-4 ${styles[tone]}`}>
      <div className="text-xs uppercase tracking-wide opacity-70">{label}</div>
      <div className="text-2xl font-bold mt-1">{value}</div>
      <div className="text-xs opacity-70 mt-1">{sub}</div>
    </div>
  );
}
