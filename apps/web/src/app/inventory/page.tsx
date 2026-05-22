"use client";

import { useEffect, useState } from "react";
import {
  captureInventory,
  createInventoryItem,
  deleteInventoryItem,
  fileToBase64,
  listInventory,
} from "@/lib/api";
import type { InventoryItem, ItemCategory } from "@/lib/types";

const CATEGORIES: ItemCategory[] = [
  "tools",
  "games",
  "books",
  "kitchen",
  "outdoor",
  "electronics",
  "furniture",
  "kids",
  "sports",
  "other",
];

type Status =
  | { kind: "idle" }
  | { kind: "uploading" }
  | { kind: "error"; message: string }
  | { kind: "success"; created: number };

export default function InventoryPage() {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [filter, setFilter] = useState<ItemCategory | "all">("all");
  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState<ItemCategory>("other");

  async function refresh() {
    try {
      const data = await listInventory(filter === "all" ? undefined : filter);
      setItems(data);
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  async function handleFile(file: File) {
    setStatus({ kind: "uploading" });
    try {
      const { base64, mediaType } = await fileToBase64(file);
      const resp = await captureInventory(base64, mediaType);
      setStatus({ kind: "success", created: resp.created_count });
      await refresh();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  async function handleAdd() {
    const name = newName.trim();
    if (!name) return;
    try {
      await createInventoryItem({ name, category: newCategory });
      setNewName("");
      setNewCategory("other");
      await refresh();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteInventoryItem(id);
      await refresh();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  const isUploading = status.kind === "uploading";

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-4xl mx-auto">
      <header className="mb-10">
        <h1 className="text-3xl font-bold text-ink">Inventory</h1>
        <p className="mt-1 text-stone-600">
          Catalog what your household owns — games, tools, books, gear.
        </p>
      </header>

      <section className="mb-8">
        <label
          htmlFor="inventory-photo"
          className={`flex flex-col items-center justify-center gap-2 cursor-pointer rounded-xl border-2 border-dashed p-10 transition ${
            isUploading
              ? "border-amber-400 bg-amber-50"
              : "border-stone-300 bg-white hover:border-amber-400"
          }`}
        >
          <span className="text-4xl">📦</span>
          <span className="text-stone-700 font-medium">
            {isUploading ? "Reading photo with Claude…" : "Tap to capture or upload"}
          </span>
          <span className="text-xs text-stone-500">
            A shelf of games, a tool pegboard, a bookcase
          </span>
          <input
            id="inventory-photo"
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            disabled={isUploading}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
              e.target.value = "";
            }}
          />
        </label>

        {status.kind === "error" && (
          <div className="mt-4 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-800">
            {status.message}
          </div>
        )}
        {status.kind === "success" && (
          <div className="mt-4 rounded-md bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-800">
            Added {status.created} {status.created === 1 ? "item" : "items"} to your
            inventory.
          </div>
        )}
      </section>

      <section className="mb-10 flex flex-wrap items-end gap-3">
        <div className="flex flex-col">
          <label htmlFor="new-name" className="text-xs text-stone-500 mb-1">
            Item name
          </label>
          <input
            id="new-name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="DeWalt 20V drill"
            className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </div>
        <div className="flex flex-col">
          <label htmlFor="new-category" className="text-xs text-stone-500 mb-1">
            Category
          </label>
          <select
            id="new-category"
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value as ItemCategory)}
            className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={handleAdd}
          disabled={!newName.trim()}
          className="rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper transition hover:bg-clay disabled:opacity-50"
        >
          Add item
        </button>
      </section>

      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-stone-900">
            Your inventory ({items.length})
          </h2>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as ItemCategory | "all")}
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm"
          >
            <option value="all">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        {items.length === 0 ? (
          <p className="text-stone-500 text-sm">
            Nothing yet. Capture a photo or add an item to start.
          </p>
        ) : (
          <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
            {items.map((item) => (
              <li
                key={item.id}
                className="flex items-center justify-between px-4 py-3"
              >
                <div>
                  <div className="font-medium text-stone-900">
                    {item.name}
                    {item.quantity > 1 && (
                      <span className="text-stone-500"> ×{item.quantity}</span>
                    )}
                  </div>
                  <div className="text-xs text-stone-500 mt-0.5">
                    {item.category}
                    {item.condition && ` · ${item.condition.replace("_", " ")}`}
                    {item.location && ` · ${item.location}`}
                    {item.tags.length > 0 && ` · ${item.tags.join(", ")}`}
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(item.id)}
                  className="text-xs text-stone-400 hover:text-red-600 transition"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
