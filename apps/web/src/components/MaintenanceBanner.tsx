"use client";
import { useEffect, useState } from "react";
import { getRuntimeConfig } from "@/lib/api";

export function MaintenanceBanner() {
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    getRuntimeConfig()
      .then((cfg) => setMessage(cfg.maintenance_message ?? ""))
      .catch(() => {/* silent — no banner on fetch failure */});
  }, []);

  if (!message) return null;

  return (
    <div className="w-full border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900">
      {message}
    </div>
  );
}
