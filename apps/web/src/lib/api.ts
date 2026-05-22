import type {
  BadgeAward,
  Briefing,
  ChatTurnResponse,
  ContentFeed,
  ContentItem,
  ConversationOpenResponse,
  CookedResponse,
  MealPlan,
  PantryCaptureResponse,
  PantryItem,
  PlannedMealStatus,
  PlannedMealStatusResponse,
  PreservationAdvice,
  PreservationJob,
  PreservationMethod,
  PreservationMethodInfo,
  PurchasedItemResponse,
  SavingsRollup,
  ShoppingList,
  Streak,
  StretchResponse,
  WasteEvent,
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

export function generateShoppingList(): Promise<ShoppingList> {
  return api<ShoppingList>("/api/v1/food/shopping-lists/from-plan", { method: "POST" });
}

export function getActiveShoppingList(): Promise<ShoppingList | null> {
  return api<ShoppingList | null>("/api/v1/food/shopping-lists/active");
}

export function markShoppingItemPurchased(
  itemId: string,
  actualPriceUsd?: number,
): Promise<PurchasedItemResponse> {
  return api<PurchasedItemResponse>(
    `/api/v1/food/shopping-items/${itemId}/purchased`,
    {
      method: "POST",
      body: JSON.stringify({ actual_price_usd: actualPriceUsd }),
    },
  );
}

export interface WasteLogArgs {
  pantryItemId?: string;
  ingredientName: string;
  quantity?: number;
  unit?: string;
  reason?: "spoiled" | "forgotten" | "over_cooked" | "over_purchased" | "other";
  estimatedValueUsd?: number;
}

export function logWaste(args: WasteLogArgs): Promise<WasteEvent> {
  return api<WasteEvent>("/api/v1/food/waste", {
    method: "POST",
    body: JSON.stringify({
      pantry_item_id: args.pantryItemId,
      ingredient_name: args.ingredientName,
      quantity: args.quantity,
      unit: args.unit,
      reason: args.reason,
      estimated_value_usd: args.estimatedValueUsd,
    }),
  });
}

export function getSavingsRollup(periodDays = 30): Promise<SavingsRollup> {
  return api<SavingsRollup>(`/api/v1/food/waste/savings?period_days=${periodDays}`);
}

export function getStreaks(): Promise<Streak[]> {
  return api<Streak[]>("/api/v1/tracking/streaks");
}

export function getBadges(): Promise<BadgeAward[]> {
  return api<BadgeAward[]>("/api/v1/tracking/badges");
}

export function getTodaysBriefing(): Promise<Briefing> {
  return api<Briefing>("/api/v1/ai/briefings/today");
}

export function regenerateBriefing(): Promise<Briefing> {
  return api<Briefing>("/api/v1/ai/briefings/generate", { method: "POST" });
}

export function markBriefingRead(id: string): Promise<Briefing> {
  return api<Briefing>(`/api/v1/ai/briefings/${id}/read`, { method: "POST" });
}

export function getPreservationMethods(): Promise<PreservationMethodInfo[]> {
  return api<PreservationMethodInfo[]>("/api/v1/food/preservation/methods");
}

export function getPreservationAdvice(
  method: PreservationMethod,
  ingredientName: string,
  quantity?: number,
  unit?: string,
): Promise<PreservationAdvice> {
  return api<PreservationAdvice>("/api/v1/food/preservation/advice", {
    method: "POST",
    body: JSON.stringify({
      method,
      ingredient_name: ingredientName,
      quantity,
      unit,
    }),
  });
}

export function createPreservationJob(args: {
  method: PreservationMethod;
  ingredientName: string;
  quantityIn?: number;
  unit?: string;
  safetyCheckPassed: boolean;
  notes?: string;
}): Promise<PreservationJob> {
  return api<PreservationJob>("/api/v1/food/preservation/jobs", {
    method: "POST",
    body: JSON.stringify({
      method: args.method,
      ingredient_name: args.ingredientName,
      quantity_in: args.quantityIn,
      unit: args.unit,
      safety_check_passed: args.safetyCheckPassed,
      notes: args.notes,
    }),
  });
}

export function listPreservationJobs(): Promise<PreservationJob[]> {
  return api<PreservationJob[]>("/api/v1/food/preservation/jobs");
}

export function completePreservationJob(
  jobId: string,
  quantityOut?: number,
  safetyNotes?: string,
): Promise<PreservationJob> {
  return api<PreservationJob>(`/api/v1/food/preservation/jobs/${jobId}/complete`, {
    method: "POST",
    body: JSON.stringify({
      quantity_out: quantityOut,
      safety_notes: safetyNotes,
    }),
  });
}

// ---------- Content / library ----------

export function captureVideo(url: string): Promise<ContentItem> {
  return api<ContentItem>("/api/v1/content/capture", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

export function getContentFeed(): Promise<ContentFeed> {
  return api<ContentFeed>("/api/v1/content/feed");
}

export function deleteContentItem(id: string): Promise<{ status: string }> {
  return api<{ status: string }>(`/api/v1/content/items/${id}`, {
    method: "DELETE",
  });
}

// ---------- Chat assistant ----------

export function openConversation(page: string): Promise<ConversationOpenResponse> {
  return api<ConversationOpenResponse>("/api/v1/ai/conversations", {
    method: "POST",
    body: JSON.stringify({ page }),
  });
}

export function sendChatMessage(
  conversationId: string,
  content: string,
): Promise<ChatTurnResponse> {
  return api<ChatTurnResponse>(
    `/api/v1/ai/conversations/${conversationId}/messages`,
    { method: "POST", body: JSON.stringify({ content }) },
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
