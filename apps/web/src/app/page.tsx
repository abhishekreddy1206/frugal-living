export default function Home() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-10">
      <h1 className="text-4xl font-bold text-stone-900">frugal-living</h1>
      <p className="mt-2 text-stone-600">An AI-native suite for living well on less.</p>
      <p className="mt-8 text-sm text-stone-500">
        Tier A in progress · Pantry · Recipes · Meal Planning · Curated Feed · Voice
      </p>

      <section className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-4 w-full max-w-3xl">
        <a
          href="/pantry"
          className="rounded-lg border border-stone-200 bg-white p-5 hover:border-stone-400 transition"
        >
          <div className="text-lg font-semibold">📷 Capture pantry</div>
          <p className="text-sm text-stone-600 mt-1">Snap a photo of your shelves.</p>
        </a>
        <a
          href="/stretch"
          className="rounded-lg border border-stone-200 bg-white p-5 hover:border-stone-400 transition"
        >
          <div className="text-lg font-semibold">🍳 Stretch my pantry</div>
          <p className="text-sm text-stone-600 mt-1">What can I make right now?</p>
        </a>
        <a
          href="/plan"
          className="rounded-lg border border-stone-200 bg-white p-5 hover:border-stone-400 transition"
        >
          <div className="text-lg font-semibold">📅 Plan my week</div>
          <p className="text-sm text-stone-600 mt-1">Budget-aware meal plan.</p>
        </a>
        <a
          href="/feed"
          className="rounded-lg border border-stone-200 bg-white p-5 hover:border-stone-400 transition"
        >
          <div className="text-lg font-semibold">📰 Today&apos;s feed</div>
          <p className="text-sm text-stone-600 mt-1">Curated frugal-living finds.</p>
        </a>
      </section>
    </div>
  );
}
