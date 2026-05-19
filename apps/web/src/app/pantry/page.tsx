"use client";

import { useEffect, useState } from "react";
import { capturePantry, fileToBase64, listPantry } from "@/lib/api";
import type { PantryItem } from "@/lib/types";

type Status =
  | { kind: "idle" }
  | { kind: "uploading" }
  | { kind: "error"; message: string }
  | { kind: "success"; created: number };

export default function PantryPage() {
  const [items, setItems] = useState<PantryItem[]>([]);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  async function refresh() {
    try {
      const data = await listPantry();
      setItems(data);
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleFile(file: File) {
    setStatus({ kind: "uploading" });
    setPreviewUrl(URL.createObjectURL(file));
    try {
      const { base64, mediaType } = await fileToBase64(file);
      const resp = await capturePantry(base64, mediaType);
      setStatus({ kind: "success", created: resp.created_count });
      await refresh();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  const isUploading = status.kind === "uploading";

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-4xl mx-auto">
      <header className="mb-10">
        <a href="/" className="text-sm text-stone-500 hover:text-stone-700">
          ← Home
        </a>
        <h1 className="mt-3 text-3xl font-bold text-stone-900">Pantry</h1>
        <p className="mt-1 text-stone-600">
          Snap a photo of your shelves. Claude identifies every item.
        </p>
      </header>

      <section className="mb-12">
        <label
          htmlFor="pantry-photo"
          className={`flex flex-col items-center justify-center gap-2 cursor-pointer rounded-xl border-2 border-dashed p-10 transition ${
            isUploading
              ? "border-amber-400 bg-amber-50"
              : "border-stone-300 bg-white hover:border-amber-400"
          }`}
        >
          <span className="text-4xl">📷</span>
          <span className="text-stone-700 font-medium">
            {isUploading ? "Reading photo with Claude…" : "Tap to capture or upload"}
          </span>
          <span className="text-xs text-stone-500">
            JPEG, PNG, or HEIC · stored only in this request
          </span>
          <input
            id="pantry-photo"
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

        {previewUrl && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={previewUrl}
            alt="Last capture"
            className="mt-4 max-h-64 rounded-lg shadow border border-stone-200"
          />
        )}

        {status.kind === "error" && (
          <div className="mt-4 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-800">
            {status.message}
          </div>
        )}
        {status.kind === "success" && (
          <div className="mt-4 rounded-md bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-800">
            Added {status.created} {status.created === 1 ? "item" : "items"} to your pantry.
          </div>
        )}
      </section>

      <section>
        <h2 className="text-xl font-semibold text-stone-900 mb-4">
          In your pantry ({items.length})
        </h2>
        {items.length === 0 ? (
          <p className="text-stone-500 text-sm">
            Nothing yet. Capture a photo to start your inventory.
          </p>
        ) : (
          <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
            {items.map((item) => (
              <PantryRow key={item.id} item={item} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function PantryRow({ item }: { item: PantryItem }) {
  const expiresSoon = isExpiringSoon(item.expires_at);
  return (
    <li className="flex items-center justify-between px-4 py-3">
      <div>
        <div className="font-medium text-stone-900">{item.raw_name}</div>
        <div className="text-xs text-stone-500 mt-0.5">
          {item.quantity != null && `${item.quantity} ${item.unit ?? ""} · `}
          {item.source.replace("_", " ")}
          {item.confidence != null && ` · ${Math.round(item.confidence * 100)}%`}
        </div>
      </div>
      {item.expires_at && (
        <span
          className={`text-xs px-2 py-1 rounded-md ${
            expiresSoon
              ? "bg-red-50 text-red-700 border border-red-200"
              : "bg-stone-100 text-stone-600"
          }`}
        >
          {expiresSoon ? "Expires " : "by "}
          {formatDate(item.expires_at)}
        </span>
      )}
    </li>
  );
}

function isExpiringSoon(iso: string | null): boolean {
  if (!iso) return false;
  const diff = (new Date(iso).getTime() - Date.now()) / (1000 * 60 * 60 * 24);
  return diff <= 3;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}
