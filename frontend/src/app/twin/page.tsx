/* ── Digital Twin — split-screen comparison view ── */
"use client";

import { useEffect, useState, useMemo } from "react";
import dynamic from "next/dynamic";
import { ArrowLeft, Timer, TrendingDown, Zap } from "lucide-react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { speedToColor, cn } from "@/lib/utils";
import type { TwinData, SegmentSpeed } from "@/lib/types";

const Map = dynamic(
  () => import("react-map-gl/mapbox").then((mod) => mod.default),
  { ssr: false }
);

const Source = dynamic(
  () => import("react-map-gl/mapbox").then((mod) => mod.Source),
  { ssr: false }
);

const Layer = dynamic(
  () => import("react-map-gl/mapbox").then((mod) => mod.Layer),
  { ssr: false }
);

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";
const CENTER = { longitude: -73.9442, latitude: 40.6782, zoom: 12.5 };

function TwinMap({
  segments,
  title,
  subtitle,
  borderColor,
}: {
  segments: SegmentSpeed[];
  title: string;
  subtitle: string;
  borderColor: string;
}) {
  const geojson = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: segments.map((seg) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [seg.lon, seg.lat] },
        properties: {
          color: speedToColor(seg.speed, seg.free_flow_speed),
          speed: Math.round(seg.speed),
        },
      })),
    }),
    [segments]
  );

  return (
    <div className="flex-1 flex flex-col h-full">
      <div
        className={cn(
          "h-10 flex items-center justify-between px-4 border-b-2",
          borderColor
        )}
      >
        <span className="text-sm font-semibold text-foreground">{title}</span>
        <span className="text-xs text-muted">{subtitle}</span>
      </div>
      <div className="flex-1">
        <Map
          initialViewState={CENTER}
          style={{ width: "100%", height: "100%" }}
          mapStyle="mapbox://styles/mapbox/light-v11"
          mapboxAccessToken={MAPBOX_TOKEN}
          attributionControl={false}
        >
          <Source id={`twin-${title}`} type="geojson" data={geojson}>
            <Layer
              id={`twin-circles-${title}`}
              type="circle"
              paint={{
                "circle-radius": 7,
                "circle-color": ["get", "color"],
                "circle-stroke-width": 1.5,
                "circle-stroke-color": "#ffffff",
                "circle-opacity": 0.9,
              }}
            />
          </Source>
        </Map>
      </div>
    </div>
  );
}

export default function TwinPage() {
  const router = useRouter();
  const [data, setData] = useState<TwinData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchTwin = async () => {
      try {
        const res = await api.getTwinData();
        setData(res);
      } catch {
        // use empty data
      } finally {
        setLoading(false);
      }
    };
    fetchTwin();
    const interval = setInterval(fetchTwin, 10000);
    return () => clearInterval(interval);
  }, []);

  const avgNoAction =
    data?.no_action?.length
      ? Math.round(
          data.no_action.reduce((a, s) => a + s.speed, 0) / data.no_action.length
        )
      : 0;

  const avgWithAction =
    data?.with_action?.length
      ? Math.round(
          data.with_action.reduce((a, s) => a + s.speed, 0) /
            data.with_action.length
        )
      : 0;

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* Top Bar */}
      <div className="h-14 border-b border-border bg-white flex items-center justify-between px-6">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push("/dashboard")}
            className="flex items-center gap-1 text-sm text-muted hover:text-foreground transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </button>
          <div className="w-px h-5 bg-border" />
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-primary" />
            <h1 className="text-sm font-semibold text-foreground">
              Digital Twin — What-If Analysis
            </h1>
          </div>
        </div>

        {/* Metrics */}
        {data && (
          <div className="flex items-center gap-6">
            <div className="text-center">
              <p className="text-[10px] text-muted">Avg Speed (No Action)</p>
              <p className="text-sm font-bold text-danger">{avgNoAction} mph</p>
            </div>
            <div className="text-center">
              <p className="text-[10px] text-muted">Avg Speed (With AI)</p>
              <p className="text-sm font-bold text-success">{avgWithAction} mph</p>
            </div>
            <div className="text-center">
              <p className="text-[10px] text-muted" title="Illustrative estimate: assumes intervention shortens the incident's impact by 30%">
                Time Saved (est.)
              </p>
              <p className="text-sm font-bold text-primary flex items-center gap-1">
                <Timer className="w-3.5 h-3.5" />
                {data.time_saved_min?.toFixed(1) ?? "—"} min
              </p>
            </div>
            <div className="flex items-center gap-1 text-sm font-semibold text-success">
              <TrendingDown className="w-4 h-4" />
              {avgWithAction > 0
                ? `+${(((avgWithAction - avgNoAction) / Math.max(avgNoAction, 1)) * 100).toFixed(0)}%`
                : "—"}
            </div>
          </div>
        )}
      </div>

      {/* Split Maps */}
      <div className="flex-1 flex">
        {loading ? (
          <div className="flex-1 flex items-center justify-center text-muted">
            <p className="text-sm">Loading twin data…</p>
          </div>
        ) : data ? (
          <>
            <TwinMap
              segments={data.no_action || []}
              title="Without TrafficMind"
              subtitle="No intervention scenario"
              borderColor="border-danger"
            />
            <div className="w-px bg-border" />
            <TwinMap
              segments={data.with_action || []}
              title="With TrafficMind"
              subtitle="AI-optimized response"
              borderColor="border-success"
            />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted">
            <p className="text-sm">No twin data available. Trigger an incident first.</p>
          </div>
        )}
      </div>
    </div>
  );
}
