"use client";

import { useEffect, useState } from "react";
import {
  generateShoppingList,
  getActiveShoppingList,
  markShoppingItemPurchased,
} from "@/lib/api";
import type { ShoppingItem, ShoppingList } from "@/lib/types";

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; list: ShoppingList | null }
  | { kind: "error"; message: string };

export default function ShoppingPage() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function refresh() {
    try {
      const list = await getActiveShoppingList();
      setStatus({ kind: "ready", list });
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleGenerate() {
    setStatus({ kind: "loading" });
    try {
      const list = await generateShoppingList();
      setStatus({ kind: "ready", list });
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  async function handlePurchased(item: ShoppingItem, price?: number) {
    try {
      await markShoppingItemPurchased(item.id, price);
      await refresh();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  const pending = status.kind === "ready" && status.list
    ? status.list.items.filter((i) => i.status === "pending")
    : [];
  const purchased = status.kind === "ready" && status.list
    ? status.list.items.filter((i) => i.status === "purchased")
    : [];

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-3xl mx-auto">
      <header className="mb-8">
        <a href="/" className="text-sm text-stone-500 hover:text-stone-700">
          ← Home
        </a>
        <h1 className="mt-3 text-3xl font-bold text-stone-900">Shopping list</h1>
        <p className="mt-1 text-stone-600">
          Built from this week&apos;s plan minus what&apos;s already in your pantry.
        </p>
      </header>

      <section className="mb-6">
        <button
          type="button"
          onClick={handleGenerate}
          disabled={status.kind === "loading"}
          className={`rounded-xl px-6 py-3 font-medium text-white shadow transition ${
            status.kind === "loading"
              ? "bg-amber-400 cursor-wait"
              : "bg-amber-600 hover:bg-amber-700"
          }`}
        >
          {status.kind === "loading" ? "Aggregating…" : "🛒 Generate from active plan"}
        </button>
      </section>

      {status.kind === "error" && (
        <div className="mb-6 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-800">
          {status.message}
        </div>
      )}

      {status.kind === "ready" && status.list && (
        <>
          <Section title={`To buy (${pending.length})`}>
            {pending.length === 0 ? (
              <p className="text-sm text-stone-500">All set — pantry covers the plan.</p>
            ) : (
              <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
                {pending.map((item) => (
                  <ShoppingRow
                    key={item.id}
                    item={item}
                    onPurchased={(p) => handlePurchased(item, p)}
                  />
                ))}
              </ul>
            )}
          </Section>
          {purchased.length > 0 && (
            <Section title={`Purchased (${purchased.length})`}>
              <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
                {purchased.map((item) => (
                  <li key={item.id} className="px-4 py-2 text-sm text-stone-500">
                    <span className="line-through">{formatQty(item)} {item.raw_name}</span>
                    {item.actual_price_usd != null && (
                      <span className="ml-2 text-stone-400">
                        ${item.actual_price_usd.toFixed(2)}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </>
      )}

      {status.kind === "ready" && !status.list && (
        <p className="text-sm text-stone-500">
          No active list. Generate one from an active meal plan.
        </p>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-600 mb-2">{title}</h2>
      {children}
    </section>
  );
}

function ShoppingRow({
  item,
  onPurchased,
}: {
  item: ShoppingItem;
  onPurchased: (price?: number) => void;
}) {
  const [price, setPrice] = useState<string>("");
  return (
    <li className="flex items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="font-medium text-stone-900 truncate">
          {formatQty(item)} {item.raw_name}
          {item.ingredient_id && (
            <span className="ml-2 text-emerald-700 text-xs">●</span>
          )}
        </div>
      </div>
      <input
        type="number"
        step="0.01"
        placeholder="$"
        value={price}
        onChange={(e) => setPrice(e.target.value)}
        className="w-20 rounded border border-stone-300 px-2 py-1 text-sm"
      />
      <button
        type="button"
        onClick={() => onPurchased(price === "" ? undefined : Number(price))}
        className="rounded-md bg-stone-900 text-white px-3 py-1.5 text-sm font-medium hover:bg-stone-700 transition"
      >
        ✓
      </button>
    </li>
  );
}

function formatQty(item: ShoppingItem): string {
  if (item.quantity == null) return "";
  return `${item.quantity} ${item.unit ?? ""}`.trim();
}
