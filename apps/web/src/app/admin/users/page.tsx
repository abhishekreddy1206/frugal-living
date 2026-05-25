"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { ReasonModal } from "@/components/ReasonModal";
import { RoleBadge } from "@/components/RoleBadge";
import {
  listAdminUsers,
  lockAdminUser,
  patchAdminUserActive,
  patchAdminUserRole,
  unlockAdminUser,
} from "@/lib/api";
import type { AdminUserRow, Role } from "@/lib/types";

type ModalState =
  | null
  | { kind: "deactivate"; user: AdminUserRow }
  | { kind: "activate"; user: AdminUserRow }
  | { kind: "lock"; user: AdminUserRow }
  | { kind: "unlock"; user: AdminUserRow };

export default function AdminUsersPage() {
  const { user: me } = useAuth();
  const role: Role = me?.role ?? "user";

  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [q, setQ] = useState("");
  const [modal, setModal] = useState<ModalState>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => listAdminUsers({ q: q || undefined }).then(setUsers);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isAdmin = role === "admin";
  const adminCount = useMemo(
    () => users.filter((u) => u.role === "admin" && u.is_active).length,
    [users],
  );

  const onConfirm = async (reason: string) => {
    if (!modal) return;
    setError(null);
    try {
      if (modal.kind === "deactivate") {
        await patchAdminUserActive(modal.user.id, false, reason);
      } else if (modal.kind === "activate") {
        await patchAdminUserActive(modal.user.id, true, reason);
      } else if (modal.kind === "lock") {
        await lockAdminUser(modal.user.id, 24, reason); // 24h default
      } else if (modal.kind === "unlock") {
        await unlockAdminUser(modal.user.id, reason);
      }
      setModal(null);
      await reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  };

  const promote = async (u: AdminUserRow, newRole: Role) => {
    setError(null);
    try {
      await patchAdminUserRole(u.id, newRole);
      await reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Role change failed");
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Users</h1>

      <div className="flex items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") reload();
          }}
          placeholder="Search by email"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        />
        <button
          onClick={() => reload()}
          className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-700"
        >
          Search
        </button>
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-wider text-stone-500">
            <tr>
              <th className="px-4 py-2">Email</th>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Role</th>
              <th className="px-4 py-2">Active</th>
              <th className="px-4 py-2">Locked</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {users.map((u) => {
              const isLastAdmin =
                u.role === "admin" && u.is_active && adminCount === 1;
              const locked =
                u.locked_until && new Date(u.locked_until) > new Date();
              return (
                <tr key={u.id} className="hover:bg-stone-50">
                  <td className="px-4 py-2">
                    <Link
                      href={`/admin/users/${u.id}`}
                      className="hover:underline"
                    >
                      {u.email}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-stone-500">
                    {u.display_name ?? "—"}
                  </td>
                  <td className="px-4 py-2">
                    <RoleBadge role={u.role} />
                    {u.role === "user" && (
                      <span className="text-xs text-stone-400">user</span>
                    )}
                  </td>
                  <td className="px-4 py-2">{u.is_active ? "✓" : "—"}</td>
                  <td className="px-4 py-2 text-stone-500">
                    {locked
                      ? new Date(u.locked_until!).toLocaleString()
                      : "—"}
                  </td>
                  <td className="px-4 py-2 text-right space-x-1">
                    {isAdmin && (
                      <select
                        value={u.role}
                        disabled={isLastAdmin}
                        onChange={(e) =>
                          promote(u, e.target.value as Role)
                        }
                        className="rounded border border-stone-200 px-1 py-0.5 text-xs disabled:opacity-50"
                        title={
                          isLastAdmin
                            ? "Cannot demote the last active admin"
                            : ""
                        }
                      >
                        <option value="user">user</option>
                        <option value="moderator">moderator</option>
                        <option value="admin">admin</option>
                      </select>
                    )}
                    {u.is_active ? (
                      <button
                        onClick={() =>
                          setModal({ kind: "deactivate", user: u })
                        }
                        disabled={isLastAdmin}
                        className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200 disabled:opacity-50"
                      >
                        Deactivate
                      </button>
                    ) : (
                      <button
                        onClick={() =>
                          setModal({ kind: "activate", user: u })
                        }
                        className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                      >
                        Activate
                      </button>
                    )}
                    {locked ? (
                      <button
                        onClick={() =>
                          setModal({ kind: "unlock", user: u })
                        }
                        className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                      >
                        Unlock
                      </button>
                    ) : (
                      <button
                        onClick={() => setModal({ kind: "lock", user: u })}
                        className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                      >
                        Lock 24h
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ReasonModal
        open={modal !== null}
        title={
          modal?.kind === "deactivate"
            ? `Deactivate ${modal.user.email}`
            : modal?.kind === "activate"
              ? `Activate ${modal.user.email}`
              : modal?.kind === "lock"
                ? `Lock ${modal.user.email} for 24h`
                : modal?.kind === "unlock"
                  ? `Unlock ${modal.user.email}`
                  : ""
        }
        actionLabel={
          modal?.kind === "deactivate"
            ? "Deactivate"
            : modal?.kind === "activate"
              ? "Activate"
              : modal?.kind === "lock"
                ? "Lock"
                : modal?.kind === "unlock"
                  ? "Unlock"
                  : "Confirm"
        }
        destructive={modal?.kind === "deactivate" || modal?.kind === "lock"}
        onCancel={() => setModal(null)}
        onConfirm={onConfirm}
      />
    </div>
  );
}
