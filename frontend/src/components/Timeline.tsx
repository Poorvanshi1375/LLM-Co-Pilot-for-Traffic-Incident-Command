/* ── Timeline — timestamped event log, newest first, current incident on top ── */
"use client";

import { useState } from "react";
import {
  Clock, AlertTriangle, Navigation, TrafficCone, Bell, Brain, Download,
  CheckCircle, Share2, XCircle, ChevronDown, ChevronRight,
} from "lucide-react";
import { useTrafficStore } from "@/lib/store";
import { formatTime } from "@/lib/utils";
import type { TimelineEntry } from "@/lib/types";

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  detection: <AlertTriangle className="w-3 h-3 text-danger" />,
  incident: <AlertTriangle className="w-3 h-3 text-danger" />,
  signal: <TrafficCone className="w-3 h-3 text-amber-600" />,
  routing: <Navigation className="w-3 h-3 text-primary" />,
  alert: <Bell className="w-3 h-3 text-sky-500" />,
  supervisor: <Brain className="w-3 h-3 text-purple-600" />,
  resolution: <CheckCircle className="w-3 h-3 text-success" />,
  social: <Share2 className="w-3 h-3 text-sky-500" />,
  error: <XCircle className="w-3 h-3 text-danger" />,
  system: <Clock className="w-3 h-3 text-muted" />,
};

/** Strip the leading emoji the server adds, since each row already has an icon. */
function eventText(e: string): string {
  return e.replace(/^[\u{1F300}-\u{1FAFF}☀-➿✅❌]️?\s*/u, "");
}

function EventList({ entries }: { entries: TimelineEntry[] }) {
  return (
    <div className="space-y-0">
      {entries.map((entry, i) => (
        <div key={`${entry.timestamp}-${i}`} className="flex gap-3 group">
          <div className="flex flex-col items-center">
            <div className="w-5 h-5 rounded-full border-2 border-border bg-white flex items-center justify-center z-10 group-hover:border-primary transition-colors">
              {CATEGORY_ICONS[entry.category] || CATEGORY_ICONS.system}
            </div>
            {i < entries.length - 1 && <div className="w-px flex-1 bg-border" />}
          </div>
          <div className="pb-4 flex-1">
            <p className="text-xs text-foreground leading-relaxed">{eventText(entry.event)}</p>
            <p className="text-[10px] text-muted mt-0.5">{formatTime(entry.timestamp)}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Timeline() {
  const timeline = useTrafficStore((s) => s.timeline);
  const [showEarlier, setShowEarlier] = useState(false);

  // The current (or latest) incident starts at the last detection event
  const lastDetection = timeline.map((t) => t.category).lastIndexOf("detection");
  const currentStart = lastDetection >= 0 ? lastDetection : 0;
  const current = timeline.slice(currentStart).reverse();
  const earlier = timeline.slice(0, currentStart).reverse();

  const exportCSV = () => {
    const cell = (v: string) => `"${v.replace(/"/g, '""')}"`;
    const csv = [
      "Timestamp (UTC),Brooklyn time,Event,Category",
      ...timeline.map((t) => [t.timestamp, formatTime(t.timestamp), eventText(t.event), t.category].map(cell).join(",")),
    ].join("\r\n");
    // UTF-8 byte-order mark so Excel shows non-ASCII characters correctly
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "traffic_timeline.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!timeline.length) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted py-12">
        <Clock className="w-10 h-10 mb-3 text-slate-300" />
        <p className="text-sm font-medium">No timeline events</p>
        <p className="text-xs mt-1">Events appear as agents process incidents</p>
      </div>
    );
  }

  return (
    <div className="p-1">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">Event Timeline</h3>
        </div>
        <button
          onClick={exportCSV}
          className="flex items-center gap-1 text-[10px] text-primary hover:text-primary/80 transition-colors"
        >
          <Download className="w-3 h-3" />
          Export CSV
        </button>
      </div>
      <p className="text-[10px] text-muted mb-3">Newest first · Brooklyn time</p>

      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted mb-2">
        {lastDetection >= 0 ? "Latest incident" : "Events"}
      </p>
      <EventList entries={current} />

      {earlier.length > 0 && (
        <div className="mt-1 border-t border-border pt-2">
          <button
            onClick={() => setShowEarlier(!showEarlier)}
            className="flex items-center gap-1 text-[11px] text-muted hover:text-foreground mb-2"
          >
            {showEarlier ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Earlier events ({earlier.length})
          </button>
          {showEarlier && <EventList entries={earlier} />}
        </div>
      )}
    </div>
  );
}
