/* ── Zustand Store — Real-time traffic state ── */
import { create } from "zustand";
import type {
  SegmentSpeed, RiskEntry, IncidentDetection, AgentOutput,
  ChatMessage, TimelineEntry, Metrics, DensityData, WeatherCondition,
  PredictedHotspot, CandidateRoute, VehicleType, Settings,
} from "./types";

export interface Toast {
  id: number;
  kind: "error" | "info";
  message: string;
}

interface TrafficStore {
  // Connection
  connected: boolean;
  setConnected: (v: boolean) => void;
  /** Time the current disconnected stretch began (ms), for the wake-up banner */
  disconnectedSince: number | null;

  // Feed data
  segments: SegmentSpeed[];
  riskMap: RiskEntry[];
  hour: number;
  setFeedData: (segments: SegmentSpeed[], riskMap: RiskEntry[], hour: number) => void;

  // Incident
  incident: IncidentDetection | null;
  setIncident: (v: IncidentDetection | null) => void;
  processing: boolean;
  setProcessing: (v: boolean) => void;

  // Agent output
  agentOutput: AgentOutput | null;
  setAgentOutput: (v: AgentOutput | null) => void;

  // Chat
  messages: ChatMessage[];
  addMessage: (m: ChatMessage) => void;
  clearMessages: () => void;
  setMessages: (m: ChatMessage[]) => void;

  // Timeline
  timeline: TimelineEntry[];
  setTimeline: (t: TimelineEntry[]) => void;

  // Metrics
  metrics: Metrics | null;
  setMetrics: (m: Metrics) => void;

  // Density
  density: DensityData | null;
  setDensity: (d: DensityData | null) => void;

  // Weather
  weather: WeatherCondition | null;
  setWeather: (w: WeatherCondition | null) => void;

  // Predicted Hotspots
  predictedHotspots: PredictedHotspot[];
  setPredictedHotspots: (h: PredictedHotspot[]) => void;

  // Route Intelligence
  dashboardMode: "overview" | "route";
  setDashboardMode: (m: "overview" | "route") => void;
  vehicleType: VehicleType;
  setVehicleType: (v: VehicleType) => void;
  routeOrigin: { lat: number; lon: number; name: string } | null;
  setRouteOrigin: (o: { lat: number; lon: number; name: string } | null) => void;
  routeDestination: { lat: number; lon: number; name: string } | null;
  setRouteDestination: (d: { lat: number; lon: number; name: string } | null) => void;
  candidateRoutes: CandidateRoute[];
  setCandidateRoutes: (r: CandidateRoute[]) => void;
  selectedRouteIndex: number;
  setSelectedRouteIndex: (i: number) => void;
  routeLoading: boolean;
  setRouteLoading: (v: boolean) => void;
  routeWeatherCondition: string;
  setRouteWeatherCondition: (c: string) => void;

  // UI
  activePanel: string;
  setActivePanel: (p: string) => void;
  incidentStartTime: number | null;
  setIncidentStartTime: (t: number | null) => void;

  // Settings
  autoPost: boolean;
  setAutoPost: (v: boolean) => void;
  settings: Settings | null;
  setSettings: (s: Settings) => void;

  // Toasts
  toasts: Toast[];
  pushToast: (message: string, kind?: Toast["kind"]) => void;
  dismissToast: (id: number) => void;
}

let toastId = 0;

export const useTrafficStore = create<TrafficStore>((set) => ({
  connected: false,
  disconnectedSince: Date.now(),
  setConnected: (connected) => set((s) => ({
    connected,
    disconnectedSince: connected ? null : (s.disconnectedSince ?? Date.now()),
  })),

  segments: [],
  riskMap: [],
  hour: 8.5,
  setFeedData: (segments, riskMap, hour) => set({ segments, riskMap, hour }),

  incident: null,
  setIncident: (incident) => set({ incident }),
  processing: false,
  setProcessing: (processing) => set({ processing }),

  agentOutput: null,
  setAgentOutput: (agentOutput) => set({ agentOutput }),

  messages: [],
  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  clearMessages: () => set({ messages: [] }),
  setMessages: (messages) => set({ messages }),

  timeline: [],
  setTimeline: (timeline) => set({ timeline }),

  metrics: null,
  setMetrics: (metrics) => set({ metrics }),

  density: null,
  setDensity: (density) => set({ density }),

  weather: null,
  setWeather: (weather) => set({ weather }),

  predictedHotspots: [],
  setPredictedHotspots: (predictedHotspots) => set({ predictedHotspots }),

  dashboardMode: "overview",
  setDashboardMode: (dashboardMode) => set({
    dashboardMode,
    ...(dashboardMode === "overview" ? {
      routeOrigin: null, routeDestination: null,
      candidateRoutes: [], selectedRouteIndex: 0,
    } : {}),
  }),
  vehicleType: "normal",
  setVehicleType: (vehicleType) => set({ vehicleType }),
  routeOrigin: null,
  setRouteOrigin: (routeOrigin) => set({ routeOrigin }),
  routeDestination: null,
  setRouteDestination: (routeDestination) => set({ routeDestination }),
  candidateRoutes: [],
  setCandidateRoutes: (candidateRoutes) => set({ candidateRoutes }),
  selectedRouteIndex: 0,
  setSelectedRouteIndex: (selectedRouteIndex) => set({ selectedRouteIndex }),
  routeLoading: false,
  setRouteLoading: (routeLoading) => set({ routeLoading }),
  routeWeatherCondition: "clear",
  setRouteWeatherCondition: (routeWeatherCondition) => set({ routeWeatherCondition }),

  activePanel: "signals",
  setActivePanel: (activePanel) => set({ activePanel }),
  incidentStartTime: null,
  setIncidentStartTime: (incidentStartTime) => set({ incidentStartTime }),

  autoPost: false,
  setAutoPost: (autoPost) => set({ autoPost }),
  settings: null,
  setSettings: (settings) => set({ settings, autoPost: settings.auto_post }),

  toasts: [],
  pushToast: (message, kind = "error") => {
    const id = ++toastId;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, kind, message }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 6000);
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
