"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout, switchHousehold } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";

type NavItem = { href: string; label: string };
type NavSection = { title: string; items: NavItem[] };

const SECTIONS: NavSection[] = [
  {
    title: "Overview",
    items: [{ href: "/", label: "Today" }],
  },
  {
    title: "Kitchen",
    items: [
      { href: "/pantry", label: "Pantry" },
      { href: "/stretch", label: "Recipe stretcher" },
      { href: "/plan", label: "Meal plan" },
      { href: "/shopping", label: "Shopping list" },
      { href: "/preservation", label: "Preservation" },
      { href: "/waste", label: "Waste & savings" },
    ],
  },
  {
    title: "Household",
    items: [{ href: "/inventory", label: "Inventory" }],
  },
  {
    title: "Community",
    items: [
      { href: "/share", label: "Share" },
      { href: "/communities", label: "Communities" },
    ],
  },
  {
    title: "Library",
    items: [{ href: "/watch", label: "Watch" }],
  },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-line bg-crust">
      {/* wordmark */}
      <div className="px-6 pb-5 pt-7">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-clay shadow-warm">
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="#fffdf7" aria-hidden>
              <path d="M8 2C5 5 4 7 4 9.2A4 4 0 0 0 12 9.2C12 7 11 5 8 2Z" />
            </svg>
          </span>
          <span className="font-display text-[26px] font-semibold leading-none text-ink">
            Hearth
          </span>
        </Link>
        <p className="eyebrow mt-2.5 pl-[2px]">Live well on less</p>
      </div>

      <div className="mx-6 rule-fade" />

      {/* navigation */}
      <nav className="flex-1 overflow-y-auto px-4 py-5">
        {SECTIONS.map((section) => (
          <div key={section.title} className="mb-6 last:mb-0">
            <p className="eyebrow mb-2 px-3">{section.title}</p>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const active = pathname === item.href;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`group relative flex items-center gap-2.5 rounded-lg px-3 py-[9px] text-[13.5px] transition-colors ${
                        active
                          ? "bg-raised font-semibold text-clay shadow-warm"
                          : "text-ink-soft hover:bg-paper/70 hover:text-ink"
                      }`}
                    >
                      {active && (
                        <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-clay" />
                      )}
                      <span
                        className={`h-[5px] w-[5px] shrink-0 rounded-full transition-colors ${
                          active
                            ? "bg-clay"
                            : "bg-ink-faint group-hover:bg-ink-soft"
                        }`}
                      />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* footer */}
      <SidebarFooter />
    </aside>
  );
}

function SidebarFooter() {
  const { user, memberships, activeHousehold, refresh } = useAuth();
  const router = useRouter();

  async function onSwitch(id: string) {
    try {
      await switchHousehold(id);
      await refresh();
      router.refresh();
    } catch {
      /* noop — guard will redirect on auth errors */
    }
  }

  async function onLogout() {
    try {
      await logout();
    } finally {
      await refresh();
      router.replace("/login");
    }
  }

  if (!user) {
    return (
      <div className="border-t border-line px-6 py-4">
        <p className="text-[11px] text-ink-faint">Hearth v0.1 · pre-launch</p>
      </div>
    );
  }

  return (
    <div className="border-t border-line px-6 py-4 space-y-2">
      <div className="text-[12px] text-ink-soft">
        <div className="font-medium text-ink">{activeHousehold?.name ?? "—"}</div>
        <div className="text-[11px] text-ink-faint">{user.email}</div>
      </div>
      {memberships.length > 1 && (
        <select
          value={activeHousehold?.id ?? ""}
          onChange={(e) => onSwitch(e.target.value)}
          className="w-full rounded-md border border-line bg-paper px-2 py-1 text-[12px]"
        >
          {memberships.map((m) => (
            <option key={m.household.id} value={m.household.id}>
              {m.household.name}
            </option>
          ))}
        </select>
      )}
      <button
        onClick={onLogout}
        className="w-full rounded-md border border-line bg-paper px-2 py-1 text-[12px] text-ink-soft hover:bg-raised"
      >
        Log out
      </button>
    </div>
  );
}
