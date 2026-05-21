"use client";

import { useEffect, useState } from "react";
import { captureVideo, deleteContentItem, getContentFeed } from "@/lib/api";
import type { ContentItem } from "@/lib/types";

type Capture =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "error"; message: string };

export default function WatchPage() {
  const [items, setItems] = useState<ContentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [url, setUrl] = useState("");
  const [capture, setCapture] = useState<Capture>({ kind: "idle" });

  useEffect(() => {
    getContentFeed()
      .then((feed) => setItems(feed.items))
      .catch(() => {
        /* feed stays empty */
      })
      .finally(() => setLoading(false));
  }, []);

  async function onCapture(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setCapture({ kind: "saving" });
    try {
      const item = await captureVideo(url.trim());
      setItems((prev) => [item, ...prev.filter((i) => i.id !== item.id)]);
      setUrl("");
      setCapture({ kind: "idle" });
    } catch (err) {
      const raw = (err as Error).message;
      const message = raw.includes("422")
        ? "That doesn't look like a YouTube video link."
        : raw;
      setCapture({ kind: "error", message });
    }
  }

  async function onRemove(id: string) {
    setItems((prev) => prev.filter((i) => i.id !== id));
    try {
      await deleteContentItem(id);
    } catch {
      /* best-effort — refetch would reconcile */
    }
  }

  const saving = capture.kind === "saving";

  return (
    <div className="mx-auto max-w-5xl animate-rise-in px-6 py-12 md:px-12">
      <header className="mb-8">
        <p className="eyebrow">The library</p>
        <h1 className="mt-2 text-[40px] font-semibold leading-[1.1] text-ink">
          Watch
        </h1>
        <p className="mt-2 max-w-lg text-[15px] text-ink-soft">
          Save frugal-living videos to a tidy library. Paste a YouTube link and
          Hearth pulls in the title, channel, and thumbnail.
        </p>
      </header>

      {/* capture form */}
      <form onSubmit={onCapture} className="mb-3">
        <div className="flex flex-col gap-2.5 sm:flex-row">
          <input
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              if (capture.kind === "error") setCapture({ kind: "idle" });
            }}
            placeholder="https://www.youtube.com/watch?v=…"
            className="flex-1 rounded-xl border border-line bg-raised px-4 py-3 text-[14px] text-ink shadow-warm placeholder:text-ink-faint focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/15"
          />
          <button
            type="submit"
            disabled={saving || !url.trim()}
            className="rounded-xl bg-clay px-6 py-3 text-[14px] font-semibold text-paper shadow-warm transition hover:bg-clay-deep disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? "Saving…" : "Save video"}
          </button>
        </div>
        {capture.kind === "error" && (
          <p className="mt-2 text-[13px] text-clay-deep">{capture.message}</p>
        )}
      </form>

      <div className="rule-fade mb-8" />

      {/* feed */}
      {loading ? (
        <FeedSkeleton />
      ) : items.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <div className="mb-4 flex items-baseline justify-between">
            <p className="eyebrow">Saved</p>
            <span className="text-[12px] text-ink-faint">
              {items.length} {items.length === 1 ? "video" : "videos"}
            </span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((item) => (
              <VideoCard key={item.id} item={item} onRemove={onRemove} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function VideoCard({
  item,
  onRemove,
}: {
  item: ContentItem;
  onRemove: (id: string) => void;
}) {
  return (
    <article className="group overflow-hidden rounded-xl border border-line bg-raised shadow-warm transition-all hover:-translate-y-0.5 hover:shadow-warm-lg">
      <a
        href={item.url ?? "#"}
        target="_blank"
        rel="noreferrer"
        className="relative block aspect-video bg-crust"
      >
        {item.thumbnail_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={item.thumbnail_url}
            alt={item.title}
            className="h-full w-full object-cover"
          />
        )}
        <span className="absolute inset-0 grid place-items-center bg-ink/0 transition-colors group-hover:bg-ink/25">
          <span className="grid h-12 w-12 scale-90 place-items-center rounded-full bg-paper/95 opacity-0 shadow-warm transition-all group-hover:scale-100 group-hover:opacity-100">
            <svg viewBox="0 0 24 24" className="h-5 w-5 fill-clay" aria-hidden>
              <path d="M9.5 7.5v9l7.5-4.5-7.5-4.5Z" />
            </svg>
          </span>
        </span>
      </a>
      <div className="p-4">
        <h3 className="line-clamp-2 text-[15px] font-semibold leading-snug text-ink">
          {item.title}
        </h3>
        {item.author && (
          <p className="mt-1 text-[12px] text-ink-faint">{item.author}</p>
        )}
        <div className="mt-3 flex items-center justify-between">
          <a
            href={item.url ?? "#"}
            target="_blank"
            rel="noreferrer"
            className="text-[12px] font-semibold text-clay transition hover:text-clay-deep"
          >
            Watch on YouTube ↗
          </a>
          <button
            onClick={() => onRemove(item.id)}
            className="text-[12px] text-ink-faint opacity-0 transition hover:text-clay-deep group-hover:opacity-100"
          >
            Remove
          </button>
        </div>
      </div>
    </article>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-raised/60 px-6 py-16 text-center">
      <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-clay/10 ring-1 ring-clay/15">
        <svg viewBox="0 0 24 24" className="h-6 w-6 fill-clay" aria-hidden>
          <path d="M9.5 7.5v9l7.5-4.5-7.5-4.5Z" />
        </svg>
      </span>
      <h3 className="mt-4 text-[20px] font-semibold text-ink">
        Your library is empty
      </h3>
      <p className="mx-auto mt-1 max-w-sm text-[14px] text-ink-soft">
        Paste a YouTube link above — a frugal cooking tutorial, a preservation
        walkthrough — and it&apos;ll land here.
      </p>
    </div>
  );
}

function FeedSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="overflow-hidden rounded-xl border border-line bg-raised shadow-warm"
        >
          <div className="aspect-video animate-pulse bg-line" />
          <div className="space-y-2 p-4">
            <div className="h-4 w-5/6 animate-pulse rounded bg-line" />
            <div className="h-3 w-1/3 animate-pulse rounded bg-line" />
          </div>
        </div>
      ))}
    </div>
  );
}
