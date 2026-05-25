import type { Role } from "@/lib/types";

const STYLES: Record<Role, string> = {
  admin: "bg-amber-200 text-amber-900",
  moderator: "bg-stone-200 text-stone-800",
  user: "bg-transparent text-stone-500",
};

const LABELS: Record<Role, string> = {
  admin: "ADMIN",
  moderator: "MOD",
  user: "",
};

export function RoleBadge({ role }: { role: Role }) {
  if (role === "user") return null;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wider ${STYLES[role]}`}
    >
      {LABELS[role]}
    </span>
  );
}
