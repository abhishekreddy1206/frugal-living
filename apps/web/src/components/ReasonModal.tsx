"use client";
import { useState } from "react";

interface Props {
  open: boolean;
  title: string;
  actionLabel: string;
  destructive?: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void | Promise<void>;
}

export function ReasonModal({
  open, title, actionLabel, destructive, onCancel, onConfirm,
}: Props) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const trimmed = reason.trim();
  const valid = trimmed.length >= 3;

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      await onConfirm(trimmed);
      setReason("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-xl text-stone-900">{title}</h2>
        <label className="mt-4 block text-sm font-medium text-stone-700">
          Reason (required, min 3 chars)
        </label>
        <textarea
          autoFocus
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded border border-stone-300 px-3 py-2 text-sm focus:border-amber-400 focus:outline-none"
          placeholder="Why are you doing this?"
        />
        <div className="mt-5 flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded px-4 py-2 text-sm text-stone-600 hover:bg-stone-100"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!valid || busy}
            className={`rounded px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50 ${
              destructive
                ? "bg-red-600 hover:bg-red-700"
                : "bg-amber-600 hover:bg-amber-700"
            }`}
          >
            {busy ? "…" : actionLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
