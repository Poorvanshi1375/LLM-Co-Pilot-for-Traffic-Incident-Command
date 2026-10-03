/* ── Routing Panel — route intelligence cards + diversion display ── */
"use client";

import {
  Navigation, ArrowRight, Shield, TrendingDown, Clock,
  Route, Download, AlertTriangle, Gauge, TrafficCone, Siren,
} from "lucide-react";
import { useTrafficStore } from "@/lib/store";
import { cn, confidenceColor } from "@/lib/utils";
import { api } from "@/lib/api";
import type { CandidateRoute } from "@/lib/types";
import { FallbackBadge, AgentsWorking } from "@/components/StatusOverlays";

const COLOR_MAP: Record<string, string> = {
  "#10B981": "bg-emerald-500",
  "#F59E0B": "bg-amber-500",
  "#EF4444": "bg-red-500",
};

// Route colour comes from the route's average risk score, not its rank
const COLOR_LABEL: Record<string, string> = {
  "#10B981": "Low Risk",
  "#F59E0B": "Moderate Risk",
  "#EF4444": "High Risk",
};

function RouteCard({ route, isSelected, onSelect }: {
  route: CandidateRoute;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const barColor = COLOR_MAP[route.color] || "bg-slate-500";
  const label = COLOR_LABEL[route.color] || "Route";

  return (
    <button
      onClick={onSelect}
      className={cn(
        "w-full text-left border rounded-lg p-3 transition-all",
        isSelected
          ? "border-primary bg-primary/5 shadow-sm"
          : "border-border bg-white hover:border-primary/40",
      )}
    >
      {/* Color bar + rank */}
      <div className="flex items-center gap-2 mb-2">
        <div className={cn("w-1 h-8 rounded-full", barColor)} />
        <div>
          <p className="text-xs font-bold text-foreground">
            Route {route.route_index + 1}
            {route.route_index === 0 && (
              <span className="ml-1.5 text-[10px] font-semibold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                BEST
              </span>
            )}
          </p>
          <p className="text-[10px] text-muted">{label}</p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div className="flex items-center gap-1 text-muted">
          <Route className="w-3 h-3" />
          <span>{route.total_length_km.toFixed(2)} km</span>
        </div>
        <div className="flex items-center gap-1 text-muted">
          <Clock className="w-3 h-3" />
          <span>{route.total_travel_time_min.toFixed(1)} min</span>
        </div>
        <div className="flex items-center gap-1 text-muted">
          <Gauge className="w-3 h-3" />
          <span>Density: {route.avg_density.toFixed(1)}</span>
        </div>
        <div className="flex items-center gap-1 text-muted">
          <AlertTriangle className="w-3 h-3" />
          <span>Risk: {route.avg_accident_score.toFixed(2)}</span>
        </div>
      </div>

      {/* Weather penalty */}
      {route.avg_weather_penalty > 1 && (
        <div className="flex items-center gap-1 mt-2 text-[10px] text-amber-600 bg-amber-50 rounded px-2 py-1">
          <TrafficCone className="w-3 h-3" />
          <span>Weather penalty: {route.avg_weather_penalty.toFixed(1)}x</span>
        </div>
      )}

      {/* Signal Preemptions (emergency vehicles) */}
      {route.signal_preemptions && route.signal_preemptions.length > 0 && (
        <div className="mt-2 text-[10px] text-blue-600 bg-blue-50 rounded px-2 py-1">
          <div className="flex items-center gap-1 mb-0.5">
            <Siren className="w-3 h-3" />
            <span className="font-semibold">{route.signal_preemptions.length} Signal Preemptions</span>
          </div>
          {route.signal_preemptions.slice(0, 3).map((sp, i) => (
            <p key={i} className="truncate">{sp.intersection}: {sp.action}</p>
          ))}
          {route.signal_preemptions.length > 3 && (
            <p className="text-muted">+{route.signal_preemptions.length - 3} more</p>
          )}
        </div>
      )}
    </button>
  );
}

export default function RoutingPanel() {
  const agentOutput = useTrafficStore((s) => s.agentOutput);
  const diversion = agentOutput?.diversion;
  const dashboardMode = useTrafficStore((s) => s.dashboardMode);
  const candidateRoutes = useTrafficStore((s) => s.candidateRoutes);
  const selectedRouteIndex = useTrafficStore((s) => s.selectedRouteIndex);
  const setSelectedRouteIndex = useTrafficStore((s) => s.setSelectedRouteIndex);
  const routeWeatherCondition = useTrafficStore((s) => s.routeWeatherCondition);
  const routeLoading = useTrafficStore((s) => s.routeLoading);
  const processing = useTrafficStore((s) => s.processing);

  /* ── Route Intelligence Mode ── */
  if (dashboardMode === "route") {
    if (routeLoading) {
      return (
        <div className="flex flex-col items-center justify-center h-full text-muted py-12">
          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin mb-3" />
          <p className="text-sm font-medium">Computing optimal routes...</p>
        </div>
      );
    }

    if (candidateRoutes.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center h-full text-muted py-12">
          <Route className="w-10 h-10 mb-3 text-slate-300" />
          <p className="text-sm font-medium">Route Intelligence</p>
          <p className="text-xs mt-1 text-center px-4">
            Search or click on the map to set origin & destination, then routes will be computed automatically.
          </p>
        </div>
      );
    }

    return (
      <div className="p-1 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Route className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-semibold text-foreground">Route Intelligence</h3>
          </div>
          <button
            onClick={() => api.downloadRoutesCsv()}
            className="flex items-center gap-1 text-[10px] text-primary hover:underline"
            title="Export routes as CSV"
          >
            <Download className="w-3 h-3" />
            CSV
          </button>
        </div>

        {routeWeatherCondition && routeWeatherCondition !== "clear" && (
          <div className="flex items-center gap-1.5 text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-1.5">
            <TrafficCone className="w-3.5 h-3.5" />
            <span className="capitalize">{routeWeatherCondition} conditions active</span>
          </div>
        )}

        <div className="space-y-2">
          {candidateRoutes.map((route) => (
            <RouteCard
              key={route.route_index}
              route={route}
              isSelected={selectedRouteIndex === route.route_index}
              onSelect={() => setSelectedRouteIndex(route.route_index)}
            />
          ))}
        </div>
      </div>
    );
  }

  /* ── Overview / Incident Diversion Mode ── */
  if (!diversion && processing) return <AgentsWorking what="The diversion route" />;
  if (!diversion) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted py-12">
        <Navigation className="w-10 h-10 mb-3 text-slate-300" />
        <p className="text-sm font-medium">No diversion route</p>
        <p className="text-xs mt-1">Diversion will appear when incident is detected</p>
      </div>
    );
  }

  return (
    <div className="p-1">
      <div className="flex items-center gap-2 mb-3">
        <Navigation className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">Dynamic Diversion Route</h3>
        <FallbackBadge source={diversion.source} className="ml-auto" />
      </div>

      <div className="border border-border rounded-lg p-4 bg-white">
        {/* Route Streets */}
        <div className="mb-4">
          <span className="text-xs text-muted font-medium">Recommended Path</span>
          {diversion.avoids_street && (
            <p className="text-[11px] text-slate-600 mt-1">
              Leave <strong>{diversion.avoids_street}</strong> before the incident, take these streets, then rejoin it past the blocked zone:
            </p>
          )}
          <div className="flex flex-wrap items-center gap-1 mt-1.5">
            {diversion.route_street_names.map((street: string, i: number) => (
              <span key={i} className="flex items-center gap-1">
                <span className="text-xs font-medium text-foreground bg-primary/5 px-2 py-0.5 rounded">
                  {street}
                </span>
                {i < diversion.route_street_names.length - 1 && (
                  <ArrowRight className="w-3 h-3 text-muted" />
                )}
              </span>
            ))}
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="text-center p-2 bg-emerald-50 rounded-lg">
            <TrendingDown className="w-4 h-4 text-success mx-auto mb-1" />
            <p className="text-xs text-muted" title="Average risk along the detour compared with staying on the normal route through the incident">
              Risk vs. normal route
            </p>
            <p className={cn("text-sm font-bold", diversion.risk_delta_pct >= 0 ? "text-success" : "text-danger")}>
              {diversion.risk_delta_pct >= 0
                ? `${diversion.risk_delta_pct.toFixed(0)}% lower`
                : `${Math.abs(diversion.risk_delta_pct).toFixed(0)}% higher`}
            </p>
          </div>
          <div className="text-center p-2 bg-blue-50 rounded-lg">
            <Clock className="w-4 h-4 text-primary mx-auto mb-1" />
            <p className="text-xs text-muted">Extra Time</p>
            <p className="text-sm font-bold text-primary">
              +{diversion.time_delta_min.toFixed(1)} min
            </p>
          </div>
          <div className="text-center p-2 bg-amber-50 rounded-lg">
            <Shield className="w-4 h-4 text-warning mx-auto mb-1" />
            <p className="text-xs text-muted">Vol. Redirect</p>
            <p className="text-sm font-bold text-warning">
              {diversion.diversion_volume_pct.toFixed(0)}%
            </p>
          </div>
        </div>

        {/* Narrative */}
        <div className="space-y-2">
          <div>
            <span className="text-xs text-muted font-medium">Diversion Narrative</span>
            <p className="text-xs text-foreground leading-relaxed mt-1">
              {diversion.diversion_text}
            </p>
          </div>
          <div>
            <span className="text-xs text-muted font-medium">Why Safer</span>
            <p className="text-xs text-foreground leading-relaxed mt-1">
              {diversion.why_safer}
            </p>
          </div>
        </div>

        {/* Confidence */}
        <div className="flex justify-end mt-3">
          <span className={cn("text-xs font-semibold", confidenceColor(diversion.confidence))}>
            Confidence: {(diversion.confidence * 100).toFixed(0)}%
          </span>
        </div>
      </div>
    </div>
  );
}
