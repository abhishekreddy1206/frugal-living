"use client";

import { useEffect, useState } from "react";
import {
  generateMealPlan,
  getActiveMealPlan,
  updatePlannedMealStatus,
} from "@/lib/api";
import type { MealPlan, PlannedMeal, PlannedMealStatus } from "@/lib/types";

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; plan: MealPlan | null; coverage: string | null; totalCost: number | null }
  | { kind: "error"; message: string };

function mondayOfThisWeek(): string {
  const d = new Date();
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day; // Sunday => previous Monday
  d.setDate(d.getDate() + diff);
  return d.toISOString().slice(0, 10);
}

export default function PlanPage() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [weekStart, setWeekStart] = useState(mondayOfThisWeek());
  const [budget, setBudget] = useState<number | "">(60);
  const [dinners, setDinners] = useState(7);
  const [dietary, setDietary] = useState("");

  async function refresh() {
    try {
      const plan = await getActiveMealPlan();
      setStatus({
        kind: "ready",
        plan,
        coverage:
          (plan?.meals.length ? "(generated)" : null) as string | null,
        totalCost: null,
      });
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleGenerate() {
    setStatus({ kind: "loading" });
    try {
      const resp = await generateMealPlan({
        weekStart,
        targetBudgetUsd: budget === "" ? undefined : Number(budget),
        dinnersPerWeek: dinners,
        dietaryConstraints: dietary
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setStatus({
        kind: "ready",
        plan: resp.plan,
        coverage: resp.pantry_coverage_summary,
        totalCost: resp.total_estimated_cost_usd,
      });
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  async function handleStatusChange(meal: PlannedMeal, newStatus: PlannedMealStatus) {
    try {
      await updatePlannedMealStatus(meal.id, newStatus);
      await refresh();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-5xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-ink">Plan the week</h1>
        <p className="mt-1 text-stone-600">
          A budget-aware weekly dinner plan, optimized around your pantry.
        </p>
      </header>

      <section className="mb-8 rounded-xl border border-stone-200 bg-white p-5">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <label className="flex flex-col text-sm">
            <span className="text-stone-700 mb-1">Week start</span>
            <input
              type="date"
              value={weekStart}
              onChange={(e) => setWeekStart(e.target.value)}
              className="rounded border border-stone-300 px-2 py-1"
            />
          </label>
          <label className="flex flex-col text-sm">
            <span className="text-stone-700 mb-1">Budget (USD)</span>
            <input
              type="number"
              min={0}
              value={budget}
              onChange={(e) =>
                setBudget(e.target.value === "" ? "" : Number(e.target.value))
              }
              className="rounded border border-stone-300 px-2 py-1"
            />
          </label>
          <label className="flex flex-col text-sm">
            <span className="text-stone-700 mb-1">Dinners</span>
            <select
              value={dinners}
              onChange={(e) => setDinners(Number(e.target.value))}
              className="rounded border border-stone-300 px-2 py-1"
            >
              {[3, 4, 5, 6, 7].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col text-sm">
            <span className="text-stone-700 mb-1">Dietary (comma-sep)</span>
            <input
              type="text"
              placeholder="vegetarian, gluten-free"
              value={dietary}
              onChange={(e) => setDietary(e.target.value)}
              className="rounded border border-stone-300 px-2 py-1"
            />
          </label>
        </div>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={status.kind === "loading"}
          className={`mt-4 rounded-xl px-6 py-3 font-medium text-white shadow transition ${
            status.kind === "loading"
              ? "bg-amber-400 cursor-wait"
              : "bg-amber-600 hover:bg-amber-700"
          }`}
        >
          {status.kind === "loading" ? "Opus is thinking…" : "📅 Generate this plan"}
        </button>
      </section>

      {status.kind === "error" && (
        <div className="mb-6 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-800">
          {status.message}
        </div>
      )}

      {status.kind === "ready" && status.plan && (
        <>
          <section className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-stone-600">
            <span>
              <b className="text-stone-900">{status.plan.meals.length}</b> meals
            </span>
            {status.plan.target_budget_usd != null && (
              <span>
                Budget: <b className="text-stone-900">${status.plan.target_budget_usd}</b>
              </span>
            )}
            {status.totalCost != null && (
              <span>
                AI estimate (new purchases): <b className="text-stone-900">${status.totalCost.toFixed(2)}</b>
              </span>
            )}
            {status.coverage && <span>· {status.coverage}</span>}
          </section>

          <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {status.plan.meals.map((meal) => (
              <PlanCell key={meal.id} meal={meal} onStatus={handleStatusChange} />
            ))}
          </section>
        </>
      )}

      {status.kind === "ready" && !status.plan && (
        <p className="text-sm text-stone-500">No active plan. Generate one above.</p>
      )}
    </div>
  );
}

function PlanCell({
  meal,
  onStatus,
}: {
  meal: PlannedMeal;
  onStatus: (m: PlannedMeal, s: PlannedMealStatus) => void;
}) {
  const recipe = meal.recipe;
  const date = new Date(meal.planned_date);
  const dayLabel = date.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const totalMin = (recipe?.prep_time_min ?? 0) + (recipe?.cook_time_min ?? 0);

  return (
    <article
      className={`rounded-xl border bg-white p-4 shadow-sm transition ${
        meal.status === "cooked"
          ? "border-emerald-300 bg-emerald-50"
          : meal.status === "skipped"
            ? "border-stone-300 opacity-60"
            : "border-stone-200"
      }`}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wide text-stone-500">{dayLabel}</div>
          <h3 className="text-base font-semibold text-stone-900 truncate">
            {recipe?.name ?? "Recipe missing"}
          </h3>
        </div>
        <StatusBadge status={meal.status} />
      </header>

      {recipe && (
        <>
          <div className="mt-1 text-xs text-stone-500 flex flex-wrap items-center gap-x-2">
            {recipe.cuisine && <span>{recipe.cuisine}</span>}
            {totalMin > 0 && <span>· {totalMin} min</span>}
            <span>· serves {recipe.servings}</span>
            {recipe.estimated_cost_per_serving_usd != null && (
              <span>· ${recipe.estimated_cost_per_serving_usd.toFixed(2)}/srv</span>
            )}
          </div>
          {recipe.description && (
            <p className="mt-2 text-sm text-stone-600 line-clamp-2">{recipe.description}</p>
          )}
          {meal.notes && (
            <p className="mt-2 text-xs text-amber-700 italic">↳ {meal.notes}</p>
          )}
        </>
      )}

      {meal.status === "planned" && (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={() => onStatus(meal, "cooked")}
            className="flex-1 rounded-md bg-stone-900 text-white py-1.5 text-xs font-medium hover:bg-stone-700 transition"
          >
            ✓ Cooked
          </button>
          <button
            type="button"
            onClick={() => onStatus(meal, "skipped")}
            className="flex-1 rounded-md bg-stone-100 text-stone-700 py-1.5 text-xs font-medium hover:bg-stone-200 transition"
          >
            Skip
          </button>
        </div>
      )}
    </article>
  );
}

function StatusBadge({ status }: { status: PlannedMealStatus }) {
  const styles: Record<PlannedMealStatus, string> = {
    planned: "bg-stone-100 text-stone-600 border-stone-200",
    prepped: "bg-amber-50 text-amber-700 border-amber-200",
    cooked: "bg-emerald-50 text-emerald-700 border-emerald-200",
    skipped: "bg-stone-100 text-stone-500 border-stone-200",
  };
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-md border ${styles[status]} whitespace-nowrap`}>
      {status}
    </span>
  );
}
