/* ── Digital Twin — side-by-side what-if comparison ── */
"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { ArrowLeft, Timer, TrendingUp, Zap, Play, Loader2, Info } from "lucide-react";
import { useRouter } from "next/navigation";
import type { ViewState } from "react-map-gl/mapbox";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { TwinData } from "@/lib/types";

// Mapbox needs the browser: load the map component client-side only
const TwinMap = dynamic(() => import("@/components/TwinMap"), {
  ssr: false,
  loading: () => <div className="w-full h-full bg-slate-50" />,
});

const CENTER: Partial<ViewState> = { longitude: -73.9442, latitude: 40.6782, zoom: 12.5 };

function avgSpeed(rows: { speed: number }[] | undefined): number {
  return rows?.length ? rows.reduce((a, s) => a + s.speed, 0) / rows.length : 0;
}

export default function TwinPage() {
  const router = useRouter();
  const [data, setData] = useState<TwinData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  // Both maps share one view, so panning one pans the other
  const [view, setView] = useState<Partial<ViewState>>(CENTER);
  const [centered, setCentered] = useState<string | null>(null);

  useEffect(() => {
    const fetchTwin = async () => {
      try {
        setData(await api.getTwinData());
        setError("");
      } catch (e) {
        setError(errorMessage(e));
      } finally {
        setLoading(false);
      }
    };
    fetchTwin();
    const interval = setInterval(fetchTwin, 10000);
    return () => clearInterval(interval);
  }, []);

  // Centre on the incident the first time it appears
  const incident = data?.incident ?? null;
  useEffect(() => {
    if (incident && centered !== incident.incident_id) {
      setView({ longitude: incident.lon, latitude: incident.lat, zoom: 13.5 });
      setCentered(incident.incident_id);
    }
  }, [incident, centered]);

  const simulate = async () => {
    setStarting(true);
    try {
      await api.triggerIncident("HIGH");
      setData(await api.getTwinData());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  };

  const noAction = avgSpeed(data?.no_action);
  const withAction = avgSpeed(data?.with_action);
  const gainPct = noAction > 0 ? ((withAction - noAction) / noAction) * 100 : 0;
  const hasIncident = Boolean(incident && data?.no_action?.length);

  return (
    <div className="flex flex-col h-dvh bg-background">
      {/* Top bar */}
      <div className="border-b border-border bg-white flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 sm:px-6 py-2.5">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={() => router.push("/dashboard")}
            className="flex items-center gap-1 text-sm text-muted hover:text-foreground transition-colors shrink-0"
          >
            <ArrowLeft className="w-4 h-4" />
            <span className="hidden sm:inline">Back to Dashboard</span>
            <span className="sm:hidden">Back</span>
          </button>
          <div className="w-px h-5 bg-border" />
          <div className="flex items-center gap-2 min-w-0">
            <Zap className="w-4 h-4 text-primary shrink-0" />
            <h1 className="text-sm font-semibold text-foreground truncate">Digital Twin — What-If</h1>
          </div>
        </div>

        {hasIncident && (
          <div className="grid grid-cols-3 gap-4 sm:gap-6 text-center">
            <div>
              <p className="text-[10px] text-muted">Avg speed, no action</p>
              <p className="text-sm font-bold text-danger">{noAction.toFixed(0)} mph</p>
            </div>
            <div>
              <p className="text-[10px] text-muted">Avg speed, with AI plan</p>
              <p className="text-sm font-bold text-success flex items-center justify-center gap-1">
                {withAction.toFixed(0)} mph
                <span className="text-[10px] font-semibold flex items-center"><TrendingUp className="w-3 h-3" />{gainPct.toFixed(0)}%</span>
              </p>
            </div>
            <div>
              <p className="text-[10px] text-muted">Time saved (est.)</p>
              <p className="text-sm font-bold text-primary flex items-center justify-center gap-1">
                <Timer className="w-3.5 h-3.5" />
                {data?.time_saved_min?.toFixed(1)} min
              </p>
            </div>
          </div>
        )}
      </div>

      {hasIncident && (
        <div className="flex items-start gap-2 px-4 sm:px-6 py-2 text-[11px] text-slate-600 bg-slate-50 border-b border-border">
          <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-muted" />
          <span>
            Incident on <strong>{incident?.street_name}</strong>. Left: congestion spreads around it if nothing is done.
            Right: the diversion and signal changes in place. Both sides come from a simple illustrative model, not a traffic simulation.
            The two maps move together.
          </span>
        </div>
      )}

      {/* Maps, or an explanation of what is missing */}
      <div className="flex-1 min-h-0">
        {loading ? (
          <div className="h-full flex items-center justify-center text-muted text-sm">Loading twin data…</div>
        ) : hasIncident ? (
          <div className="h-full flex flex-col md:flex-row">
            {[
              { id: "before", title: "Without TrafficMind", subtitle: "No intervention", rows: data!.no_action, border: "border-danger" },
              { id: "after", title: "With TrafficMind", subtitle: "Diversion + signal plan", rows: data!.with_action, border: "border-success" },
            ].map((side, i) => (
              <div key={side.id} className={cn("flex-1 min-h-0 flex flex-col", i === 0 && "border-b md:border-b-0 md:border-r border-border")}>
                <div className={cn("h-9 shrink-0 flex items-center justify-between px-4 border-b-2 bg-white", side.border)}>
                  <span className="text-sm font-semibold text-foreground">{side.title}</span>
                  <span className="text-xs text-muted">{side.subtitle}</span>
                </div>
                <div className="flex-1 min-h-0">
                  <TwinMap id={side.id} segments={side.rows} incident={incident} viewState={view} onMove={setView} />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="h-full flex items-center justify-center p-6">
            <div className="max-w-sm text-center">
              <Zap className="w-10 h-10 mx-auto mb-3 text-slate-300" />
              <p className="text-sm font-semibold text-foreground">No active incident to compare</p>
              <p className="text-xs text-muted mt-1.5 leading-relaxed">
                The digital twin compares what happens around an incident with and without TrafficMind&apos;s plan.
                Start a simulated incident to see it.
              </p>
              {error && <p className="text-xs text-danger mt-2">{error}</p>}
              <div className="flex items-center justify-center gap-2 mt-4">
                <button
                  onClick={simulate}
                  disabled={starting}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-danger text-white rounded-lg hover:bg-danger/90 disabled:opacity-50"
                >
                  {starting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                  {starting ? "Starting…" : "Simulate Incident"}
                </button>
                <button
                  onClick={() => router.push("/dashboard")}
                  className="px-3 py-1.5 text-xs font-medium border border-border rounded-lg hover:bg-slate-50"
                >
                  Open dashboard
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
