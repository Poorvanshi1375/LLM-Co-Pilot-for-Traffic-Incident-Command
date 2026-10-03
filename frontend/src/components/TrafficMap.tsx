/* ── Traffic Map — Mapbox GL + speed-colored markers + route intelligence ── */
"use client";

import { useMemo, useCallback, useEffect, useState, useRef } from "react";
import Map, { Source, Layer, Marker, NavigationControl, type MapRef } from "react-map-gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";
import { useTrafficStore } from "@/lib/store";
import { speedToColor, severityColor } from "@/lib/utils";
import { api, errorMessage } from "@/lib/api";
import { Search, MapPin, X, Loader2 } from "lucide-react";
import type { SegmentSpeed, GeocodeSuggestion } from "@/lib/types";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";
const BROOKLYN_CENTER = { longitude: -73.9442, latitude: 40.6782, zoom: 12.5 };

export default function TrafficMap() {
  const segments = useTrafficStore((s) => s.segments);
  const riskMap = useTrafficStore((s) => s.riskMap);
  const incident = useTrafficStore((s) => s.incident);
  const agentOutput = useTrafficStore((s) => s.agentOutput);
  const predictedHotspots = useTrafficStore((s) => s.predictedHotspots);
  const setPredictedHotspots = useTrafficStore((s) => s.setPredictedHotspots);
  const dashboardMode = useTrafficStore((s) => s.dashboardMode);
  const routeOrigin = useTrafficStore((s) => s.routeOrigin);
  const routeDestination = useTrafficStore((s) => s.routeDestination);
  const setRouteOrigin = useTrafficStore((s) => s.setRouteOrigin);
  const setRouteDestination = useTrafficStore((s) => s.setRouteDestination);
  const candidateRoutes = useTrafficStore((s) => s.candidateRoutes);
  const setCandidateRoutes = useTrafficStore((s) => s.setCandidateRoutes);
  const selectedRouteIndex = useTrafficStore((s) => s.selectedRouteIndex);
  const setSelectedRouteIndex = useTrafficStore((s) => s.setSelectedRouteIndex);
  const vehicleType = useTrafficStore((s) => s.vehicleType);
  const routeLoading = useTrafficStore((s) => s.routeLoading);
  const setRouteLoading = useTrafficStore((s) => s.setRouteLoading);
  const setRouteWeatherCondition = useTrafficStore((s) => s.setRouteWeatherCondition);
  const pushToast = useTrafficStore((s) => s.pushToast);

  // Search state
  const [originQuery, setOriginQuery] = useState("");
  const [destQuery, setDestQuery] = useState("");
  const [originSuggestions, setOriginSuggestions] = useState<GeocodeSuggestion[]>([]);
  const [destSuggestions, setDestSuggestions] = useState<GeocodeSuggestion[]>([]);
  const [showOriginSuggestions, setShowOriginSuggestions] = useState(false);
  const [showDestSuggestions, setShowDestSuggestions] = useState(false);
  const originDebounce = useRef<ReturnType<typeof setTimeout>>(undefined);
  const destDebounce = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Predicted hotspots are precomputed on the server: fetch once, retry until it succeeds
  useEffect(() => {
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout>;
    const fetchHotspots = async () => {
      try {
        const data = await api.getPredictedHotspots();
        if (!cancelled && data?.clusters) setPredictedHotspots(data.clusters);
      } catch {
        if (!cancelled) retry = setTimeout(fetchHotspots, 15_000);
      }
    };
    fetchHotspots();
    return () => { cancelled = true; clearTimeout(retry); };
  }, [setPredictedHotspots]);

  // Auto-compute routes when both points are set, or when incident/traffic changes
  const incidentId = incident?.street_name ?? null;
  const mapRef = useRef<MapRef>(null);

  // Bring a new incident into view (overview mode), then fit its diversion once computed
  const incidentKey = incident?.incident_id ?? null;
  useEffect(() => {
    if (!incident || dashboardMode !== "overview") return;
    mapRef.current?.flyTo({ center: [incident.lon, incident.lat], zoom: 14, duration: 1200 });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when a different incident starts
  }, [incidentKey, dashboardMode]);

  const diversionCoords = agentOutput?.diversion?.route_coords;
  useEffect(() => {
    if (!diversionCoords?.length || !incident || dashboardMode !== "overview") return;
    let minLon = incident.lon, maxLon = incident.lon, minLat = incident.lat, maxLat = incident.lat;
    for (const [lon, lat] of diversionCoords) {
      minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
      minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
    }
    mapRef.current?.fitBounds([[minLon, minLat], [maxLon, maxLat]], { padding: 80, duration: 1200, maxZoom: 15 });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refit only when the route changes
  }, [diversionCoords]);
  useEffect(() => {
    if (!routeOrigin || !routeDestination || dashboardMode !== "route") return;
    const computeRoutes = async () => {
      setRouteLoading(true);
      try {
        const data = await api.findRoutes(
          { lat: routeOrigin.lat, lon: routeOrigin.lon },
          { lat: routeDestination.lat, lon: routeDestination.lon },
          3,
          vehicleType,
        );
        if (data?.routes) {
          setCandidateRoutes(data.routes);
          setRouteWeatherCondition(data.weather_condition || "clear");
          if (!data.routes.length) pushToast("No road route found between those points.", "info");
        }
      } catch (e) {
        pushToast(`Route planning failed: ${errorMessage(e)}`);
      }
      setRouteLoading(false);
    };
    computeRoutes();
    // Refresh routes every 30s for real-time congestion updates
    const interval = setInterval(computeRoutes, 30_000);
    return () => clearInterval(interval);
  }, [routeOrigin, routeDestination, vehicleType, dashboardMode, incidentId, setCandidateRoutes, setRouteLoading, setRouteWeatherCondition, pushToast]);

  // Geocode search handlers
  const handleOriginSearch = useCallback((q: string) => {
    setOriginQuery(q);
    clearTimeout(originDebounce.current);
    if (q.length < 2) { setOriginSuggestions([]); return; }
    originDebounce.current = setTimeout(async () => {
      try {
        const data = await api.geocodeSearch(q);
        setOriginSuggestions(data?.suggestions || []);
        setShowOriginSuggestions(true);
      } catch { setOriginSuggestions([]); }
    }, 300);
  }, []);

  const handleDestSearch = useCallback((q: string) => {
    setDestQuery(q);
    clearTimeout(destDebounce.current);
    if (q.length < 2) { setDestSuggestions([]); return; }
    destDebounce.current = setTimeout(async () => {
      try {
        const data = await api.geocodeSearch(q);
        setDestSuggestions(data?.suggestions || []);
        setShowDestSuggestions(true);
      } catch { setDestSuggestions([]); }
    }, 300);
  }, []);

  const selectOrigin = useCallback((s: GeocodeSuggestion) => {
    setRouteOrigin({ lat: s.lat, lon: s.lon, name: s.place_name });
    setOriginQuery(s.place_name);
    setShowOriginSuggestions(false);
  }, [setRouteOrigin]);

  const selectDest = useCallback((s: GeocodeSuggestion) => {
    setRouteDestination({ lat: s.lat, lon: s.lon, name: s.place_name });
    setDestQuery(s.place_name);
    setShowDestSuggestions(false);
  }, [setRouteDestination]);

  // Map click in route mode
  const handleMapClick = useCallback((e: any) => {
    if (dashboardMode !== "route") return;
    const { lng, lat } = e.lngLat;
    if (!routeOrigin) {
      setRouteOrigin({ lat, lon: lng, name: `${lat.toFixed(4)}, ${lng.toFixed(4)}` });
      setOriginQuery(`${lat.toFixed(4)}, ${lng.toFixed(4)}`);
    } else if (!routeDestination) {
      setRouteDestination({ lat, lon: lng, name: `${lat.toFixed(4)}, ${lng.toFixed(4)}` });
      setDestQuery(`${lat.toFixed(4)}, ${lng.toFixed(4)}`);
    }
  }, [dashboardMode, routeOrigin, routeDestination, setRouteOrigin, setRouteDestination]);

  // Segment Points GeoJSON
  const segmentGeoJSON = useMemo(() => ({
    type: "FeatureCollection" as const,
    features: segments.map((seg: SegmentSpeed) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [seg.lon, seg.lat] },
      properties: {
        color: speedToColor(seg.speed, seg.free_flow_speed),
        speed: Math.round(seg.speed),
        name: seg.street_name,
      },
    })),
  }), [segments]);

  // Road segment lines GeoJSON — group by street, connect into polylines for Google-Maps-style traffic coloring
  const roadLinesGeoJSON = useMemo(() => {
    // Group segments by street name
    const byStreet: Record<string, SegmentSpeed[]> = {};
    for (const seg of segments) {
      const key = seg.street_name;
      if (!byStreet[key]) byStreet[key] = [];
      byStreet[key].push(seg);
    }

    const features: any[] = [];
    for (const [, segs] of Object.entries(byStreet)) {
      if (segs.length === 0) continue;

      // Sort by lat then lon for consistent polyline direction
      const sorted = [...segs].sort((a, b) => a.lat !== b.lat ? a.lat - b.lat : a.lon - b.lon);

      // Build connected polyline coordinates and compute average color
      const coords = sorted.map(s => [s.lon, s.lat]);
      let totalRatio = 0;
      for (const s of sorted) {
        totalRatio += s.free_flow_speed > 0 ? s.speed / s.free_flow_speed : 0.5;
      }
      const avgRatio = totalRatio / sorted.length;

      // If segments are far apart (>500m), split into sub-groups to avoid cross-map lines
      const groups: SegmentSpeed[][] = [[]];
      for (let i = 0; i < sorted.length; i++) {
        const cur = sorted[i];
        const lastGroup = groups[groups.length - 1];
        if (lastGroup.length === 0) {
          lastGroup.push(cur);
        } else {
          const prev = lastGroup[lastGroup.length - 1];
          const dist = Math.sqrt((cur.lat - prev.lat) ** 2 + (cur.lon - prev.lon) ** 2);
          if (dist < 0.005) { // ~500m threshold
            lastGroup.push(cur);
          } else {
            groups.push([cur]);
          }
        }
      }

      for (const group of groups) {
        if (group.length < 1) continue;

        // Extend each point with bearing to create road-like segments
        const DEG_TO_RAD = Math.PI / 180;
        const EXT = 0.0008; // extend ~90m in bearing direction at each end

        let lineCoords: number[][] = [];
        if (group.length === 1) {
          // Single point — use bearing to create segment
          const s = group[0];
          const b = (s.bearing ?? 0) * DEG_TO_RAD;
          const dx = Math.sin(b) * EXT;
          const dy = Math.cos(b) * EXT;
          lineCoords = [[s.lon - dx, s.lat - dy], [s.lon + dx, s.lat + dy]];
        } else {
          lineCoords = group.map(s => [s.lon, s.lat]);
        }

        // Color per-segment group
        let grpRatio = 0;
        for (const s of group) {
          grpRatio += s.free_flow_speed > 0 ? s.speed / s.free_flow_speed : 0.5;
        }
        grpRatio /= group.length;

        features.push({
          type: "Feature" as const,
          geometry: { type: "LineString" as const, coordinates: lineCoords },
          properties: {
            color: speedToColor(grpRatio * 30, 30), // pass ratio through speedToColor
            speed: Math.round(grpRatio * 100),
          },
        });
      }
    }

    return { type: "FeatureCollection" as const, features };
  }, [segments]);

  // Risk heatmap GeoJSON
  const riskGeoJSON = useMemo(() => ({
    type: "FeatureCollection" as const,
    features: riskMap.map((r) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [r.lon, r.lat] },
      properties: { risk: r.score },
    })),
  }), [riskMap]);

  // Diversion route line GeoJSON
  const diversionGeoJSON = useMemo(() => {
    if (!agentOutput?.diversion?.route_coords?.length) return null;
    return {
      type: "Feature" as const,
      geometry: { type: "LineString" as const, coordinates: agentOutput.diversion.route_coords },
      properties: {},
    };
  }, [agentOutput]);

  // Predicted hotspot circles GeoJSON
  const hotspotGeoJSON = useMemo(() => ({
    type: "FeatureCollection" as const,
    features: predictedHotspots.map((h) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [h.center_lon, h.center_lat] },
      properties: {
        risk_score: h.risk_score,
        accident_count: h.accident_count,
        severity_score: h.severity_score,
        radius_m: h.radius_m,
      },
    })),
  }), [predictedHotspots]);

  // Route GeoJSONs
  const routeGeoJSONs = useMemo(() => {
    return candidateRoutes.map((route) => ({
      type: "Feature" as const,
      geometry: { type: "LineString" as const, coordinates: route.coords },
      properties: { color: route.color, index: route.route_index },
    }));
  }, [candidateRoutes]);

  const isRouteMode = dashboardMode === "route";

  return (
    <div className="w-full h-full relative">
      <Map
        ref={mapRef}
        initialViewState={BROOKLYN_CENTER}
        style={{ width: "100%", height: "100%" }}
        mapStyle="mapbox://styles/mapbox/light-v11"
        mapboxAccessToken={MAPBOX_TOKEN}
        attributionControl={false}
        cursor={isRouteMode ? "crosshair" : "grab"}
        onClick={handleMapClick}
      >
        <NavigationControl position="top-left" />

        {/* Risk Heatmap Layer (overview mode) */}
        {!isRouteMode && (
          <Source id="risk-heatmap" type="geojson" data={riskGeoJSON}>
            <Layer
              id="risk-heat"
              type="heatmap"
              paint={{
                "heatmap-weight": ["get", "risk"],
                "heatmap-intensity": 1.5,
                "heatmap-radius": 30,
                "heatmap-opacity": 0.4,
                "heatmap-color": [
                  "interpolate", ["linear"], ["heatmap-density"],
                  0, "rgba(0,0,0,0)",
                  0.2, "rgba(16,185,129,0.4)",
                  0.4, "rgba(245,158,11,0.5)",
                  0.6, "rgba(249,115,22,0.6)",
                  0.8, "rgba(239,68,68,0.7)",
                  1, "rgba(220,38,38,0.9)",
                ],
              }}
            />
          </Source>
        )}

        {/* Road segment lines colored by speed (overview mode) */}
        {!isRouteMode && (
          <Source id="road-lines" type="geojson" data={roadLinesGeoJSON}>
            <Layer
              id="road-line-layer"
              type="line"
              paint={{
                "line-color": ["get", "color"],
                "line-width": 6,
                "line-opacity": 0.9,
              }}
              layout={{ "line-cap": "round", "line-join": "round" }}
            />
          </Source>
        )}

        {/* Speed points (overview mode) */}
        {!isRouteMode && (
          <Source id="segments" type="geojson" data={segmentGeoJSON}>
            <Layer
              id="segment-circles"
              type="circle"
              paint={{
                "circle-radius": 4,
                "circle-color": ["get", "color"],
                "circle-stroke-width": 1,
                "circle-stroke-color": "#ffffff",
                "circle-opacity": 0.9,
              }}
            />
          </Source>
        )}

        {/* Diversion Route Line (overview mode) */}
        {!isRouteMode && diversionGeoJSON && (
          <Source id="diversion-route" type="geojson" data={diversionGeoJSON}>
            <Layer
              id="diversion-line"
              type="line"
              paint={{
                "line-color": "#2563eb",
                "line-width": 4,
                "line-dasharray": [2, 2],
                "line-opacity": 0.8,
              }}
            />
          </Source>
        )}

        {/* Predicted Hotspot Zones (both modes) */}
        {predictedHotspots.length > 0 && (
          <Source id="predicted-hotspots" type="geojson" data={hotspotGeoJSON}>
            <Layer
              id="hotspot-circles"
              type="circle"
              paint={{
                "circle-radius": [
                  "interpolate", ["linear"], ["get", "risk_score"],
                  5, 12, 20, 22, 50, 35,
                ],
                "circle-color": [
                  "interpolate", ["linear"], ["get", "risk_score"],
                  5, "rgba(251, 146, 60, 0.5)",
                  20, "rgba(239, 68, 68, 0.55)",
                  50, "rgba(185, 28, 28, 0.6)",
                ],
                "circle-stroke-width": 1.5,
                "circle-stroke-color": "rgba(220, 38, 38, 0.7)",
                "circle-opacity": 0.6,
              }}
            />
          </Source>
        )}

        {/* Candidate Routes (route mode) */}
        {isRouteMode && routeGeoJSONs.map((geojson, idx) => (
          <Source key={`route-${idx}`} id={`route-${idx}`} type="geojson" data={geojson}>
            <Layer
              id={`route-line-${idx}`}
              type="line"
              paint={{
                "line-color": geojson.properties.color,
                "line-width": selectedRouteIndex === idx ? 6 : 3,
                "line-opacity": selectedRouteIndex === idx ? 1 : 0.5,
              }}
              layout={{ "line-cap": "round", "line-join": "round" }}
            />
          </Source>
        ))}

        {/* Origin Marker */}
        {isRouteMode && routeOrigin && (
          <Marker latitude={routeOrigin.lat} longitude={routeOrigin.lon} anchor="bottom">
            <div className="flex flex-col items-center">
              <div className="bg-emerald-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded mb-0.5">START</div>
              <MapPin className="w-6 h-6 text-emerald-500 drop-shadow-md" />
            </div>
          </Marker>
        )}

        {/* Destination Marker */}
        {isRouteMode && routeDestination && (
          <Marker latitude={routeDestination.lat} longitude={routeDestination.lon} anchor="bottom">
            <div className="flex flex-col items-center">
              <div className="bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded mb-0.5">END</div>
              <MapPin className="w-6 h-6 text-red-500 drop-shadow-md" />
            </div>
          </Marker>
        )}

        {/* Incident Marker */}
        {incident && (
          <Marker latitude={incident.lat} longitude={incident.lon} anchor="center">
            <div className="relative">
              <div
                className="animate-incident-pulse absolute -inset-3 rounded-full opacity-30"
                style={{ backgroundColor: severityColor(incident.severity) }}
              />
              <div
                className="w-6 h-6 rounded-full border-2 border-white shadow-lg flex items-center justify-center"
                style={{ backgroundColor: severityColor(incident.severity) }}
              >
                <span className="text-white text-xs font-bold">!</span>
              </div>
            </div>
          </Marker>
        )}
      </Map>

      {/* Search Boxes (route mode) */}
      {isRouteMode && (
        <div className="absolute top-3 right-3 w-[calc(100%-4.5rem)] sm:w-72 space-y-2 z-10">
          {/* Origin Search */}
          <div className="relative">
            <div className="flex items-center bg-white rounded-lg shadow-lg border border-slate-200 px-3 py-2">
              <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 mr-2 shrink-0" />
              <input
                type="text"
                value={originQuery}
                onChange={(e) => handleOriginSearch(e.target.value)}
                onFocus={() => originSuggestions.length > 0 && setShowOriginSuggestions(true)}
                placeholder="Origin — search or click map"
                className="flex-1 text-xs text-foreground bg-transparent outline-none placeholder:text-muted"
              />
              {routeOrigin && (
                <button onClick={() => { setRouteOrigin(null); setOriginQuery(""); setCandidateRoutes([]); }}>
                  <X className="w-3.5 h-3.5 text-muted hover:text-foreground" />
                </button>
              )}
            </div>
            {showOriginSuggestions && originSuggestions.length > 0 && (
              <div className="absolute top-full mt-1 w-full bg-white rounded-lg shadow-lg border border-slate-200 max-h-40 overflow-y-auto z-20">
                {originSuggestions.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => selectOrigin(s)}
                    className="w-full text-left px-3 py-2 text-xs text-foreground hover:bg-slate-50 border-b border-slate-100 last:border-0"
                  >
                    {s.place_name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Destination Search */}
          <div className="relative">
            <div className="flex items-center bg-white rounded-lg shadow-lg border border-slate-200 px-3 py-2">
              <div className="w-2.5 h-2.5 rounded-full bg-red-500 mr-2 shrink-0" />
              <input
                type="text"
                value={destQuery}
                onChange={(e) => handleDestSearch(e.target.value)}
                onFocus={() => destSuggestions.length > 0 && setShowDestSuggestions(true)}
                placeholder="Destination — search or click map"
                className="flex-1 text-xs text-foreground bg-transparent outline-none placeholder:text-muted"
              />
              {routeDestination && (
                <button onClick={() => { setRouteDestination(null); setDestQuery(""); setCandidateRoutes([]); }}>
                  <X className="w-3.5 h-3.5 text-muted hover:text-foreground" />
                </button>
              )}
            </div>
            {showDestSuggestions && destSuggestions.length > 0 && (
              <div className="absolute top-full mt-1 w-full bg-white rounded-lg shadow-lg border border-slate-200 max-h-40 overflow-y-auto z-20">
                {destSuggestions.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => selectDest(s)}
                    className="w-full text-left px-3 py-2 text-xs text-foreground hover:bg-slate-50 border-b border-slate-100 last:border-0"
                  >
                    {s.place_name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Loading indicator */}
          {routeLoading && (
            <div className="flex items-center justify-center gap-2 bg-white/90 rounded-lg shadow px-3 py-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
              <span className="text-xs text-muted">Computing routes...</span>
            </div>
          )}

          {/* Route mode instruction */}
          {!routeOrigin && !routeDestination && !routeLoading && (
            <div className="bg-white/90 rounded-lg shadow px-3 py-2 text-center">
              <span className="text-xs text-muted">Search or click the map to set points</span>
            </div>
          )}
        </div>
      )}

      {/* Map Legend */}
      <div className="hidden sm:block absolute bottom-4 left-4 glass-card rounded-lg p-3 text-xs">
        <div className="font-semibold mb-1.5 text-slate-700">
          {isRouteMode ? "Route Legend" : "Traffic Conditions"}
        </div>
        {isRouteMode ? (
          <>
            <div className="flex items-center gap-1.5 mb-1">
              <div className="w-6 h-0.5 bg-emerald-500 rounded" />
              <span className="text-slate-600">Low risk</span>
            </div>
            <div className="flex items-center gap-1.5 mb-1">
              <div className="w-6 h-0.5 bg-amber-500 rounded" />
              <span className="text-slate-600">Moderate risk</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-6 h-0.5 bg-red-500 rounded" />
              <span className="text-slate-600">High risk</span>
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center gap-1.5 mb-1">
              <div className="w-5 h-1 rounded bg-emerald-500" />
              <span className="text-slate-600">Clear — Good to go</span>
            </div>
            <div className="flex items-center gap-1.5 mb-1">
              <div className="w-5 h-1 rounded bg-amber-500" />
              <span className="text-slate-600">Slow — Possible congestion</span>
            </div>
            <div className="flex items-center gap-1.5 mb-1">
              <div className="w-5 h-1 rounded bg-red-500" />
              <span className="text-slate-600">Congested — Avoid</span>
            </div>
          </>
        )}
        {predictedHotspots.length > 0 && (
          <>
            <div className="border-t border-slate-200 my-1.5" />
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full bg-red-400/60 border border-red-500/70" />
              <span className="text-slate-600">Predicted Hotspot</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
