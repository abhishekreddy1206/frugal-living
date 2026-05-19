"use client";

import { useState } from "react";

type Msg = { role: "user" | "assistant"; content: string };

/**
 * Always-on Claude chat sidebar. Knows about the current pantry, meal plan, and
 * household. Stub for now — wire to POST /api/v1/ai/conversations/{id}/messages.
 */
export default function ChatSidebar() {
  const [open, setOpen] = useState(true);
  const [msgs, setMsgs] = useState<Msg[]>([
    {
      role: "assistant",
      content: "Hey — I can help you stretch your pantry, plan meals, or just talk through what to cook. What's up?",
    },
  ]);
  const [draft, setDraft] = useState("");

  async function send() {
    if (!draft.trim()) return;
    const userMsg: Msg = { role: "user", content: draft };
    setMsgs((m) => [...m, userMsg]);
    setDraft("");
    // TODO: POST to /api/v1/ai/conversations/{id}/messages and stream response.
    setMsgs((m) => [
      ...m,
      { role: "assistant", content: "(stub) Backend wiring pending — see apps/backend/app/routers/ai.py" },
    ]);
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed right-4 bottom-4 rounded-full bg-stone-900 text-white px-4 py-2 shadow-lg"
      >
        Chat
      </button>
    );
  }

  return (
    <aside className="w-80 border-l border-stone-200 bg-white flex flex-col">
      <header className="flex items-center justify-between p-3 border-b border-stone-200">
        <span className="font-semibold">Hearth chat</span>
        <button onClick={() => setOpen(false)} className="text-stone-500 hover:text-stone-900">
          ✕
        </button>
      </header>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {msgs.map((m, i) => (
          <div
            key={i}
            className={
              m.role === "user"
                ? "bg-stone-900 text-white rounded-lg px-3 py-2 ml-6"
                : "bg-stone-100 text-stone-900 rounded-lg px-3 py-2 mr-6"
            }
          >
            {m.content}
          </div>
        ))}
      </div>

      <form
        className="p-3 border-t border-stone-200 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask anything..."
          className="flex-1 rounded-md border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:border-stone-500"
        />
        <button type="submit" className="rounded-md bg-stone-900 text-white px-3 py-2 text-sm">
          Send
        </button>
      </form>

      <div className="px-3 pb-3 text-xs text-stone-500">
        🎙️ Voice ("hey Hearth") · 📰 Daily briefing — wired in upcoming sprint.
      </div>
    </aside>
  );
}
