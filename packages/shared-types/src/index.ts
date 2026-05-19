/**
 * Shared TypeScript types between apps/web and apps/mobile (future).
 *
 * Keep this minimal — only types that cross app boundaries (API responses,
 * shared enums). UI-specific types stay in their consuming app.
 */

// ---------- Core ----------
export type UUID = string;

export interface Household {
  id: UUID;
  name: string;
  size: number;
  currency: string;
  locale: string;
  timezone: string;
}

export interface User {
  id: UUID;
  email: string;
  displayName: string | null;
}

export type HouseholdRole = "owner" | "member" | "viewer";

// ---------- Food ----------
export interface PantryItem {
  id: UUID;
  householdId: UUID;
  rawName: string;
  quantity: number | null;
  unit: string | null;
  expiresAt: string | null;
  source: "manual" | "photo_capture" | "receipt_scan" | "barcode" | "imported";
  confidence: number | null;
  photoUrl: string | null;
}

export interface Recipe {
  id: UUID;
  name: string;
  slug: string;
  description: string | null;
  servings: number;
  prepTimeMin: number | null;
  cookTimeMin: number | null;
  estimatedCostPerServingUsd: number | null;
  sourceUrl: string | null;
  sourceAttribution: string | null;
  isAiGenerated: boolean;
}

export interface MealPlan {
  id: UUID;
  householdId: UUID;
  weekStart: string;
  status: "draft" | "active" | "archived";
  targetBudgetUsd: number | null;
}

// ---------- Content ----------
export interface ContentItem {
  id: UUID;
  provider: "youtube" | "rss" | "reddit" | "ai_generated";
  title: string;
  url: string | null;
  author: string | null;
  summary: string | null;
  thumbnailUrl: string | null;
  durationSeconds: number | null;
  publishedAt: string | null;
  topic: "food" | "bills" | "community" | "general";
  tags: string[];
}

// ---------- AI ----------
export type ChatRole = "user" | "assistant" | "system" | "tool";

export interface ChatMessage {
  id: UUID;
  conversationId: UUID;
  role: ChatRole;
  content: string;
  createdAt: string;
}

// ---------- Tracking ----------
export interface SavingsEvent {
  id: UUID;
  householdId: UUID;
  kind:
    | "pantry_stretched"
    | "recipe_substituted"
    | "waste_avoided"
    | "bill_negotiated"
    | "swap_received"
    | "coupon_applied";
  amountUsd: number;
  description: string | null;
  occurredOn: string;
}

export interface Streak {
  id: UUID;
  householdId: UUID;
  kind: "cooked_from_pantry" | "zero_waste_week" | "under_budget_month" | "meal_planned_week";
  currentLength: number;
  longestLength: number;
  lastEventOn: string | null;
}
