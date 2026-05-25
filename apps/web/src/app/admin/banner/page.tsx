"use client";
import { useEffect, useState } from "react";

import {
  clearAdminSettingGlobal, getAdminSetting, setAdminSettingGlobal,
} from "@/lib/api";

export default function AdminBannerPage() {
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getAdminSetting("maintenance_message").then((d) => {
      setMessage(String(d.current_global ?? ""));
    });
  }, []);

  const save = async () => {
    await setAdminSettingGlobal("maintenance_message", message);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const clear = async () => {
    await clearAdminSettingGlobal("maintenance_message");
    setMessage("");
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Maintenance banner</h1>
      <p className="text-sm text-stone-500">
        Non-empty text shows as a banner across every page (public — no auth needed).
      </p>

      <textarea
        rows={4}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="e.g. Scheduled maintenance Sun 2am UTC"
        className="w-full rounded border border-stone-300 px-3 py-2 text-sm"
      />

      <div className="flex items-center gap-3">
        <button onClick={save} className="rounded bg-amber-600 px-4 py-1.5 text-sm text-white">
          Save
        </button>
        <button onClick={clear} className="rounded bg-stone-100 px-4 py-1.5 text-sm">
          Clear
        </button>
        {saved && <span className="text-xs text-green-700">Saved ✓</span>}
      </div>

      <section>
        <h2 className="mb-2 font-serif text-base text-stone-900">Preview</h2>
        {message ? (
          <div className="w-full rounded border border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900">
            {message}
          </div>
        ) : (
          <p className="text-xs text-stone-400">Empty — no banner shown.</p>
        )}
      </section>
    </div>
  );
}
