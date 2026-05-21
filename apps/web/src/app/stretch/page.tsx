"use client";

import { useState } from "react";
import { markRecipeCooked, stretchRecipes } from "@/lib/api";
import type { CookedResponse, Recipe } from "@/lib/types";

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; recipes: Recipe[]; pantrySize: number }
  | { kind: "error"; message: string };

export default function StretchPage() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [cookedToasts, setCookedToasts] = useState<CookedResponse[]>([]);

  async function handleStretch() {
    setStatus({ kind: "loading" });
    setCookedToasts([]);
    try {
      const resp = await stretchRecipes({ count: 5 });
      setStatus({ kind: "ready", recipes: resp.recipes, pantrySize: resp.pantry_size });
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  async function handleCooked(recipe: Recipe) {
    try {
      const resp = await markRecipeCooked(recipe.id);
      setCookedToasts((prev) => [resp, ...prev]);
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-5xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-ink">Stretch the pantry</h1>
        <p className="mt-1 text-stone-600">
          What can I make right now? Claude suggests recipes that use what you already have.
        </p>
      </header>

      <section className="mb-10">
        <button
          type="button"
          onClick={handleStretch}
          disabled={status.kind === "loading"}
          className={`rounded-xl px-6 py-3 font-medium text-white shadow transition ${
            status.kind === "loading"
              ? "bg-amber-400 cursor-wait"
              : "bg-amber-600 hover:bg-amber-700"
          }`}
        >
          {status.kind === "loading" ? "Thinking…" : "🍳 Suggest 5 recipes"}
        </button>
        {status.kind === "ready" && (
          <span className="ml-4 text-sm text-stone-500">
            From {status.pantrySize} pantry items
          </span>
        )}
      </section>

      {cookedToasts.length > 0 && (
        <div className="mb-6 space-y-2">
          {cookedToasts.map((t) => (
            <div
              key={t.recipe_id}
              className="rounded-md bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-800"
            >
              Cooked <b>{t.recipe_name}</b> · {Math.round(t.cooked_from_pantry_pct * 100)}%
              from your pantry
              {t.estimated_value_usd != null && (
                <> · saved ~${t.estimated_value_usd.toFixed(2)}</>
              )}
            </div>
          ))}
        </div>
      )}

      {status.kind === "error" && (
        <div className="mb-6 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-800">
          {status.message}
        </div>
      )}

      {status.kind === "ready" && (
        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {status.recipes.map((recipe) => (
            <RecipeCard
              key={recipe.id}
              recipe={recipe}
              onCooked={() => handleCooked(recipe)}
            />
          ))}
        </section>
      )}

      {status.kind === "idle" && (
        <p className="text-sm text-stone-500">
          Make sure you&apos;ve captured some pantry items first.
        </p>
      )}
    </div>
  );
}

function RecipeCard({ recipe, onCooked }: { recipe: Recipe; onCooked: () => void }) {
  const totalMin = (recipe.prep_time_min ?? 0) + (recipe.cook_time_min ?? 0);
  return (
    <article className="rounded-xl border border-stone-200 bg-white p-5 shadow-sm hover:shadow transition">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-stone-900 truncate">{recipe.name}</h2>
          <div className="mt-1 text-xs text-stone-500 flex flex-wrap items-center gap-x-2">
            {recipe.cuisine && <span>{recipe.cuisine}</span>}
            {recipe.cuisine && totalMin > 0 && <span>·</span>}
            {totalMin > 0 && <span>{totalMin} min</span>}
            {totalMin > 0 && <span>·</span>}
            <span>serves {recipe.servings}</span>
            {recipe.estimated_cost_per_serving_usd != null && (
              <>
                <span>·</span>
                <span>${recipe.estimated_cost_per_serving_usd.toFixed(2)}/serving</span>
              </>
            )}
          </div>
        </div>
        <span
          className={`text-xs px-2 py-0.5 rounded-md whitespace-nowrap ${
            recipe.difficulty === "easy"
              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
              : recipe.difficulty === "hard"
                ? "bg-red-50 text-red-700 border border-red-200"
                : "bg-stone-100 text-stone-600"
          }`}
        >
          {recipe.difficulty}
        </span>
      </div>

      {recipe.description && (
        <p className="mt-2 text-sm text-stone-600 line-clamp-2">{recipe.description}</p>
      )}

      <div className="mt-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-stone-500 mb-1">
          Ingredients
        </h3>
        <ul className="text-sm text-stone-700 space-y-0.5">
          {recipe.ingredients.map((ing, idx) => (
            <li key={idx}>
              {ing.quantity != null && (
                <span className="text-stone-500">
                  {ing.quantity} {ing.unit ?? ""}{" "}
                </span>
              )}
              {ing.raw_name}
              {ing.ingredient_id && (
                <span className="ml-1 text-emerald-700 text-xs">●</span>
              )}
              {ing.substitutions.length > 0 && (
                <span className="text-stone-400 text-xs">
                  {" "}
                  or {ing.substitutions.join(", ")}
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-stone-500 mb-1">
          Steps
        </h3>
        <ol className="text-sm text-stone-700 list-decimal list-inside space-y-0.5">
          {recipe.steps.map((step) => (
            <li key={step.order_index}>{step.content}</li>
          ))}
        </ol>
      </div>

      <button
        type="button"
        onClick={onCooked}
        className="mt-4 w-full rounded-md bg-stone-900 text-white py-2 text-sm font-medium hover:bg-stone-700 transition"
      >
        ✓ I cooked this
      </button>
    </article>
  );
}
