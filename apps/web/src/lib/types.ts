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
