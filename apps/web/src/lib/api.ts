import type {
  CookedResponse,
  MealPlan,
  PantryCaptureResponse,
  PantryItem,
  PlannedMealStatus,
  PlannedMealStatusResponse,
  StretchResponse,
  WeekPlanResponse,
} from "./types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

export function listPantry(): Promise<PantryItem[]> {
  return api<PantryItem[]>("/api/v1/food/pantry");
}

export function capturePantry(
  imageBase64: string,
  mediaType: string,
): Promise<PantryCaptureResponse> {
  return api<PantryCaptureResponse>("/api/v1/food/pantry/capture", {
    method: "POST",
    body: JSON.stringify({ image_base64: imageBase64, media_type: mediaType }),
  });
}

export interface StretchOptions {
  count?: number;
  maxPrepMin?: number;
  maxCookMin?: number;
  prioritizeExpiring?: boolean;
  mealType?: "breakfast" | "lunch" | "dinner" | "snack" | "any";
  cuisines?: string[];
}

export function stretchRecipes(opts: StretchOptions = {}): Promise<StretchResponse> {
  const params = new URLSearchParams();
  if (opts.count != null) params.set("count", String(opts.count));
  if (opts.maxPrepMin != null) params.set("max_prep_min", String(opts.maxPrepMin));
  if (opts.maxCookMin != null) params.set("max_cook_min", String(opts.maxCookMin));
  if (opts.prioritizeExpiring != null)
    params.set("prioritize_expiring", String(opts.prioritizeExpiring));
  if (opts.mealType) params.set("meal_type", opts.mealType);
  for (const c of opts.cuisines ?? []) params.append("cuisines", c);
  const qs = params.toString();
  return api<StretchResponse>(`/api/v1/food/recipes/stretch${qs ? `?${qs}` : ""}`);
}

export function markRecipeCooked(
  recipeId: string,
  servingsCooked?: number,
): Promise<CookedResponse> {
  const qs = servingsCooked != null ? `?servings_cooked=${servingsCooked}` : "";
  return api<CookedResponse>(`/api/v1/food/recipes/${recipeId}/cooked${qs}`, {
    method: "POST",
  });
}

export interface GeneratePlanArgs {
  weekStart: string; // YYYY-MM-DD
  targetBudgetUsd?: number;
  dinnersPerWeek?: number;
  maxCostPerServingUsd?: number;
  dietaryConstraints?: string[];
  notes?: string;
}

export function generateMealPlan(args: GeneratePlanArgs): Promise<WeekPlanResponse> {
  return api<WeekPlanResponse>("/api/v1/food/meal-plans/generate", {
    method: "POST",
    body: JSON.stringify({
      week_start: args.weekStart,
      target_budget_usd: args.targetBudgetUsd,
      dinners_per_week: args.dinnersPerWeek ?? 7,
      max_cost_per_serving_usd: args.maxCostPerServingUsd,
      dietary_constraints: args.dietaryConstraints ?? [],
      notes: args.notes,
    }),
  });
}

export function getActiveMealPlan(): Promise<MealPlan | null> {
  return api<MealPlan | null>("/api/v1/food/meal-plans/active");
}

export function updatePlannedMealStatus(
  plannedMealId: string,
  status: PlannedMealStatus,
  servingsCooked?: number,
): Promise<PlannedMealStatusResponse> {
  return api<PlannedMealStatusResponse>(
    `/api/v1/food/planned-meals/${plannedMealId}/status`,
    {
      method: "POST",
      body: JSON.stringify({ status, servings_cooked: servingsCooked }),
    },
  );
}

/** Read a File as a base64 string (without the data:...;base64, prefix). */
export function fileToBase64(file: File): Promise<{ base64: string; mediaType: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const commaIdx = result.indexOf(",");
      resolve({ base64: result.slice(commaIdx + 1), mediaType: file.type || "image/jpeg" });
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
