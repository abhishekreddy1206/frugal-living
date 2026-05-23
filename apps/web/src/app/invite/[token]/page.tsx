"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { acceptInvite, AuthError, previewInvite } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";
import type { InvitePreview as InvitePreviewT } from "@/lib/types";

export default function InvitePage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const router = useRouter();
  const { user, ready, refresh } = useAuth();
  const [preview, setPreview] = useState<InvitePreviewT | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // If not authed once auth state is ready, send to signup with a return path.
  useEffect(() => {
    if (ready && !user) {
      router.replace(`/signup?return=/invite/${token}`);
    }
  }, [ready, user, router, token]);

  // Load the preview once authenticated.
  useEffect(() => {
    if (!user) return;
    previewInvite(token)
      .then(setPreview)
      .catch((e) => {
        if (e instanceof AuthError) return; // guard handles
        setError((e as Error).message);
      });
  }, [user, token]);

  async function onAccept() {
    setBusy(true);
    setError(null);
    try {
      await acceptInvite(token);
      await refresh();
      router.replace("/");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!ready || !user) return null;

  return (
    <div className="mx-auto max-w-md px-6 py-20">
      <h1 className="text-2xl font-bold mb-4 text-ink">Household invite</h1>
      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}
      {preview && (
        <>
          <p className="mb-2 text-stone-700">
            {preview.inviter_name ?? "Someone"} invited you to join{" "}
            <span className="font-semibold">{preview.household_name}</span> as{" "}
            <span className="font-mono">{preview.role}</span>.
          </p>
          <button
            onClick={onAccept}
            disabled={busy}
            className="mt-4 w-full rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper transition hover:bg-clay disabled:opacity-50"
          >
            {busy ? "Accepting…" : "Accept invite"}
          </button>
        </>
      )}
    </div>
  );
}
