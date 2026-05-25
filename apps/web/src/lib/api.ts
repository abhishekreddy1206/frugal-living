import type {
  AuthHousehold,
  AuthUser,
  BadgeAward,
  Briefing,
  ChatTurnResponse,
  Community,
  CommunityMembership,
  CommunityPreview,
  CommunityRole,
  ContentFeed,
  ContentItem,
  ConversationOpenResponse,
  CookedResponse,
  CreateInviteResponse,
  ExchangeType,
  FeedResponse,
  InventoryItem,
  InvitePreview,
  ItemCaptureResponse,
  ItemCategory,
  JoinRequest,
  LoginResponse,
  Listing,
  MealPlan,
  MeResponse,
  MyCommunitiesResponse,
  PantryCaptureResponse,
  PantryItem,
  PlannedMealStatus,
  PlannedMealStatusResponse,
  PreservationAdvice,
  PreservationJob,
  PreservationMethod,
  PreservationMethodInfo,
  PurchasedItemResponse,
  RecipeSuggestionsResponse,
  SavingsRollup,
  ShoppingList,
  SignupResponse,
  Streak,
  StretchResponse,
  WasteEvent,
  WeekPlanResponse,
} from "./types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class AuthError extends Error {
  constructor(message = "not authenticated") {
    super(message);
    this.name = "AuthError";
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (res.status === 401) {
    throw new AuthError();
  }
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${await res.text()}`);
  }
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

export function getRecipeSuggestions(
  limit = 12,
): Promise<RecipeSuggestionsResponse> {
  return api<RecipeSuggestionsResponse>(
    `/api/v1/content/recipe-suggestions?limit=${limit}`,
  );
}

// ---------- Community / inventory (Tier B) ----------

export function listInventory(category?: string): Promise<InventoryItem[]> {
  const qs = category ? `?category=${encodeURIComponent(category)}` : "";
  return api<InventoryItem[]>(`/api/v1/community/items${qs}`);
}

export function captureInventory(
  imageBase64: string,
  mediaType: string,
): Promise<ItemCaptureResponse> {
  return api<ItemCaptureResponse>("/api/v1/community/items/capture", {
    method: "POST",
    body: JSON.stringify({ image_base64: imageBase64, media_type: mediaType }),
  });
}

export function createInventoryItem(args: {
  name: string;
  category?: ItemCategory;
  tags?: string[];
  quantity?: number;
  location?: string;
  notes?: string;
}): Promise<InventoryItem> {
  return api<InventoryItem>("/api/v1/community/items", {
    method: "POST",
    body: JSON.stringify({
      name: args.name,
      category: args.category ?? "other",
      tags: args.tags ?? [],
      quantity: args.quantity ?? 1,
      location: args.location,
      notes: args.notes,
    }),
  });
}

export function deleteInventoryItem(id: string): Promise<{ status: string }> {
  return api<{ status: string }>(`/api/v1/community/items/${id}`, {
    method: "DELETE",
  });
}

// ---------- Auth ----------

export function signup(args: {
  email: string;
  password: string;
  display_name: string;
  household_name: string;
}): Promise<SignupResponse> {
  return api<SignupResponse>("/api/v1/auth/signup", {
    method: "POST",
    body: JSON.stringify(args),
  });
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return api<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<{ status: string }> {
  return api<{ status: string }>("/api/v1/auth/logout", { method: "POST" });
}

export function getMe(): Promise<MeResponse> {
  return api<MeResponse>("/api/v1/auth/me");
}

export function changePassword(
  current_password: string,
  new_password: string,
): Promise<{ status: string }> {
  return api<{ status: string }>("/api/v1/auth/password", {
    method: "POST",
    body: JSON.stringify({ current_password, new_password }),
  });
}

export function createHousehold(name: string): Promise<AuthHousehold> {
  return api<AuthHousehold>("/api/v1/auth/households", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function switchHousehold(household_id: string): Promise<AuthHousehold> {
  return api<AuthHousehold>("/api/v1/auth/switch-household", {
    method: "POST",
    body: JSON.stringify({ household_id }),
  });
}

export function createInvite(
  household_id: string,
  role: "member" | "viewer" = "member",
  email?: string,
): Promise<CreateInviteResponse> {
  return api<CreateInviteResponse>(`/api/v1/auth/households/${household_id}/invites`, {
    method: "POST",
    body: JSON.stringify({ role, email }),
  });
}

export function previewInvite(token: string): Promise<InvitePreview> {
  return api<InvitePreview>(`/api/v1/auth/invites/${token}`);
}

export function acceptInvite(token: string): Promise<AuthHousehold> {
  return api<AuthHousehold>(`/api/v1/auth/invites/${token}/accept`, {
    method: "POST",
  });
}

export function revokeInvite(
  household_id: string,
  invite_id: string,
): Promise<{ status: string }> {
  return api<{ status: string }>(
    `/api/v1/auth/households/${household_id}/invites/${invite_id}`,
    { method: "DELETE" },
  );
}

// ---------- Community Phase 2 ----------

export function createCommunity(args: {
  slug: string; name: string; description?: string;
}): Promise<Community> {
  return api<Community>("/api/v1/community/communities", {
    method: "POST",
    body: JSON.stringify(args),
  });
}

export function getCommunityPreview(slug: string): Promise<CommunityPreview> {
  return api<CommunityPreview>(`/api/v1/community/communities/${encodeURIComponent(slug)}`);
}

export function updateCommunity(
  communityId: string,
  args: { name?: string; description?: string },
): Promise<Community> {
  return api<Community>(`/api/v1/community/communities/${communityId}`, {
    method: "PATCH",
    body: JSON.stringify(args),
  });
}

export function deleteCommunity(communityId: string): Promise<{ status: string }> {
  return api<{ status: string }>(`/api/v1/community/communities/${communityId}`, {
    method: "DELETE",
  });
}

export function leaveCommunity(communityId: string): Promise<{ status: string }> {
  return api<{ status: string }>(
    `/api/v1/community/communities/${communityId}/leave`,
    { method: "POST" },
  );
}

export function getMyCommunities(): Promise<MyCommunitiesResponse> {
  return api<MyCommunitiesResponse>("/api/v1/community/communities/mine");
}

export function requestToJoin(communityId: string): Promise<JoinRequest> {
  return api<JoinRequest>(
    `/api/v1/community/communities/${communityId}/join-requests`,
    { method: "POST" },
  );
}

export function withdrawJoinRequest(
  communityId: string,
): Promise<{ status: string }> {
  return api<{ status: string }>(
    `/api/v1/community/communities/${communityId}/join-requests/withdraw`,
    { method: "POST" },
  );
}

export function listJoinRequests(communityId: string): Promise<JoinRequest[]> {
  return api<JoinRequest[]>(
    `/api/v1/community/communities/${communityId}/join-requests`,
  );
}

export function approveJoinRequest(
  communityId: string,
  requestId: string,
): Promise<JoinRequest> {
  return api<JoinRequest>(
    `/api/v1/community/communities/${communityId}/join-requests/${requestId}/approve`,
    { method: "POST" },
  );
}

export function declineJoinRequest(
  communityId: string,
  requestId: string,
  note?: string,
): Promise<JoinRequest> {
  return api<JoinRequest>(
    `/api/v1/community/communities/${communityId}/join-requests/${requestId}/decline`,
    { method: "POST", body: JSON.stringify({ note: note ?? null }) },
  );
}

export function createListing(args: {
  item_id: string;
  allowed_exchange_types: ExchangeType[];
  quantity_available: number;
  community_ids?: string[];
  share_in_radius?: boolean;
  share_radius_miles?: number;
  description_override?: string;
}): Promise<Listing> {
  return api<Listing>("/api/v1/community/listings", {
    method: "POST",
    body: JSON.stringify({
      item_id: args.item_id,
      allowed_exchange_types: args.allowed_exchange_types,
      quantity_available: args.quantity_available,
      community_ids: args.community_ids ?? [],
      share_in_radius: args.share_in_radius ?? false,
      share_radius_miles: args.share_radius_miles,
      description_override: args.description_override,
    }),
  });
}

export function updateListing(
  listingId: string,
  patch: Partial<{
    allowed_exchange_types: ExchangeType[];
    quantity_available: number;
    community_ids: string[];
    share_in_radius: boolean;
    share_radius_miles: number;
    description_override: string;
    availability_status: "available" | "paused" | "removed";
  }>,
): Promise<Listing> {
  return api<Listing>(`/api/v1/community/listings/${listingId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteListing(listingId: string): Promise<{ status: string }> {
  return api<{ status: string }>(`/api/v1/community/listings/${listingId}`, {
    method: "DELETE",
  });
}

export function listMyListings(): Promise<Listing[]> {
  return api<Listing[]>("/api/v1/community/listings/mine");
}

export function getListing(listingId: string): Promise<Listing> {
  return api<Listing>(`/api/v1/community/listings/${listingId}`);
}

export function getFeed(opts: {
  community_id?: string;
  category?: string;
  radius_miles_max?: number;
  cursor?: number;
  limit?: number;
} = {}): Promise<FeedResponse> {
  const params = new URLSearchParams();
  if (opts.community_id) params.set("community_id", opts.community_id);
  if (opts.category) params.set("category", opts.category);
  if (opts.radius_miles_max != null) params.set("radius_miles_max", String(opts.radius_miles_max));
  if (opts.cursor != null) params.set("cursor", String(opts.cursor));
  if (opts.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return api<FeedResponse>(`/api/v1/community/feed${qs ? `?${qs}` : ""}`);
}
