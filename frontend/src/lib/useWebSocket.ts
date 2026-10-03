/* ── WebSocket Hook ── */
"use client";

import { useEffect, useRef, useCallback } from "react";
import { useTrafficStore } from "./store";
import type { IncidentDetection } from "./types";

const WS_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")
  .replace(/^http/, "ws") + "/ws/feed";

// Short cap: a sleeping free-tier backend wakes in about a minute,
// and we want to connect within seconds of it coming up
const RECONNECT_BASE_MS = 2000;
const RECONNECT_MAX_MS = 10000;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const didUnmount = useRef(false);
  const retryCount = useRef(0);

  // Access store actions via getState() so this callback never needs to
  // re-create due to store subscription changes.
  const connect = useCallback(() => {
    const rs = wsRef.current?.readyState;
    if (rs === WebSocket.OPEN || rs === WebSocket.CONNECTING) return;
    if (didUnmount.current) return;

    const store = useTrafficStore.getState;

    /** Apply the server's incident, starting the elapsed timer only for a new one. */
    const syncIncident = (incident: IncidentDetection | null) => {
      const current = store().incident;
      if ((current?.incident_id ?? null) === (incident?.incident_id ?? null)) return;
      store().setIncident(incident);
      store().setIncidentStartTime(incident ? Date.now() : null);
      if (!incident) {
        store().setAgentOutput(null);
        store().setDensity(null);
      }
    };

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      retryCount.current = 0;
      store().setConnected(true);
    };

    ws.onmessage = (event) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- server messages are loosely typed JSON
      let data: any;
      try {
        data = JSON.parse(event.data);
      } catch {
        return; // skip malformed messages
      }
      const s = store();

      switch (data.type) {
        case "state": // full snapshot sent on connect
          syncIncident(data.incident);
          s.setAgentOutput(data.agent_output);
          s.setDensity(data.agent_output?.density ?? null);
          s.setProcessing(Boolean(data.processing));
          if (data.timeline) s.setTimeline(data.timeline);
          break;

        case "tick":
          s.setFeedData(data.segments || [], data.risk_map || [], data.hour ?? 8.5);
          // Ticks carry incident + processing, so the UI self-corrects if an event was missed
          syncIncident(data.incident ?? null);
          if (Boolean(data.processing) !== s.processing) s.setProcessing(Boolean(data.processing));
          break;

        case "incident_detected":
          syncIncident(data.incident);
          s.setProcessing(true);
          break;

        case "agents_complete":
          s.setAgentOutput(data.output);
          s.setProcessing(false);
          if (data.timeline) s.setTimeline(data.timeline);
          if (data.output?.density) s.setDensity(data.output.density);
          break;

        case "agents_failed":
          s.setProcessing(false);
          if (data.timeline) s.setTimeline(data.timeline);
          s.pushToast(`Agent pipeline failed: ${data.error || "unknown error"}`);
          break;

        case "incident_resolved":
          syncIncident(null);
          s.setProcessing(false);
          if (data.timeline) s.setTimeline(data.timeline);
          break;
      }
    };

    ws.onclose = () => {
      store().setConnected(false);
      if (!didUnmount.current) {
        // Exponential backoff capped at RECONNECT_MAX_MS
        const delay = Math.min(
          RECONNECT_BASE_MS * 2 ** retryCount.current,
          RECONNECT_MAX_MS
        );
        retryCount.current += 1;
        reconnectTimer.current = setTimeout(connect, delay);
      }
    };

    ws.onerror = () => {
      // Only close if not already closing/closed to avoid the
      // "WebSocket closed before connection established" browser warning.
      if (
        ws.readyState !== WebSocket.CLOSING &&
        ws.readyState !== WebSocket.CLOSED
      ) {
        ws.close();
      }
    };
  }, []); // stable — reads store via getState(), no subscriptions

  useEffect(() => {
    didUnmount.current = false;
    connect();
    return () => {
      didUnmount.current = true;
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);
}
