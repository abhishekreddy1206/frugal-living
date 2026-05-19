import type { PantryCaptureResponse, PantryItem } from "./types";

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
