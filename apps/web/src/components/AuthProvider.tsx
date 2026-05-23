"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { AuthError, getMe } from "@/lib/api";
import type { AuthHousehold, AuthMembership, AuthUser } from "@/lib/types";

interface AuthState {
  ready: boolean;
  user: AuthUser | null;
  memberships: AuthMembership[];
  activeHousehold: AuthHousehold | null;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

const PUBLIC_ROUTES = new Set(["/login", "/signup"]);
function isPublicRoute(path: string): boolean {
  if (PUBLIC_ROUTES.has(path)) return true;
  if (path.startsWith("/invite/")) return true;  // /invite/[token] has its own guard
  return false;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [memberships, setMemberships] = useState<AuthMembership[]>([]);
  const [activeHousehold, setActiveHousehold] = useState<AuthHousehold | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const me = await getMe();
      setUser(me.user);
      setMemberships(me.memberships);
      setActiveHousehold(me.active_household);
    } catch (err) {
      setUser(null);
      setMemberships([]);
      setActiveHousehold(null);
      if (err instanceof AuthError && !isPublicRoute(pathname)) {
        router.replace("/login");
      }
    } finally {
      setReady(true);
    }
  }, [pathname, router]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value = useMemo<AuthState>(
    () => ({ ready, user, memberships, activeHousehold, refresh }),
    [ready, user, memberships, activeHousehold, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
