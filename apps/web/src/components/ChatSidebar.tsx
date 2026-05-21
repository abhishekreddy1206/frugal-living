"use client";

import { useState } from "react";

type Msg = { role: "user" | "assistant"; content: string };

function Flame({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="currentColor" aria-hidden>
      <path d="M8 2C5 5 4 7 4 9.2A4 4 0 0 0 12 9.2C12 7 11 5 8 2Z" />
    </svg>
  );
}

/**
 * Always-available Hearth chat. Collapsed to a pill by default so it never
 * crowds the page. Stub — wire to POST /api/v1/ai/conversations/{id}/messages.
 */
export default function ChatSidebar() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([
    {
      role: "assistant",
      content:
        "Hello. I can help you stretch your pantry, plan a week of meals, or think through what to cook tonight.",
    },
  ]);
  const [draft, setDraft] = useState("");

  function send() {
    if (!draft.trim()) return;
    setMsgs((m) => [
      ...m,
      { role: "user", content: draft },
      {
        role: "assistant",
        content:
          "Conversational chat isn't wired up yet — the endpoint lives in apps/backend/app/routers/ai.py.",
      },
    ]);
    setDraft("");
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 rounded-full bg-clay px-5 py-3 text-sm font-semibold text-paper shadow-warm-lg transition hover:bg-clay-deep"
      >
        <Flame className="h-4 w-4" />
        Ask Hearth
      </button>
    );
  }

  return (
    <aside className="fixed right-0 top-0 z-40 flex h-screen w-[348px] flex-col border-l border-line bg-raised shadow-warm-lg">
      <header className="flex items-center justify-between border-b border-line px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-clay text-paper">
            <Flame className="h-3.5 w-3.5" />
          </span>
          <div className="leading-tight">
            <div className="font-display text-[17px] font-semibold text-ink">
              Hearth chat
            </div>
            <div className="text-[11px] text-ink-faint">Knows your pantry &amp; plan</div>
          </div>
        </div>
        <button
          onClick={() => setOpen(false)}
          className="grid h-7 w-7 place-items-center rounded-md text-ink-faint transition hover:bg-paper hover:text-ink"
          aria-label="Close chat"
        >
          ✕
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {msgs.map((m, i) => (
          <div
            key={i}
            className={
              m.role === "user"
                ? "ml-8 rounded-2xl rounded-br-sm bg-clay px-3.5 py-2.5 text-sm text-paper"
                : "mr-8 rounded-2xl rounded-bl-sm border border-line bg-paper px-3.5 py-2.5 text-sm text-ink"
            }
          >
            {m.content}
          </div>
        ))}
      </div>

      <form
        className="flex gap-2 border-t border-line px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask anything…"
          className="flex-1 rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-clay focus:outline-none"
        />
        <button
          type="submit"
          className="rounded-lg bg-ink px-3.5 py-2 text-sm font-semibold text-paper transition hover:bg-clay"
        >
          Send
        </button>
      </form>

      <p className="px-5 pb-3 text-[11px] text-ink-faint">
        Voice (&ldquo;hey Hearth&rdquo;) &amp; live chat — wired in an upcoming sprint.
      </p>
    </aside>
  );
}
