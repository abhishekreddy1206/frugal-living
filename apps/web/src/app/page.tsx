import BriefingCard from "@/components/BriefingCard";
import StreakBar from "@/components/StreakBar";

export default function Home() {
  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-5xl mx-auto">
      <header className="mb-10">
        <h1 className="text-4xl font-bold text-stone-900">frugal-living</h1>
        <p className="mt-2 text-stone-600">An AI-native suite for living well on less.</p>
      </header>

      <section className="mb-6">
        <BriefingCard />
      </section>

      <section className="mb-10">
        <StreakBar />
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Tile href="/pantry" icon="📷" title="Capture pantry" sub="Snap a photo of your shelves." />
        <Tile href="/stretch" icon="🍳" title="Stretch my pantry" sub="What can I make right now?" />
        <Tile href="/plan" icon="📅" title="Plan my week" sub="Budget-aware meal plan." />
        <Tile href="/shopping" icon="🛒" title="Shopping list" sub="Plan minus pantry." />
        <Tile href="/preservation" icon="🥫" title="Preservation" sub="Cans, ferments, freezer prep." />
        <Tile href="/waste" icon="📊" title="Waste &amp; savings" sub="What you saved this month." />
      </section>
    </div>
  );
}

function Tile({ href, icon, title, sub }: { href: string; icon: string; title: string; sub: string }) {
  return (
    <a
      href={href}
      className="rounded-lg border border-stone-200 bg-white p-5 hover:border-stone-400 transition"
    >
      <div className="text-lg font-semibold">
        {icon} {title}
      </div>
      <p className="text-sm text-stone-600 mt-1">{sub}</p>
    </a>
  );
}
