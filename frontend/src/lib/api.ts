/* ── API Client ── */
import type { Settings } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const ADMIN_TOKEN_KEY = "trafficmind_admin_token";

/** Error carrying the HTTP status and the server's `detail` message. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch {
    throw new ApiError(0, "Cannot reach the backend — it may still be starting up");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

/* Operator token: typed once in the sidebar, kept only in this browser */
export function getAdminToken(): string {
  try { return localStorage.getItem(ADMIN_TOKEN_KEY) || ""; } catch { return ""; }
}

export function setAdminToken(token: string) {
  try {
    if (token) localStorage.setItem(ADMIN_TOKEN_KEY, token);
    else localStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch { /* storage unavailable */ }
}

function adminHeaders(): Record<string, string> {
  const token = getAdminToken();
  return token ? { "X-Admin-Token": token } : {};
}

export const api = {
  health: () => fetchAPI<any>("/health"),
  getState: () => fetchAPI<any>("/api/state"),
  getAgentOutput: () => fetchAPI<any>("/api/agents"),
  getSignals: () => fetchAPI<any>("/api/signals"),
  getDiversion: () => fetchAPI<any>("/api/diversion"),
  getAlerts: () => fetchAPI<any>("/api/alerts"),
  getDensity: () => fetchAPI<any>("/api/density"),
  getTimeline: () => fetchAPI<any>("/api/timeline"),
  getHotspots: () => fetchAPI<any>("/api/hotspots"),
  getMetrics: () => fetchAPI<any>("/api/metrics"),
  getTwinData: () => fetchAPI<any>("/api/twin"),
  getChatHistory: () => fetchAPI<any>("/api/chat/history"),
  getDocuments: () => fetchAPI<any>("/api/documents"),
  getWeather: () => fetchAPI<any>("/api/weather"),
  getPredictedHotspots: () => fetchAPI<any>("/api/hotspots/predicted"),

  geocodeSearch: (query: string) =>
    fetchAPI<any>(`/api/geocode?q=${encodeURIComponent(query)}`),

  findRoutes: (origin: { lat: number; lon: number }, dest: { lat: number; lon: number }, k: number = 3, vehicleType: string = "normal") =>
    fetchAPI<any>("/api/routes", {
      method: "POST",
      body: JSON.stringify({
        origin_lat: origin.lat, origin_lon: origin.lon,
        dest_lat: dest.lat, dest_lon: dest.lon,
        k, vehicle_type: vehicleType,
      }),
    }),

  downloadRoutesCsv: () => {
    const url = `${API_URL}/api/routes/csv`;
    const a = document.createElement("a");
    a.href = url;
    a.download = "routes.csv";
    a.click();
  },

  triggerIncident: (severity: string = "HIGH") =>
    fetchAPI<any>("/api/trigger-incident", {
      method: "POST",
      body: JSON.stringify({ severity }),
    }),

  resolveIncident: () =>
    fetchAPI<any>("/api/resolve-incident", { method: "POST" }),

  sendChat: (message: string) =>
    fetchAPI<any>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  getSettings: () => fetchAPI<Settings>("/api/settings"),

  setAutoPost: (enabled: boolean) =>
    fetchAPI<any>("/api/settings/auto-post", {
      method: "POST",
      headers: adminHeaders(),
      body: JSON.stringify({ enabled }),
    }),

  setAutoDetect: (enabled: boolean) =>
    fetchAPI<any>("/api/settings/auto-detect", {
      method: "POST",
      headers: adminHeaders(),
      body: JSON.stringify({ enabled }),
    }),

  sendVoice: async (audioBlob: Blob): Promise<any> => {
    const form = new FormData();
    form.append("audio", audioBlob, "recording.webm");
    let res: Response;
    try {
      res = await fetch(`${API_URL}/api/chat/voice`, { method: "POST", body: form });
    } catch {
      throw new ApiError(0, "Cannot reach the backend — it may still be starting up");
    }
    if (!res.ok) throw new ApiError(res.status, `Voice request failed (${res.status})`);
    return res.json();
  },
};

/** Human-readable message for any thrown value. */
export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export { API_URL };
