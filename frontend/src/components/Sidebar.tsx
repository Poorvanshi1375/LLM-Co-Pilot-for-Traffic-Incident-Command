/* ── Sidebar — incident timer, severity badge, density, metrics ── */
"use client";

import { useEffect, useState } from "react";
import {
  Activity, AlertTriangle, Clock, Radio, Gauge,
  CheckCircle, Circle, CloudRain, Cloud, Sun,
  Snowflake, Wind, CloudFog, Share2, KeyRound, Radar,
} from "lucide-react";
import Image from "next/image";
import { useTrafficStore } from "@/lib/store";
import { severityBg, formatHour, cn } from "@/lib/utils";
import { api, errorMessage, getAdminToken, setAdminToken } from "@/lib/api";

export default function Sidebar() {
  const connected = useTrafficStore((s) => s.connected);
  const incident = useTrafficStore((s) => s.incident);
  const agentOutput = useTrafficStore((s) => s.agentOutput);
  const hour = useTrafficStore((s) => s.hour);
  const segments = useTrafficStore((s) => s.segments);
  const processing = useTrafficStore((s) => s.processing);
  const incidentStartTime = useTrafficStore((s) => s.incidentStartTime);
  const density = useTrafficStore((s) => s.density);
  const weather = useTrafficStore((s) => s.weather);
  const setWeather = useTrafficStore((s) => s.setWeather);
  const autoPost = useTrafficStore((s) => s.autoPost);
  const setAutoPost = useTrafficStore((s) => s.setAutoPost);
  const settings = useTrafficStore((s) => s.settings);
  const setSettings = useTrafficStore((s) => s.setSettings);
  const pushToast = useTrafficStore((s) => s.pushToast);

  const [elapsed, setElapsed] = useState("00:00");
  const [tokenInput, setTokenInput] = useState("");
  const [hasToken, setHasToken] = useState(false);

  // Fetch server settings once connected (the backend may still be waking up)
  useEffect(() => {
    if (!connected) return;
    api.getSettings().then(setSettings).catch(() => {});
  }, [connected, setSettings]);

  // localStorage is only readable after hydration, so this must run in an effect
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHasToken(Boolean(getAdminToken()));
  }, []);

  const toggleAutoPost = async () => {
    const next = !autoPost;
    try {
      await api.setAutoPost(next);
      setAutoPost(next);
    } catch (e) {
      pushToast(errorMessage(e));
    }
  };

  const toggleAutoDetect = async () => {
    if (!settings) return;
    const next = !settings.auto_detect;
    try {
      await api.setAutoDetect(next);
      setSettings({ ...settings, auto_detect: next });
    } catch (e) {
      pushToast(errorMessage(e));
    }
  };

  // Operator-only toggles need a server-side ADMIN_TOKEN and the token saved in this browser
  const canOperate = Boolean(settings?.admin_configured && hasToken);
  const operatorHint = canOperate
    ? ""
    : settings && !settings.admin_configured
      ? " (locked: no ADMIN_TOKEN on server)"
      : " (enter the operator token below to change)";

  const saveToken = () => {
    setAdminToken(tokenInput.trim());
    setHasToken(Boolean(tokenInput.trim()));
    setTokenInput("");
  };

  // Poll weather every 5 minutes
  useEffect(() => {
    const fetchWeather = () => {
      api.getWeather().then(setWeather).catch(() => {});
    };
    fetchWeather();
    const interval = setInterval(fetchWeather, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [setWeather]);

  useEffect(() => {
    if (!incidentStartTime) {
      setElapsed("00:00");
      return;
    }
    const interval = setInterval(() => {
      const diff = Math.floor((Date.now() - incidentStartTime) / 1000);
      const min = Math.floor(diff / 60).toString().padStart(2, "0");
      const sec = (diff % 60).toString().padStart(2, "0");
      setElapsed(`${min}:${sec}`);
    }, 1000);
    return () => clearInterval(interval);
  }, [incidentStartTime]);

  const avgSpeed = segments.length
    ? Math.round(
        segments.reduce((a, s) => a + s.speed, 0) / segments.length
      )
    : 0;

  return (
    <div className="w-64 border-r border-border bg-white flex flex-col h-full overflow-y-auto">
      {/* Logo */}
      <div className="px-4 py-5 border-b border-border">
        <div className="flex items-center gap-2">
          <Image src="/logo.svg" alt="TrafficMind" width={32} height={32} className="rounded-lg" />
          <div>
            <h1 className="text-base font-bold text-foreground">TrafficMind</h1>
            <p className="text-[10px] text-muted">AI Co-Pilot</p>
          </div>
        </div>
      </div>

      {/* Connection Status */}
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2 text-xs">
          <div
            className={cn(
              "w-2 h-2 rounded-full",
              connected ? "bg-success" : "bg-danger"
            )}
          />
          <span className="text-muted">
            {connected ? "Connected — Live Feed" : "Disconnected"}
          </span>
        </div>
      </div>

      {/* Simulated Time */}
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2 text-xs text-muted mb-1">
          <Clock className="w-3.5 h-3.5" />
          <span>Brooklyn Time</span>
        </div>
        <p className="text-lg font-semibold text-foreground pl-5.5">
          {formatHour(hour)}
        </p>
      </div>

      {/* Weather */}
      {weather && (
        <div className="px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2 text-xs text-muted mb-1">
            {weather.condition === "snow" || weather.condition === "ice" ? (
              <Snowflake className="w-3.5 h-3.5" />
            ) : weather.condition === "rain" || weather.condition === "heavy_rain" ? (
              <CloudRain className="w-3.5 h-3.5" />
            ) : weather.condition === "fog" ? (
              <CloudFog className="w-3.5 h-3.5" />
            ) : weather.condition === "wind" ? (
              <Wind className="w-3.5 h-3.5" />
            ) : weather.condition === "cloudy" || weather.condition === "partly_cloudy" ? (
              <Cloud className="w-3.5 h-3.5" />
            ) : (
              <Sun className="w-3.5 h-3.5" />
            )}
            <span>Weather</span>
          </div>
          <div className="pl-5.5 space-y-0.5">
            <p className="text-sm font-semibold text-foreground">
              {Math.round(weather.temp_f)}°F — {weather.description}
            </p>
            <div className="flex gap-3 text-[10px] text-muted">
              <span>💧 {weather.precip_pct}%</span>
              <span>💨 {weather.wind_mph} mph</span>
            </div>
            {weather.is_severe && (
              <p className="text-[10px] font-semibold text-danger mt-0.5">
                ⚠ Severe weather — routing affected
              </p>
            )}
          </div>
        </div>
      )}

      {/* Incident Status */}
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2 text-xs text-muted mb-2">
          <AlertTriangle className="w-3.5 h-3.5" />
          <span>Incident Status</span>
        </div>
        {incident ? (
          <div className="space-y-2 pl-5.5">
            <span
              className={cn(
                "inline-block text-xs font-semibold px-2 py-0.5 rounded-full",
                severityBg(incident.severity)
              )}
            >
              {incident.severity}
            </span>
            <p className="text-xs text-foreground font-medium">
              {incident.street_name}
            </p>
            <div className="flex items-center gap-1.5 text-xs text-muted">
              <Clock className="w-3 h-3" />
              <span>Elapsed: {elapsed}</span>
            </div>
            {incident.duration_estimate_min > 0 && (
              <p className="text-[10px] text-muted">
                Est. duration: {incident.duration_estimate_min} min
              </p>
            )}
            {processing && (
              <div className="flex items-center gap-1.5 text-xs text-primary">
                <Activity className="w-3 h-3 animate-spin" />
                <span>Agents processing…</span>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-1.5 pl-5.5 text-xs text-success">
            <CheckCircle className="w-3.5 h-3.5" />
            <span>No active incidents</span>
          </div>
        )}
      </div>

      {/* Network Stats */}
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2 text-xs text-muted mb-2">
          <Activity className="w-3.5 h-3.5" />
          <span>Network Stats</span>
        </div>
        <div className="space-y-1.5 pl-5.5">
          <div className="flex justify-between text-xs">
            <span className="text-muted">Active Segments</span>
            <span className="font-medium text-foreground">{segments.length}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-muted">Avg Speed</span>
            <span className="font-medium text-foreground">{avgSpeed} mph</span>
          </div>
        </div>
      </div>

      {/* Density */}
      {density && (
        <div className="px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2 text-xs text-muted mb-2">
            <Gauge className="w-3.5 h-3.5" />
            <span>Vehicle Density</span>
          </div>
          <div className="space-y-1.5 pl-5.5">
            <p className="text-sm font-semibold text-foreground">
              {density.congestion_level}
            </p>
            <p className="text-xs text-muted">
              ~{density.estimated_vehicles} vehicles
            </p>
          </div>
        </div>
      )}

      {/* Agent Confidence */}
      {agentOutput?.confidence_scores && (
        <div className="px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2 text-xs text-muted mb-2">
            <Radio className="w-3.5 h-3.5" />
            <span>Agent Confidence</span>
          </div>
          <div className="space-y-1.5 pl-5.5">
            {Object.entries(agentOutput.confidence_scores).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs">
                <span className="text-muted capitalize">{k}</span>
                <span
                  className={cn(
                    "font-medium",
                    Number(v) >= 0.8
                      ? "text-success"
                      : Number(v) >= 0.6
                      ? "text-warning"
                      : "text-danger"
                  )}
                >
                  {(Number(v) * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Cascade Risk */}
      {agentOutput && (
        <div className="px-4 py-3">
          <div className="flex items-center gap-2 text-xs text-muted mb-1">
            <Circle className="w-3.5 h-3.5" />
            <span>Cascade Risk</span>
          </div>
          <div className="pl-5.5">
            <div className="w-full bg-slate-100 rounded-full h-2 mt-1">
              <div
                className={cn(
                  "h-2 rounded-full transition-all duration-500",
                  agentOutput.cascade_risk > 0.7
                    ? "bg-danger"
                    : agentOutput.cascade_risk > 0.4
                    ? "bg-warning"
                    : "bg-success"
                )}
                style={{
                  width: `${Math.min(agentOutput.cascade_risk * 100, 100)}%`,
                }}
              />
            </div>
            <p className="text-[10px] text-muted mt-0.5">
              {(agentOutput.cascade_risk * 100).toFixed(0)}% probability
            </p>
          </div>
        </div>
      )}

      {/* Auto-Post Tweets */}
      <div className="px-4 py-3 border-t border-slate-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-muted">
            <Share2 className="w-3.5 h-3.5" />
            <span>Auto-Post Tweets</span>
          </div>
          <Toggle
            on={autoPost}
            disabled={!settings?.twitter_enabled || (!canOperate && !autoPost)}
            onClick={toggleAutoPost}
            label="Auto-post tweets"
          />
        </div>
        <p className="text-[10px] text-muted mt-1 pl-5.5">
          {!settings?.twitter_enabled
            ? "Posting is disabled on this server"
            : autoPost ? "Tweets post when incidents are processed" : `Tweet auto-posting off${operatorHint}`}
        </p>
      </div>

      {/* Auto-detect incidents */}
      <div className="px-4 py-3 border-t border-slate-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-muted">
            <Radar className="w-3.5 h-3.5" />
            <span>Auto-Detect Incidents</span>
          </div>
          <Toggle
            on={Boolean(settings?.auto_detect)}
            disabled={!settings || !canOperate}
            onClick={toggleAutoDetect}
            label="Auto-detect incidents"
          />
        </div>
        <p className="text-[10px] text-muted mt-1 pl-5.5">
          {settings?.auto_detect
            ? "Agents run when the feed shows a sustained slowdown"
            : `Off — use Simulate Incident${operatorHint}`}
        </p>
      </div>

      {/* Operator token */}
      <div className="px-4 py-3 border-t border-slate-200">
        <div className="flex items-center gap-2 text-xs text-muted mb-1.5">
          <KeyRound className="w-3.5 h-3.5" />
          <span>Operator Access</span>
        </div>
        {settings && !settings.admin_configured ? (
          <p className="pl-5.5 text-[10px] text-muted">
            Not configured on this server (no ADMIN_TOKEN), so operator settings are locked.
          </p>
        ) : hasToken ? (
          <div className="flex items-center justify-between pl-5.5 text-[10px]">
            <span className="text-success">Token saved in this browser</span>
            <button
              onClick={() => { setAdminToken(""); setHasToken(false); }}
              className="text-muted hover:text-foreground underline"
            >
              Forget
            </button>
          </div>
        ) : (
          <form
            className="flex gap-1.5 pl-5.5"
            onSubmit={(e) => { e.preventDefault(); saveToken(); }}
          >
            <input
              type="password"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="Admin token"
              aria-label="Admin token"
              className="flex-1 min-w-0 text-[11px] border border-border rounded px-2 py-1 outline-none focus:border-primary"
            />
            <button
              type="submit"
              disabled={!tokenInput.trim()}
              className="text-[11px] px-2 py-1 rounded bg-slate-100 text-foreground hover:bg-slate-200 disabled:opacity-50"
            >
              Save
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

function Toggle({ on, disabled, onClick, label }: {
  on: boolean;
  disabled?: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "relative w-8 h-[18px] rounded-full transition-colors duration-200 disabled:opacity-40 disabled:cursor-not-allowed",
        on ? "bg-blue-500" : "bg-slate-300"
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 left-0.5 w-3.5 h-3.5 rounded-full bg-white transition-transform duration-200",
          on && "translate-x-3.5"
        )}
      />
    </button>
  );
}
