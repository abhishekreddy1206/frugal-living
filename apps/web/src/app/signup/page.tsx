"use client";

import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { acceptInvite, signup } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";

export default function SignupPage() {
  const router = useRouter();
  const search = useSearchParams();
  const returnTo = search.get("return");
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [householdName, setHouseholdName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await signup({
        email,
        password,
        display_name: displayName,
        household_name: householdName,
      });
      // If signup came from an invite link, accept it now
      if (returnTo && returnTo.startsWith("/invite/")) {
        const token = returnTo.slice("/invite/".length);
        try {
          await acceptInvite(token);
        } catch {
          // Surface but don't block the redirect
        }
      }
      await refresh();
      router.replace(returnTo ?? "/");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm px-6 py-20">
      <h1 className="text-3xl font-bold mb-6 text-ink">Sign up</h1>
      <form onSubmit={onSubmit} className="space-y-4">
        <label className="block">
          <span className="text-xs text-stone-500">Email</span>
          <input
            type="email" required value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-stone-500">Password (min 8)</span>
          <input
            type="password" required minLength={8} value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-stone-500">Display name</span>
          <input
            required value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-stone-500">Household name</span>
          <input
            required value={householdName}
            onChange={(e) => setHouseholdName(e.target.value)}
            placeholder="The Smith household"
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </label>
        {err && (
          <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
            {err}
          </div>
        )}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper transition hover:bg-clay disabled:opacity-50"
        >
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>
      <p className="mt-6 text-sm text-stone-500">
        Already have an account?{" "}
        <Link href="/login" className="text-clay underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
