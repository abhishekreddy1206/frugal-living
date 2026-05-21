// Types shared with the backend. Mirror app/schemas/food.py.

export interface PantryItem {
  id: string;
  raw_name: string;
  ingredient_id: string | null;
  location_id: string | null;
  quantity: number | null;
  unit: string | null;
  purchased_at: string | null;
  opened_at: string | null;
  expires_at: string | null;
  estimated_value: number | null;
  source: string;
  confidence: number | null;
  photo_url: string | null;
  notes: string | null;
  created_at: string;
}

export interface PantryCaptureResponse {
  items: PantryItem[];
  created_count: number;
}

// ---------- Recipes ----------

export interface RecipeIngredient {
  raw_name: string;
  ingredient_id: string | null;
  quantity: number | null;
  unit: string | null;
  is_optional: boolean;
  substitutions: string[];
}

export interface RecipeStep {
  order_index: number;
  content: string;
  duration_seconds: number | null;
}

export interface Recipe {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  servings: number;
  prep_time_min: number | null;
  cook_time_min: number | null;
  cuisine: string | null;
  difficulty: string;
  tags: string[];
  estimated_cost_usd: number | null;
  estimated_cost_per_serving_usd: number | null;
  is_ai_generated: boolean;
  ingredients: RecipeIngredient[];
  steps: RecipeStep[];
}

export interface StretchResponse {
  recipes: Recipe[];
  pantry_size: number;
}

export interface CookedResponse {
  recipe_id: string;
  recipe_name: string;
  servings: number;
  cooked_from_pantry_pct: number;
  decremented_item_ids: string[];
  estimated_value_usd: number | null;
}

// ---------- Meal plan ----------

export type PlannedMealStatus = "planned" | "prepped" | "cooked" | "skipped";

export interface PlannedMeal {
  id: string;
  recipe_id: string | null;
  planned_date: string;
  meal_type: string;
  servings: number;
  status: PlannedMealStatus;
  notes: string | null;
  recipe: Recipe | null;
}

export interface MealPlan {
  id: string;
  week_start: string;
  name: string | null;
  target_budget_usd: number | null;
  status: "draft" | "active" | "archived";
  meals: PlannedMeal[];
}

export interface WeekPlanResponse {
  plan: MealPlan;
  pantry_coverage_summary: string | null;
  total_estimated_cost_usd: number | null;
}

export interface PlannedMealStatusResponse {
  planned_meal_id: string;
  new_status: PlannedMealStatus;
  cooked_from_pantry_pct: number | null;
  estimated_value_usd: number | null;
  decremented_item_ids: string[];
}

// ---------- Shopping ----------

export type ShoppingItemStatus = "pending" | "purchased" | "skipped";

export interface ShoppingItem {
  id: string;
  ingredient_id: string | null;
  raw_name: string;
  quantity: number | null;
  unit: string | null;
  store: string | null;
  estimated_price_usd: number | null;
  actual_price_usd: number | null;
  status: ShoppingItemStatus;
}

export interface ShoppingList {
  id: string;
  meal_plan_id: string | null;
  name: string | null;
  status: "active" | "completed" | "archived";
  target_date: string | null;
  items: ShoppingItem[];
}

export interface PurchasedItemResponse {
  shopping_item_id: string;
  pantry_item_id: string;
  status: "purchased" | "already_purchased";
}

// ---------- Waste / savings ----------

export interface WasteEvent {
  id: string;
  pantry_item_id: string | null;
  ingredient_name: string;
  quantity: number | null;
  unit: string | null;
  reason: string | null;
  estimated_value_usd: number | null;
  occurred_on: string;
}

export interface SavingsRollup {
  period_days: number;
  cooked_from_pantry_value_usd: number;
  waste_value_usd: number;
  net_savings_usd: number;
  cooked_meals_count: number;
  waste_events_count: number;
  expiring_soon: PantryItem[];
}

// ---------- Streaks + badges ----------

export interface Streak {
  kind: string;
  current_length: number;
  longest_length: number;
  last_event_on: string | null;
}

export interface BadgeAward {
  key: string;
  name: string;
  description: string | null;
  awarded_at: string;
  icon_url: string | null;
}

// ---------- Briefing ----------

export interface Briefing {
  id: string;
  for_date: string;
  headline: string | null;
  body_markdown: string;
  was_read: boolean;
}

// ---------- Preservation ----------

export type PreservationMethod =
  | "canning_water_bath"
  | "canning_pressure"
  | "freezing"
  | "dehydrating"
  | "fermenting"
  | "pickling"
  | "curing";

export interface PreservationMethodInfo {
  method: PreservationMethod;
  label: string;
  safe_for: string[];
  typical_shelf_life_days: number;
  safety_notes: string;
}

export interface PreservationAdvice {
  is_safe: boolean;
  refusal_reason: string | null;
  recommended_method: string | null;
  safety_warnings: string[];
  usda_references: string[];
  steps: string[];
  expected_shelf_life_days: number | null;
  equipment: string[];
}

export interface PreservationJob {
  id: string;
  method: PreservationMethod;
  ingredient_name: string;
  quantity_in: number | null;
  quantity_out: number | null;
  unit: string | null;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
  safety_check_passed: boolean;
  safety_notes: string | null;
  notes: string | null;
}

// ---------- Content / library ----------

export interface ContentItem {
  id: string;
  provider: string;
  external_id: string;
  title: string;
  url: string | null;
  author: string | null;
  summary: string | null;
  thumbnail_url: string | null;
  topic: string;
  tags: string[];
  created_at: string;
}

export interface ContentFeed {
  items: ContentItem[];
  count: number;
}
