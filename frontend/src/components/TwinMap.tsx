/* ── Twin Map — one scenario of the digital twin, drawn with the dashboard's traffic style ── */
"use client";

import { useMemo } from "react";
import Map, { Source, Layer, Marker, type ViewState } from "react-map-gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";
import { speedToColor } from "@/lib/utils";
import type { IncidentDetection } from "@/lib/types";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";
const NO_DATA_COLOR = "#9ca3af";

type ScenarioSegment = { segment_id: string; speed: number; free_flow_speed: number };

export default function TwinMap({
  id,
  segments,
  incident,
  viewState,
  onMove,
}: {
  id: string;
  segments: ScenarioSegment[];
  incident: IncidentDetection | null;
  viewState: Partial<ViewState>;
  onMove: (v: ViewState) => void;
}) {
  // Colour each road by this scenario's speed for its monitored segment
  const trafficColor = useMemo(() => {
    if (!segments.length) return NO_DATA_COLOR;
    const expr: unknown[] = ["match", ["get", "s"]];
    for (const seg of segments) expr.push(seg.segment_id, speedToColor(seg.speed, seg.free_flow_speed));
    expr.push(NO_DATA_COLOR);
    return expr as unknown as string;
  }, [segments]);

  return (
    <Map
      {...viewState}
      onMove={(e) => onMove(e.viewState)}
      style={{ width: "100%", height: "100%" }}
      mapStyle="mapbox://styles/mapbox/light-v11"
      mapboxAccessToken={MAPBOX_TOKEN}
      attributionControl={false}
    >
      <Source id={`twin-roads-${id}`} type="geojson" data="/road-network.geojson">
        <Layer
          id={`twin-casing-${id}`}
          type="line"
          paint={{ "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 10, 2.5, 13, 4.5, 16, 9], "line-opacity": 0.85 }}
          layout={{ "line-cap": "round", "line-join": "round" }}
        />
        <Layer
          id={`twin-traffic-${id}`}
          type="line"
          paint={{ "line-color": trafficColor, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.2, 13, 2.6, 16, 6], "line-opacity": 0.9 }}
          layout={{ "line-cap": "round", "line-join": "round" }}
        />
      </Source>
      {incident && (
        <Marker latitude={incident.lat} longitude={incident.lon} anchor="center">
          <div className="w-5 h-5 rounded-full border-2 border-white shadow-lg bg-orange-500 flex items-center justify-center">
            <span className="text-white text-[10px] font-bold">!</span>
          </div>
        </Marker>
      )}
    </Map>
  );
}
