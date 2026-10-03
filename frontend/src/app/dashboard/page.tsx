/* ── Dashboard Page — main operational view ── */
"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import {
  TrafficCone, Navigation, Bell, MessageSquare,
  Clock, Brain, AlertTriangle, Play, Square,
  Map as MapIcon, Route, Ambulance, ShieldCheck, Flame, Car, Menu, X,
} from "lucide-react";
import Sidebar from "@/components/Sidebar";
import SignalPanel from "@/components/SignalPanel";
import RoutingPanel from "@/components/RoutingPanel";
import AlertPanel from "@/components/AlertPanel";
import ChatInterface from "@/components/ChatInterface";
import Timeline from "@/components/Timeline";
import SummaryPanel from "@/components/SummaryPanel";
import { BackendStatusBanner, Toaster } from "@/components/StatusOverlays";
import { useWebSocket } from "@/lib/useWebSocket";
import { useTrafficStore } from "@/lib/store";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { VehicleType } from "@/lib/types";

// Mapbox must be client-side only
const TrafficMap = dynamic(() => import("@/components/TrafficMap"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full flex items-center justify-center bg-slate-50">
      <div className="text-sm text-muted">Loading map…</div>
    </div>
  ),
});

const TABS = [
  { id: "signals", label: "Signals", icon: TrafficCone },
  { id: "routing", label: "Routing", icon: Navigation },
  { id: "alerts", label: "Alerts", icon: Bell },
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "timeline", label: "Timeline", icon: Clock },
  { id: "summary", label: "Summary", icon: Brain },
] as const;

export default function DashboardPage() {
  useWebSocket();
  const [activeTab, setActiveTab] = useState("signals");
  const incident = useTrafficStore((s) => s.incident);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const pushToast = useTrafficStore((s) => s.pushToast);
  const processing = useTrafficStore((s) => s.processing);
  const dashboardMode = useTrafficStore((s) => s.dashboardMode);
  const setDashboardMode = useTrafficStore((s) => s.setDashboardMode);
  const vehicleType = useTrafficStore((s) => s.vehicleType);
  const setVehicleType = useTrafficStore((s) => s.setVehicleType);

  const VEHICLE_OPTIONS: { value: VehicleType; label: string; icon: typeof Car }[] = [
    { value: "normal", label: "Normal", icon: Car },
    { value: "ambulance", label: "Ambulance", icon: Ambulance },
    { value: "police", label: "Police", icon: ShieldCheck },
    { value: "fire_brigade", label: "Fire", icon: Flame },
  ];

  const handleTrigger = async () => {
    setTriggerLoading(true);
    try {
      await api.triggerIncident("HIGH");
    } catch (e) {
      pushToast(errorMessage(e));
    } finally {
      setTriggerLoading(false);
    }
  };

  const handleResolve = async () => {
    try {
      await api.resolveIncident();
    } catch (e) {
      pushToast(errorMessage(e));
    }
  };

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      {/* Left Sidebar — fixed on large screens, a drawer below 1024px */}
      <div className="hidden lg:flex">
        <Sidebar />
      </div>
      {sidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-40 flex">
          <div className="absolute inset-0 bg-slate-900/30" onClick={() => setSidebarOpen(false)} />
          <div className="relative z-10 h-full shadow-xl">
            <Sidebar />
            <button
              onClick={() => setSidebarOpen(false)}
              aria-label="Close sidebar"
              className="absolute top-4 right-3 text-muted hover:text-foreground"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Main Area */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <BackendStatusBanner />

        {/* Top Control Bar */}
        <div className="min-h-12 border-b border-border bg-white flex flex-wrap items-center justify-between gap-2 px-3 sm:px-4 py-2">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(true)}
              aria-label="Open sidebar"
              className="lg:hidden text-muted hover:text-foreground"
            >
              <Menu className="w-4 h-4" />
            </button>
            <h2 className="hidden sm:block text-sm font-semibold text-foreground">
              Command Dashboard
            </h2>
            {incident && (
              <span className="flex items-center gap-1 text-xs text-danger font-medium animate-pulse">
                <AlertTriangle className="w-3.5 h-3.5" />
                Active Incident
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Mode Toggle */}
            <div className="flex bg-slate-100 rounded-lg p-0.5">
              <button
                onClick={() => setDashboardMode("overview")}
                className={cn(
                  "flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md transition-colors",
                  dashboardMode === "overview"
                    ? "bg-white text-foreground shadow-sm"
                    : "text-muted hover:text-foreground"
                )}
              >
                <MapIcon className="w-3 h-3" />
                <span className="hidden sm:inline">Overview</span>
              </button>
              <button
                onClick={() => setDashboardMode("route")}
                className={cn(
                  "flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md transition-colors",
                  dashboardMode === "route"
                    ? "bg-white text-foreground shadow-sm"
                    : "text-muted hover:text-foreground"
                )}
              >
                <Route className="w-3 h-3" />
                <span className="hidden sm:inline">Route Planning</span>
              </button>
            </div>

            {/* Vehicle Selector (route mode only) */}
            {dashboardMode === "route" && (
              <div className="flex bg-slate-100 rounded-lg p-0.5">
                {VEHICLE_OPTIONS.map((opt) => {
                  const Icon = opt.icon;
                  return (
                    <button
                      key={opt.value}
                      onClick={() => setVehicleType(opt.value)}
                      title={opt.label}
                      className={cn(
                        "flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md transition-colors",
                        vehicleType === opt.value
                          ? "bg-white text-foreground shadow-sm"
                          : "text-muted hover:text-foreground"
                      )}
                    >
                      <Icon className="w-3 h-3" />
                      <span className="hidden sm:inline">{opt.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
            {!incident ? (
              <button
                onClick={handleTrigger}
                disabled={triggerLoading || processing}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-danger text-white rounded-lg hover:bg-danger/90 disabled:opacity-50 transition-colors"
              >
                <Play className="w-3 h-3" />
                {triggerLoading ? "Triggering…" : "Simulate Incident"}
              </button>
            ) : (
              <button
                onClick={handleResolve}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-success text-white rounded-lg hover:bg-success/90 transition-colors"
              >
                <Square className="w-3 h-3" />
                Resolve Incident
              </button>
            )}
          </div>
        </div>

        {/* Content: Map + Right Panel (stacked below 768px) */}
        <div className="flex-1 flex flex-col md:flex-row overflow-hidden min-h-0">
          {/* Map */}
          <div className="h-[45%] md:h-full md:w-[65%] shrink-0">
            <TrafficMap />
          </div>

          {/* Right Panel */}
          <div className="flex-1 min-h-0 md:w-[35%] border-t md:border-t-0 md:border-l border-border flex flex-col bg-white">
            {/* Tabs */}
            <div className="flex border-b border-border overflow-x-auto">
              {TABS.map((tab) => {
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      "flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium whitespace-nowrap transition-colors border-b-2",
                      activeTab === tab.id
                        ? "border-primary text-primary"
                        : "border-transparent text-muted hover:text-foreground"
                    )}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {tab.label}
                  </button>
                );
              })}
            </div>

            {/* Tab Content */}
            <div className="flex-1 overflow-y-auto p-3">
              {activeTab === "signals" && <SignalPanel />}
              {activeTab === "routing" && <RoutingPanel />}
              {activeTab === "alerts" && <AlertPanel />}
              {activeTab === "chat" && <ChatInterface />}
              {activeTab === "timeline" && <Timeline />}
              {activeTab === "summary" && <SummaryPanel />}
            </div>
          </div>
        </div>
      </div>
      <Toaster />
    </div>
  );
}
