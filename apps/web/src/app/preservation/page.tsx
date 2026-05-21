"use client";

import { useEffect, useState } from "react";
import {
  completePreservationJob,
  createPreservationJob,
  getPreservationAdvice,
  getPreservationMethods,
  listPreservationJobs,
} from "@/lib/api";
import type {
  PreservationAdvice,
  PreservationJob,
  PreservationMethod,
  PreservationMethodInfo,
} from "@/lib/types";

export default function PreservationPage() {
  const [methods, setMethods] = useState<PreservationMethodInfo[]>([]);
  const [jobs, setJobs] = useState<PreservationJob[]>([]);
  const [advice, setAdvice] = useState<PreservationAdvice | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({
    method: "freezing" as PreservationMethod,
    ingredient: "",
    quantity: "",
    unit: "",
  });
  const [adviceLoading, setAdviceLoading] = useState(false);

  async function refresh() {
    try {
      const [m, j] = await Promise.all([getPreservationMethods(), listPreservationJobs()]);
      setMethods(m);
      setJobs(j);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleAdvise() {
    if (!form.ingredient.trim()) return;
    setAdviceLoading(true);
    setAdvice(null);
    setError(null);
    try {
      const a = await getPreservationAdvice(
        form.method,
        form.ingredient,
        form.quantity === "" ? undefined : Number(form.quantity),
        form.unit || undefined,
      );
      setAdvice(a);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAdviceLoading(false);
    }
  }

  async function handleStartJob(safetyPassed: boolean) {
    if (!form.ingredient.trim()) return;
    try {
      await createPreservationJob({
        method: form.method,
        ingredientName: form.ingredient,
        quantityIn: form.quantity === "" ? undefined : Number(form.quantity),
        unit: form.unit || undefined,
        safetyCheckPassed: safetyPassed,
      });
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function handleComplete(job: PreservationJob) {
    try {
      await completePreservationJob(job.id);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-4xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-ink">Preservation</h1>
        <p className="mt-1 text-stone-600">
          Stretch the pantry by canning, freezing, fermenting, or curing. We follow USDA safety rules.
        </p>
      </header>

      {error && (
        <div className="mb-6 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-800">
          {error}
        </div>
      )}

      <section className="mb-8 rounded-xl border border-stone-200 bg-white p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-600 mb-3">
          Get advice / start a job
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
          <select
            value={form.method}
            onChange={(e) =>
              setForm({ ...form, method: e.target.value as PreservationMethod })
            }
            className="md:col-span-2 rounded border border-stone-300 px-2 py-1 text-sm"
          >
            {methods.map((m) => (
              <option key={m.method} value={m.method}>
                {m.label}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Ingredient"
            value={form.ingredient}
            onChange={(e) => setForm({ ...form, ingredient: e.target.value })}
            className="rounded border border-stone-300 px-2 py-1 text-sm"
          />
          <input
            type="number"
            step="0.1"
            placeholder="Qty"
            value={form.quantity}
            onChange={(e) => setForm({ ...form, quantity: e.target.value })}
            className="rounded border border-stone-300 px-2 py-1 text-sm"
          />
          <input
            type="text"
            placeholder="Unit"
            value={form.unit}
            onChange={(e) => setForm({ ...form, unit: e.target.value })}
            className="rounded border border-stone-300 px-2 py-1 text-sm"
          />
        </div>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={handleAdvise}
            disabled={adviceLoading}
            className={`rounded-md px-4 py-2 text-sm font-medium text-white transition ${
              adviceLoading ? "bg-amber-400 cursor-wait" : "bg-amber-600 hover:bg-amber-700"
            }`}
          >
            {adviceLoading ? "Asking Claude…" : "Get USDA-aligned advice"}
          </button>
        </div>

        {advice && (
          <div
            className={`mt-4 rounded-lg border p-4 text-sm ${
              advice.is_safe
                ? "bg-emerald-50 border-emerald-200 text-emerald-900"
                : "bg-red-50 border-red-200 text-red-900"
            }`}
          >
            {!advice.is_safe ? (
              <>
                <div className="font-semibold mb-1">⚠️ Refused on safety grounds</div>
                <p>{advice.refusal_reason}</p>
                {advice.recommended_method && (
                  <p className="mt-2">
                    <b>Recommended instead:</b> {advice.recommended_method}
                  </p>
                )}
              </>
            ) : (
              <>
                <div className="font-semibold mb-1">✓ Safe — here&apos;s how</div>
                {advice.equipment.length > 0 && (
                  <p className="mt-1 text-xs">
                    <b>Equipment:</b> {advice.equipment.join(", ")}
                  </p>
                )}
                {advice.steps.length > 0 && (
                  <ol className="mt-2 list-decimal list-inside space-y-0.5">
                    {advice.steps.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ol>
                )}
                {advice.expected_shelf_life_days && (
                  <p className="mt-2 text-xs">
                    <b>Shelf life:</b> ~{advice.expected_shelf_life_days} days
                  </p>
                )}
              </>
            )}
            {advice.safety_warnings.length > 0 && (
              <ul className="mt-3 text-xs space-y-0.5 list-disc list-inside">
                {advice.safety_warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
            {advice.usda_references.length > 0 && (
              <p className="mt-2 text-xs italic">
                Refs: {advice.usda_references.join(" · ")}
              </p>
            )}
            {advice.is_safe && (
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={() => handleStartJob(true)}
                  className="rounded-md bg-stone-900 text-white px-3 py-1.5 text-xs font-medium hover:bg-stone-700 transition"
                >
                  Start job (safety checked)
                </button>
                <button
                  type="button"
                  onClick={() => handleStartJob(false)}
                  className="rounded-md bg-stone-100 text-stone-700 px-3 py-1.5 text-xs font-medium hover:bg-stone-200 transition"
                >
                  Start as draft
                </button>
              </div>
            )}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-600 mb-3">
          Active jobs ({jobs.filter((j) => !j.completed_at).length})
        </h2>
        {jobs.length === 0 ? (
          <p className="text-sm text-stone-500">No jobs yet.</p>
        ) : (
          <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
            {jobs.map((job) => (
              <li key={job.id} className="px-4 py-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-medium text-stone-900">
                    {job.ingredient_name}{" "}
                    <span className="text-xs text-stone-500">· {job.method}</span>
                  </div>
                  <div className="text-xs text-stone-500">
                    {job.quantity_in != null && `${job.quantity_in} ${job.unit ?? ""} in · `}
                    {job.completed_at
                      ? `completed · expires ${job.expires_at ?? "—"}`
                      : `started ${job.started_at?.slice(0, 10) ?? ""}`}
                    {!job.safety_check_passed && (
                      <span className="ml-1 text-red-700 font-medium">⚠ safety not checked</span>
                    )}
                  </div>
                </div>
                {!job.completed_at && (
                  <button
                    type="button"
                    onClick={() => handleComplete(job)}
                    disabled={!job.safety_check_passed}
                    className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                      job.safety_check_passed
                        ? "bg-emerald-600 text-white hover:bg-emerald-700"
                        : "bg-stone-100 text-stone-400 cursor-not-allowed"
                    }`}
                  >
                    Complete
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
