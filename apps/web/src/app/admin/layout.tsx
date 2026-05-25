"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { ready, user } = useAuth();

  useEffect(() => {
    if (!ready) return;
    if (!user || (user.role !== "admin" && user.role !== "moderator")) {
      router.replace("/");
    }
  }, [ready, user, router]);

  if (!ready) {
    return <div className="p-8 text-stone-500">Loading…</div>;
  }

  if (!user || (user.role !== "admin" && user.role !== "moderator")) {
    // Redirect is in flight; render nothing to avoid flash.
    return null;
  }

  return <div className="min-h-screen">{children}</div>;
}
