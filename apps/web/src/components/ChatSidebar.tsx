"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { openConversation, sendChatMessage } from "@/lib/api";
import type { ActionResult } from "@/lib/types";

type Msg = {
  role: "user" | "assistant";
  content: string;
  actions?: ActionResult[];
};

const GREETING =
  "Hi, I'm Hearth. I can add things to your pantry, plan meals, log waste, and answer " +
  "questions about what you have. What do you need?";

function Flame({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="currentColor" aria-hidden>
      <path d="M8 2C5 5 4 7 4 9.2A4 4 0 0 0 12 9.2C12 7 11 5 8 2Z" />
    </svg>
  );
}

/**
 * Always-available Hearth chat. Collapsed to a pill by default. The conversation
 * is scoped to the current page — navigating swaps to that page's thread.
 */
export default function ChatSidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [convId, setConvId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load (or create) the conversation for the current page whenever the sidebar
  // is open and the route changes.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setConvId(null);
    setError(null);
    openConversation(pathname)
      .then((res) => {
        if (cancelled) return;
        setConvId(res.conversation_id);
        setMsgs(
          res.messages.map((m) => ({
            role: m.role,
            content: m.content,
            actions: (m.payload?.results as ActionResult[] | undefined) ?? undefined,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load the assistant.");
      });
    return () => {
      cancelled = true;
    };
  }, [open, pathname]);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || !convId || busy) return;
    setDraft("");
    setError(null);
    setMsgs((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const res = await sendChatMessage(convId, text);
      setMsgs((m) => [
        ...m,
        { role: "assistant", content: res.reply, actions: res.actions },
      ]);
    } catch {
      setError("Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }, [draft, convId, busy]);

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
            <div className="text-[11px] text-ink-faint">Knows this page&apos;s context</div>
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
        {msgs.length === 0 && (
          <div className="mr-8 rounded-2xl rounded-bl-sm border border-line bg-paper px-3.5 py-2.5 text-sm text-ink">
            {GREETING}
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i}>
            <div
              className={
                m.role === "user"
                  ? "ml-8 rounded-2xl rounded-br-sm bg-clay px-3.5 py-2.5 text-sm text-paper"
                  : "mr-8 rounded-2xl rounded-bl-sm border border-line bg-paper px-3.5 py-2.5 text-sm text-ink"
              }
            >
              {m.content}
            </div>
            {m.actions && m.actions.length > 0 && (
              <div className="mr-8 mt-1.5 flex flex-wrap gap-1.5">
                {m.actions.map((a, j) => (
                  <span
                    key={j}
                    className={
                      a.status === "ok"
                        ? "rounded-full border border-line bg-paper px-2 py-0.5 text-[11px] text-ink-faint"
                        : "rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-800"
                    }
                  >
                    {a.status === "ok" ? "✓" : "⚠"} {a.summary}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="mr-8 rounded-2xl rounded-bl-sm border border-line bg-paper px-3.5 py-2.5 text-sm text-ink-faint">
            Hearth is thinking…
          </div>
        )}
        {error && <div className="text-[12px] text-amber-800">{error}</div>}
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
          placeholder={convId ? "Ask anything…" : "Loading…"}
          disabled={!convId || busy}
          className="flex-1 rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-clay focus:outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!convId || busy || !draft.trim()}
          className="rounded-lg bg-ink px-3.5 py-2 text-sm font-semibold text-paper transition hover:bg-clay disabled:opacity-50"
        >
          Send
        </button>
      </form>

      <p className="px-5 pb-3 text-[11px] text-ink-faint">
        Voice (&ldquo;hey Hearth&rdquo;) — wired in an upcoming sprint.
      </p>
    </aside>
  );
}
