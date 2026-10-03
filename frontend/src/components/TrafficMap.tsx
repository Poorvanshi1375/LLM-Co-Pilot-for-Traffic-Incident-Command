/* ── Traffic Map — Mapbox GL + speed-colored markers + route intelligence ── */
"use client";

import { useMemo, useCallback, useEffect, useState, useRef } from "react";
import Map, { Source, Layer, Marker, NavigationControl, type MapRef, type MapMouseEvent } from "react-map-gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";
import { useTrafficStore } from "@/lib/store";
import { speedToColor, severityColor } from "@/lib/utils";
import { api, errorMessage } from "@/lib/api";
import { MapPin, X, Loader2 } from "lucide-react";
import type { SegmentSpeed, GeocodeSuggestion } from "@/lib/types";
import MapSearch from "@/components/MapSearch";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";
const BROOKLYN_CENTER = { longitude: -73.9442, latitude: 40.6782, zoom: 12.5 };
const NO_DATA_COLOR = "#9ca3af";

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
  const handleMapClick = useCallback((e: MapMouseEvent) => {
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

  // Live colour per monitored segment: the static road layer (public/road-network.geojson)
  // tags each road with the segment ("s") on the same street that colours it
  const segmentById = useMemo(() => {
    const m: Record<string, SegmentSpeed> = {};
    for (const seg of segments) m[seg.segment_id] = seg;
    return m;
  }, [segments]);

  const trafficColor = useMemo(() => {
    if (!segments.length) return NO_DATA_COLOR;
    const expr: unknown[] = ["match", ["get", "s"]];
    for (const seg of segments) expr.push(seg.segment_id, speedToColor(seg.speed, seg.free_flow_speed));
    expr.push(NO_DATA_COLOR);
    return expr as unknown as string;
  }, [segments]);

  // Hover card for coloured roads
  const [hover, setHover] = useState<{ x: number; y: number; seg: SegmentSpeed } | null>(null);
  const handleMouseMove = useCallback((e: MapMouseEvent) => {
    const id = e.features?.[0]?.properties?.s;
    const seg = id ? segmentById[id] : undefined;
    setHover(seg ? { x: e.point.x, y: e.point.y, seg } : null);
  }, [segmentById]);

  // Optional overlays (legend toggles)
  const [showHotspots, setShowHotspots] = useState(false);
  const [showRiskHeat, setShowRiskHeat] = useState(false);

  // Search focus: a monitored street (spotlighted) or a place (pin + nearest reading)
  const [focus, setFocus] = useState<
    | { kind: "street"; name: string }
    | { kind: "place"; name: string; lat: number; lon: number }
    | null
  >(null);

  const focusStreet = useCallback((name: string) => {
    const segs = segments.filter((s) => s.street_name === name);
    if (!segs.length) return;
    setFocus({ kind: "street", name });
    const lons = segs.map((s) => s.lon), lats = segs.map((s) => s.lat);
    mapRef.current?.fitBounds(
      [[Math.min(...lons) - 0.004, Math.min(...lats) - 0.004], [Math.max(...lons) + 0.004, Math.max(...lats) + 0.004]],
      { padding: 60, duration: 1000, maxZoom: 15 },
    );
  }, [segments]);

  const focusPlace = useCallback((p: GeocodeSuggestion) => {
    setFocus({ kind: "place", name: p.place_name, lat: p.lat, lon: p.lon });
    mapRef.current?.flyTo({ center: [p.lon, p.lat], zoom: 15, duration: 1000 });
  }, []);

  // Live readings for the info card
  const focusInfo = useMemo(() => {
    if (!focus) return null;
    if (focus.kind === "street") {
      const segs = segments.filter((s) => s.street_name === focus.name);
      if (!segs.length) return null;
      const ratio = segs.reduce((a, s) => a + s.speed / Math.max(s.free_flow_speed, 1), 0) / segs.length;
      const speed = segs.reduce((a, s) => a + s.speed, 0) / segs.length;
      return { title: focus.name, subtitle: `${segs.length} monitored stretch${segs.length > 1 ? "es" : ""} (average)`, speed, ratio };
    }
    const km = (s: SegmentSpeed) => Math.hypot((s.lat - focus.lat) * 111, (s.lon - focus.lon) * 84);
    const nearest = [...segments].sort((a, b) => km(a) - km(b))[0];
    if (!nearest || km(nearest) > 1.5) {
      return { title: focus.name, subtitle: "No live sensor within 1.5 km", speed: null, ratio: null };
    }
    return {
      title: focus.name,
      subtitle: `Nearest live reading: ${nearest.street_name}, ${Math.round(km(nearest) * 1000)} m away`,
      speed: nearest.speed,
      ratio: nearest.speed / Math.max(nearest.free_flow_speed, 1),
    };
  }, [focus, segments]);

  const focusIds = useMemo(
    () => (focus?.kind === "street" ? segments.filter((s) => s.street_name === focus.name).map((s) => s.segment_id) : []),
    [focus, segments],
  );

  // Draw our road lines under the base map's labels so street names stay readable
  const [labelLayerId, setLabelLayerId] = useState<string | undefined>(undefined);
  const handleLoad = useCallback(() => {
    const layers = mapRef.current?.getStyle()?.layers ?? [];
    setLabelLayerId(layers.find((l) => l.type === "symbol")?.id);
  }, []);

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
        cursor={isRouteMode ? "crosshair" : hover ? "pointer" : "grab"}
        onClick={handleMapClick}
        onLoad={handleLoad}
        interactiveLayerIds={isRouteMode ? [] : ["roads-traffic"]}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHover(null)}
      >
        <NavigationControl position="top-left" />

        {/* Every road, grey; monitored roads coloured by live speed (overview mode) */}
        {!isRouteMode && (
          <Source id="road-network" type="geojson" data="/road-network.geojson">
            {/* Soft white edge under each traffic line keeps it crisp against the base map */}
            <Layer
              id="roads-traffic-casing"
              type="line"
              beforeId={labelLayerId}
              paint={{
                "line-color": "#ffffff",
                "line-width": ["interpolate", ["linear"], ["zoom"], 10, 2.5, 13, 4.5, 16, 9],
                "line-opacity": focusIds.length ? ["match", ["get", "s"], focusIds, 0.9, 0.2] : 0.85,
              }}
              layout={{ "line-cap": "round", "line-join": "round" }}
            />
            <Layer
              id="roads-traffic"
              type="line"
              beforeId={labelLayerId}
              paint={{
                "line-color": trafficColor,
                "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.2, 13, 2.6, 16, 6],
                "line-opacity": focusIds.length ? ["match", ["get", "s"], focusIds, 1, 0.2] : 0.9,
              }}
              layout={{ "line-cap": "round", "line-join": "round" }}
            />
          </Source>
        )}

        {/* Risk heatmap — optional overlay */}
        {!isRouteMode && showRiskHeat && (
          <Source id="risk-heatmap" type="geojson" data={riskGeoJSON}>
            <Layer
              id="risk-heat"
              type="heatmap"
              beforeId={labelLayerId}
              paint={{
                "heatmap-weight": ["get", "risk"],
                "heatmap-intensity": 1.2,
                "heatmap-radius": 30,
                "heatmap-opacity": 0.35,
                "heatmap-color": [
                  "interpolate", ["linear"], ["heatmap-density"],
                  0, "rgba(0,0,0,0)",
                  0.3, "rgba(245,158,11,0.4)",
                  0.7, "rgba(239,68,68,0.6)",
                  1, "rgba(220,38,38,0.8)",
                ],
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

        {/* Predicted hotspot zones — subtle rings, toggled from the legend */}
        {showHotspots && predictedHotspots.length > 0 && (
          <Source id="predicted-hotspots" type="geojson" data={hotspotGeoJSON}>
            <Layer
              id="hotspot-circles"
              type="circle"
              paint={{
                "circle-radius": [
                  "interpolate", ["linear"], ["zoom"],
                  11, ["interpolate", ["linear"], ["get", "risk_score"], 5, 6, 50, 14],
                  15, ["interpolate", ["linear"], ["get", "risk_score"], 5, 18, 50, 40],
                ],
                "circle-color": "rgba(220, 38, 38, 0.06)",
                "circle-stroke-width": 1.25,
                "circle-stroke-color": "rgba(220, 38, 38, 0.45)",
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

        {/* Searched place */}
        {!isRouteMode && focus?.kind === "place" && (
          <Marker latitude={focus.lat} longitude={focus.lon} anchor="bottom">
            <MapPin className="w-7 h-7 text-primary fill-primary/20 drop-shadow-md" />
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

      {/* Search + info card (overview mode) */}
      {!isRouteMode && (
        <div className="absolute top-3 right-3 w-[calc(100%-4.5rem)] sm:w-80 space-y-2 z-10">
          <MapSearch
            segments={segments}
            onPickStreet={focusStreet}
            onPickPlace={focusPlace}
            onClear={() => setFocus(null)}
          />
          {focusInfo && (
            <div className="bg-white rounded-lg shadow-md border border-slate-200 px-3 py-2.5 text-xs">
              <div className="flex items-start justify-between gap-2">
                <p className="font-semibold text-foreground leading-snug">{focusInfo.title}</p>
                <button onClick={() => setFocus(null)} aria-label="Close" className="text-muted hover:text-foreground">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <p className="text-[11px] text-muted mt-0.5">{focusInfo.subtitle}</p>
              {focusInfo.ratio !== null && focusInfo.speed !== null && (
                <div className="flex items-center gap-2 mt-2">
                  <span
                    className="inline-block w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: speedToColor(focusInfo.ratio * 100, 100) }}
                  />
                  <span className="font-medium text-foreground">
                    {focusInfo.ratio > 0.7 ? "Moving well" : focusInfo.ratio > 0.4 ? "Slow" : "Congested"}
                  </span>
                  <span className="text-muted">
                    · {Math.round(focusInfo.speed)} mph, {Math.round(focusInfo.ratio * 100)}% of normal
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

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

      {/* Map Legend (compact) */}
      <div className="hidden sm:block absolute bottom-4 left-4 bg-white/90 backdrop-blur rounded-lg shadow-sm border border-slate-200 px-3 py-2 text-[11px]">
        <div className="flex items-center gap-3">
          {(isRouteMode
            ? [["bg-emerald-500", "Low risk"], ["bg-amber-500", "Moderate"], ["bg-red-500", "High risk"]]
            : [["bg-emerald-500", "Moving well"], ["bg-amber-500", "Slow"], ["bg-red-500", "Congested"]]
          ).map(([cls, label]) => (
            <span key={label} className="flex items-center gap-1.5 text-slate-600">
              <span className={`w-4 h-1 rounded-full ${cls}`} />
              {label}
            </span>
          ))}
        </div>
        {!isRouteMode && (
          <p className="text-[10px] text-muted mt-1">Grey roads have no live sensor · hover a road for its speed</p>
        )}
        <div className="flex items-center gap-3 mt-1.5 pt-1.5 border-t border-slate-200">
          <label className="flex items-center gap-1 cursor-pointer select-none text-slate-600">
            <input type="checkbox" checked={showHotspots} onChange={(e) => setShowHotspots(e.target.checked)} className="accent-red-500 w-3 h-3" />
            Hotspots
          </label>
          {!isRouteMode && (
            <label className="flex items-center gap-1 cursor-pointer select-none text-slate-600">
              <input type="checkbox" checked={showRiskHeat} onChange={(e) => setShowRiskHeat(e.target.checked)} className="accent-red-500 w-3 h-3" />
              Risk heatmap
            </label>
          )}
        </div>
      </div>

      {/* Hover card for a coloured road */}
      {hover && (
        <div
          className="pointer-events-none absolute z-20 bg-white/95 border border-slate-200 rounded-md shadow px-2.5 py-1.5 text-[11px]"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
        >
          <p className="font-semibold text-foreground">{hover.seg.street_name}</p>
          <p className="text-slate-600">
            {Math.round(hover.seg.speed)} mph · {Math.round((hover.seg.speed / Math.max(hover.seg.free_flow_speed, 1)) * 100)}% of normal ({Math.round(hover.seg.free_flow_speed)} mph)
          </p>
        </div>
      )}
    </div>
  );
}
