import Link from "next/link";
import BriefingCard from "@/components/BriefingCard";
import StreakBar from "@/components/StreakBar";

const TOOLS = [
  {
    href: "/pantry",
    n: "01",
    title: "Pantry",
    desc: "Snap a photo of your shelves — Claude builds the inventory.",
  },
  {
    href: "/stretch",
    n: "02",
    title: "Recipe stretcher",
    desc: "Recipes built around what you already have on hand.",
  },
  {
    href: "/plan",
    n: "03",
    title: "Meal plan",
    desc: "A budget-aware week of dinners, optimized end to end.",
  },
  {
    href: "/shopping",
    n: "04",
    title: "Shopping list",
    desc: "Your meal plan, minus whatever the pantry already covers.",
  },
  {
    href: "/preservation",
    n: "05",
    title: "Preservation",
    desc: "Can, ferment, and freeze — with USDA-aligned safety.",
  },
  {
    href: "/waste",
    n: "06",
    title: "Waste & savings",
    desc: "See what cooking from the pantry saved you this month.",
  },
];

export default function Home() {
  const today = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="mx-auto max-w-5xl animate-rise-in px-6 py-12 md:px-12">
      {/* masthead */}
      <header className="mb-10">
        <p className="eyebrow">{today}</p>
        <h1 className="mt-2 text-[40px] font-semibold leading-[1.1] text-ink md:text-[48px]">
          Good to see you.
        </h1>
        <p className="mt-2 max-w-md text-[15px] text-ink-soft">
          Here&apos;s where things stand in your kitchen today.
        </p>
      </header>

      <div className="mb-10">
        <BriefingCard />
      </div>

      <div className="mb-10">
        <StreakBar />
      </div>

      {/* the kitchen */}
      <section className="mb-10">
        <div className="mb-4 flex items-baseline justify-between">
          <p className="eyebrow">The kitchen</p>
          <span className="text-[12px] text-ink-faint">6 tools</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {TOOLS.map((t) => (
            <Link
              key={t.href}
              href={t.href}
              className="group rounded-xl border border-line bg-raised p-5 shadow-warm transition-all hover:-translate-y-0.5 hover:border-clay/40 hover:shadow-warm-lg"
            >
              <div className="flex items-start justify-between">
                <span className="font-display text-[13px] tracking-wide text-ink-faint">
                  {t.n}
                </span>
                <span className="text-ink-faint transition-all group-hover:translate-x-0.5 group-hover:text-clay">
                  →
                </span>
              </div>
              <h3 className="mt-3 text-[19px] font-semibold text-ink">
                {t.title}
              </h3>
              <p className="mt-1 text-[13px] leading-relaxed text-ink-soft">
                {t.desc}
              </p>
            </Link>
          ))}
        </div>
      </section>

      {/* the library — featured: the new Watch feature */}
      <section>
        <p className="eyebrow mb-4">The library</p>
        <Link
          href="/watch"
          className="group flex items-center gap-5 overflow-hidden rounded-2xl border border-line bg-raised p-6 shadow-warm transition-all hover:-translate-y-0.5 hover:border-clay/40 hover:shadow-warm-lg"
        >
          <span className="grid h-16 w-16 shrink-0 place-items-center rounded-2xl bg-clay/10 ring-1 ring-clay/15">
            <svg viewBox="0 0 24 24" className="h-7 w-7 fill-clay" aria-hidden>
              <path d="M9.5 7.5v9l7.5-4.5-7.5-4.5Z" />
            </svg>
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-[21px] font-semibold text-ink">Watch</h3>
              <span className="rounded-full bg-ember/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-clay-deep">
                New
              </span>
            </div>
            <p className="mt-1 text-[14px] leading-relaxed text-ink-soft">
              Paste a YouTube link and Hearth saves it to a tidy library of
              frugal-living videos to revisit.
            </p>
          </div>
          <span className="hidden text-ink-faint transition-all group-hover:translate-x-1 group-hover:text-clay sm:block">
            →
          </span>
        </Link>
      </section>
    </div>
  );
}
