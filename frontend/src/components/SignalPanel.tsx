/* ── Signal Panel — signal re-timing recommendations ── */
"use client";

import { TrafficCone, Clock, MapPin, TrendingUp } from "lucide-react";
import { useTrafficStore } from "@/lib/store";
import { cn, confidenceColor } from "@/lib/utils";
import { FallbackBadge, AgentsWorking } from "@/components/StatusOverlays";

export default function SignalPanel() {
  const agentOutput = useTrafficStore((s) => s.agentOutput);
  const recs = agentOutput?.signal_recommendations || [];
  const processing = useTrafficStore((s) => s.processing);

  if (!recs.length && processing) return <AgentsWorking what="Signal re-timing plans" />;
  if (!recs.length) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted py-12">
        <TrafficCone className="w-10 h-10 mb-3 text-slate-300" />
        <p className="text-sm font-medium">No signal recommendations</p>
        <p className="text-xs mt-1">Trigger an incident to see AI-generated signal plans</p>
      </div>
    );
  }

  return (
    <div className="space-y-3 p-1">
      <div className="flex items-center gap-2 mb-2">
        <TrafficCone className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">
          Signal Re-Timing ({recs.length} intersections)
        </h3>
        <FallbackBadge source={recs[0]?.source} className="ml-auto" />
      </div>

      {recs.map((rec, i) => (
        <div
          key={i}
          className="border border-border rounded-lg p-3 hover:shadow-sm transition-shadow bg-white"
        >
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-center gap-1.5">
              <MapPin className="w-3.5 h-3.5 text-primary" />
              <span className="text-xs font-semibold text-foreground">
                {rec.intersection_name}
              </span>
            </div>
            <span
              className={cn(
                "text-xs font-semibold",
                confidenceColor(rec.confidence)
              )}
            >
              {(rec.confidence * 100).toFixed(0)}%
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2 text-xs mb-2">
            <div>
              <span className="text-muted" title="No live signal-controller data: this is the model's assumed typical timing">Assumed current</span>
              <p className="font-medium text-foreground">{rec.current_phase}</p>
            </div>
            <div>
              <span className="text-muted">Recommended</span>
              <p className="font-medium text-primary">{rec.recommended_phase}</p>
            </div>
          </div>

          <div className="flex items-center gap-3 text-[10px] text-muted mb-1.5">
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {rec.phase_duration_s}s phase
            </span>
            <span className="flex items-center gap-1">
              <TrendingUp className="w-3 h-3" />
              {rec.upstream_distance_m.toFixed(0)}m upstream
            </span>
          </div>

          <p className="text-[11px] text-slate-600 leading-relaxed">
            {rec.reason}
          </p>

          {rec.sensor_citation && (
            <p className="text-[10px] text-muted mt-1 italic">
              Source: {rec.sensor_citation}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
