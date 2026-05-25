"use client";

import { useState } from "react";
import { setHouseholdLocation } from "@/lib/api";

export default function LocationSetup({ onSaved }: { onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [manualLat, setManualLat] = useState("");
  const [manualLng, setManualLng] = useState("");
  const [showManual, setShowManual] = useState(false);

  async function useBrowserLocation() {
    if (!navigator.geolocation) {
      setShowManual(true);
      return;
    }
    setBusy(true); setErr(null);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          await setHouseholdLocation({
            lat: pos.coords.latitude, lng: pos.coords.longitude,
          });
          onSaved();
        } catch (e) {
          setErr((e as Error).message);
        } finally {
          setBusy(false);
        }
      },
      () => {
        setShowManual(true);
        setBusy(false);
      },
      { enableHighAccuracy: false, timeout: 8000 },
    );
  }

  async function saveManual(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await setHouseholdLocation({
        lat: parseFloat(manualLat), lng: parseFloat(manualLng),
      });
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm">
      <div className="font-medium text-amber-900 mb-1">Set your household&apos;s location</div>
      <p className="text-amber-800 mb-3">
        We use this only to compute distance to other households in your share radius.
        Nobody sees your exact address — only distance, rounded to the tenth of a mile.
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          onClick={useBrowserLocation}
          disabled={busy}
          className="rounded-md bg-ink px-3 py-1.5 text-xs font-semibold text-paper disabled:opacity-50"
        >
          {busy ? "Detecting…" : "Use my browser location"}
        </button>
        <button
          onClick={() => setShowManual((v) => !v)}
          className="rounded-md border border-amber-300 bg-white px-3 py-1.5 text-xs text-amber-900"
        >
          Enter coordinates manually
        </button>
      </div>
      {showManual && (
        <form onSubmit={saveManual} className="mt-3 flex flex-wrap items-end gap-2">
          <label className="text-xs text-amber-900">
            Lat
            <input
              value={manualLat}
              onChange={(e) => setManualLat(e.target.value)}
              required step="0.0001" type="number"
              className="ml-1 w-28 rounded-md border border-amber-300 bg-white px-2 py-1 text-sm"
            />
          </label>
          <label className="text-xs text-amber-900">
            Lng
            <input
              value={manualLng}
              onChange={(e) => setManualLng(e.target.value)}
              required step="0.0001" type="number"
              className="ml-1 w-28 rounded-md border border-amber-300 bg-white px-2 py-1 text-sm"
            />
          </label>
          <button
            type="submit" disabled={busy || !manualLat || !manualLng}
            className="rounded-md bg-ink px-3 py-1 text-xs font-semibold text-paper disabled:opacity-50"
          >
            Save
          </button>
        </form>
      )}
      {err && <div className="mt-2 text-xs text-red-700">{err}</div>}
    </div>
  );
}
