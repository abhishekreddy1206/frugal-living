"use client";

import { useEffect, useState } from "react";
import {
  captureInventory, createInventoryItem, deleteInventoryItem, fileToBase64,
  listInventory, createListing, getMyCommunities, listMyListings,
} from "@/lib/api";
import type {
  InventoryItem, ItemCategory, Listing, CommunityMembership, ExchangeType,
} from "@/lib/types";

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
  const [myListings, setMyListings] = useState<Listing[]>([]);
  const [memberships, setMemberships] = useState<CommunityMembership[]>([]);
  const [shareModal, setShareModal] = useState<InventoryItem | null>(null);

  async function refreshAll() {
    try {
      const [items, listings, comms] = await Promise.all([
        listInventory(filter === "all" ? undefined : filter),
        listMyListings(),
        getMyCommunities(),
      ]);
      setItems(items);
      setMyListings(listings);
      setMemberships(comms.memberships);
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  useEffect(() => {
    refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  async function handleFile(file: File) {
    setStatus({ kind: "uploading" });
    try {
      const { base64, mediaType } = await fileToBase64(file);
      const resp = await captureInventory(base64, mediaType);
      setStatus({ kind: "success", created: resp.created_count });
      await refreshAll();
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
      await refreshAll();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteInventoryItem(id);
      await refreshAll();
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
                <div className="flex items-center gap-2">
                  {myListings.some((l) => l.item.id === item.id) ? (
                    <span className="text-[11px] rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 px-2 py-0.5">
                      Shared
                    </span>
                  ) : (
                    <button
                      onClick={() => setShareModal(item)}
                      className="text-xs rounded-md border border-stone-300 bg-white px-2 py-1 text-stone-700 hover:bg-stone-50"
                    >
                      Share
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(item.id)}
                    className="text-xs text-stone-400 hover:text-red-600 transition"
                  >
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {shareModal && (
        <ShareModal
          item={shareModal}
          memberships={memberships}
          onClose={() => setShareModal(null)}
          onShared={async () => { setShareModal(null); await refreshAll(); }}
        />
      )}
    </div>
  );
}

function ShareModal({
  item, memberships, onClose, onShared,
}: {
  item: InventoryItem;
  memberships: CommunityMembership[];
  onClose: () => void;
  onShared: () => Promise<void>;
}) {
  const [types, setTypes] = useState<ExchangeType[]>(["borrow"]);
  const [quantity, setQuantity] = useState<number>(Math.min(1, item.quantity));
  const [selectedCommunities, setSelectedCommunities] = useState<Set<string>>(
    new Set(memberships.map((m) => m.community.id)),
  );
  const [shareInRadius, setShareInRadius] = useState<boolean>(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function toggleType(t: ExchangeType) {
    setTypes((prev) => prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]);
  }

  function toggleCommunity(id: string) {
    setSelectedCommunities((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await createListing({
        item_id: item.id,
        allowed_exchange_types: types,
        quantity_available: quantity,
        community_ids: Array.from(selectedCommunities),
        share_in_radius: shareInRadius,
      });
      await onShared();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-xl font-semibold text-ink mb-1">Share &ldquo;{item.name}&rdquo;</h2>
        <p className="text-xs text-stone-500 mb-4">
          Choose who can see this and how you&apos;re willing to share.
        </p>

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <div className="text-xs text-stone-500 mb-1">Offer for</div>
            <div className="flex gap-2 text-sm">
              {(["borrow", "swap", "gift"] as ExchangeType[]).map((t) => (
                <label key={t} className="inline-flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={types.includes(t)}
                    onChange={() => toggleType(t)}
                  />
                  {t}
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs text-stone-500 mb-1">Quantity available</label>
            <input
              type="number"
              min={1}
              max={item.quantity}
              value={quantity}
              onChange={(e) => setQuantity(Math.max(1, Math.min(item.quantity, Number(e.target.value))))}
              className="w-24 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
            />
            <span className="ml-2 text-xs text-stone-500">of {item.quantity}</span>
          </div>

          {memberships.length > 0 && (
            <div>
              <div className="text-xs text-stone-500 mb-1">
                Visible in these communities (uncheck to exclude)
              </div>
              <div className="space-y-1">
                {memberships.map((m) => (
                  <label key={m.community.id} className="inline-flex items-center gap-1.5 mr-3 text-sm">
                    <input
                      type="checkbox"
                      checked={selectedCommunities.has(m.community.id)}
                      onChange={() => toggleCommunity(m.community.id)}
                    />
                    {m.community.name}
                  </label>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={shareInRadius}
                onChange={(e) => setShareInRadius(e.target.checked)}
              />
              Also share with households within ~5 miles of yours
            </label>
            <p className="ml-6 text-[11px] text-stone-500 mt-0.5">
              Off by default. Nearby households see distance only — never your exact address.
            </p>
          </div>

          {err && (
            <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
              {err}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button" onClick={onClose}
              className="rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm text-stone-700"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || types.length === 0 || (selectedCommunities.size === 0 && !shareInRadius)}
              className="rounded-md bg-ink px-3 py-1.5 text-sm font-semibold text-paper disabled:opacity-50"
            >
              {busy ? "Sharing…" : "Share"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
