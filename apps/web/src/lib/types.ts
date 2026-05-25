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

// ---------- Chat assistant ----------

export interface ActionResult {
  type: string;
  status: "ok" | "error";
  summary: string;
  error: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ConversationOpenResponse {
  conversation_id: string;
  page: string;
  messages: ChatMessage[];
}

export interface ChatTurnResponse {
  message_id: string;
  reply: string;
  actions: ActionResult[];
}

// ---------- Recipe suggestions ----------

export interface RecipeSuggestion {
  id: string;
  provider: string;
  external_id: string;
  title: string;
  url: string | null;
  author: string | null;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  match_score: number;
  matched_ingredients: string[];
  match_reason: string;
}

export interface RecipeSuggestionsResponse {
  suggestions: RecipeSuggestion[];
  pantry_size: number;
}

// ---------- Community / inventory (Tier B) ----------

export type ItemCategory =
  | "tools"
  | "games"
  | "books"
  | "kitchen"
  | "outdoor"
  | "electronics"
  | "furniture"
  | "kids"
  | "sports"
  | "other";

export type ItemCondition = "new" | "like_new" | "good" | "fair" | "poor";

export interface InventoryItem {
  id: string;
  name: string;
  category: ItemCategory;
  tags: string[];
  quantity: number;
  condition: ItemCondition | null;
  estimated_value_usd: number | null;
  location: string | null;
  photo_url: string | null;
  source: string;
  confidence: number | null;
  notes: string | null;
  created_at: string;
}

export interface ItemCaptureResponse {
  items: InventoryItem[];
  created_count: number;
}

// ---------- Auth ----------

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
  role: Role;
}

export interface AuthHousehold {
  id: string;
  name: string;
}

export interface AuthMembership {
  household: AuthHousehold;
  role: string;
}

export interface MeResponse {
  user: AuthUser;
  memberships: AuthMembership[];
  active_household: AuthHousehold | null;
}

export interface SignupResponse {
  user: AuthUser;
  household: AuthHousehold;
}

export interface LoginResponse {
  user: AuthUser;
  active_household: AuthHousehold;
}

export interface InvitePreview {
  household_name: string;
  role: string;
  inviter_name: string | null;
  expires_at: string;
}

export interface CreateInviteResponse {
  token: string;
  url: string;
  expires_at: string;
}

// ---------- Community Phase 2 ----------

export type ExchangeType = "borrow" | "swap" | "gift";
export type AvailabilityStatus = "available" | "paused" | "removed";
export type CommunityRole = "owner" | "member";
export type JoinRequestStatus = "pending" | "approved" | "declined" | "withdrawn";

export interface Community {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface CommunityPreview {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  member_count: number;
  your_membership_role: CommunityRole | null;
  your_join_request_status: JoinRequestStatus | null;
}

export interface CommunityMembership {
  community: Community;
  role: CommunityRole;
  joined_at: string;
}

export interface MyCommunitiesResponse {
  memberships: CommunityMembership[];
}

export interface JoinRequest {
  id: string;
  community_id: string;
  user_id: string;
  status: JoinRequestStatus;
  requested_at: string;
  decided_at: string | null;
  decision_note: string | null;
}

export interface ListingItemSummary {
  id: string;
  name: string;
  category: string;
  tags: string[];
  quantity: number;
  condition: string | null;
  estimated_value_usd: number | null;
  photo_url: string | null;
  notes: string | null;
}

export interface Listing {
  id: string;
  item: ListingItemSummary;
  allowed_exchange_types: ExchangeType[];
  quantity_available: number;
  share_in_radius: boolean;
  share_radius_miles: number | null;
  availability_status: AvailabilityStatus;
  description_override: string | null;
  community_ids: string[];
  created_at: string;
}

export interface FeedRow {
  listing: Listing;
  distance_miles: number | null;
  matched_community_id: string | null;
}

export interface FeedResponse {
  rows: FeedRow[];
  next_cursor: string | null;
}

// --- Admin / settings / flags / moderation ---

export type Role = "user" | "moderator" | "admin";

export interface RegistryEntry {
  key: string;
  type: "bool" | "int" | "str" | "float";
  default: unknown;
  scopes: ("global" | "household" | "user")[];
  description: string;
  public: boolean;
}

export interface GlobalSettingRow {
  key: string;
  spec: RegistryEntry;
  current_global: unknown;
  has_global_override: boolean;
  household_override_count: number;
  user_override_count: number;
}

export interface SettingDetail {
  key: string;
  spec: RegistryEntry;
  current_global: unknown;
  has_global_override: boolean;
  household_overrides: { household_id: string; value: unknown; updated_at: string }[];
  user_overrides: { user_id: string; value: unknown; updated_at: string }[];
}

export interface FeatureFlag {
  key: string;
  description: string | null;
  enabled_globally: boolean;
  rollout_percent: number;
  household_override_count: number;
  user_override_count: number;
}

export interface FeatureFlagDetail extends FeatureFlag {
  household_overrides: { id: string; household_id: string; enabled: boolean }[];
  user_overrides: { id: string; user_id: string; enabled: boolean }[];
}

export interface AdminUserRow {
  id: string;
  email: string;
  display_name: string | null;
  role: Role;
  is_active: boolean;
  locked_until: string | null;
  created_at: string;
}

export interface AdminUserDetail extends AdminUserRow {
  household_memberships: { household_id: string; role: string }[];
  listing_count: number;
}

export interface AdminCommunityRow {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  deleted_at: string | null;
  created_by_user_id: string;
}

export interface AdminCommunityDetail extends AdminCommunityRow {
  member_count: number;
  listing_count: number;
}

export interface AdminListingRow {
  id: string;
  item_id: string;
  item_name: string;
  household_id: string;
  availability_status: string;
  created_at: string;
  deleted_at: string | null;
}

// Matches the actual get_listing response: description_override is surfaced
// as "description"; household_id is NOT present in the detail response.
export interface AdminListingDetail {
  id: string;
  item_id: string;
  availability_status: string;
  allowed_exchange_types: string[];
  quantity_available: number;
  description: string | null;
  created_at: string;
  deleted_at: string | null;
  shared_with_communities: string[];
}

export interface AuditLogEntry {
  id: string;
  actor_user_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RuntimeConfig {
  signups_open?: boolean;
  maintenance_message?: string;
}
