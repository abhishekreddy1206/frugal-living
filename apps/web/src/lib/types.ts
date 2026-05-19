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
