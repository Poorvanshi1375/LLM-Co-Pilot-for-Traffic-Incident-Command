/* ── Utility functions ── */
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function speedToColor(speed: number, freeFlow: number): string {
  const ratio = freeFlow > 0 ? speed / freeFlow : 0.5;
  if (ratio > 0.7) return "#10B981";      // Green — flowing
  if (ratio > 0.4) return "#F59E0B";      // Amber — slow
  return "#EF4444";                         // Red — congested
}

export function severityColor(severity: string): string {
  switch (severity) {
    case "LOW": return "#10B981";
    case "MEDIUM": return "#F59E0B";
    case "HIGH": return "#F97316";
    case "CRITICAL": return "#EF4444";
    default: return "#64748B";
  }
}

export function severityBg(severity: string): string {
  switch (severity) {
    case "LOW": return "bg-emerald-100 text-emerald-800";
    case "MEDIUM": return "bg-amber-100 text-amber-800";
    case "HIGH": return "bg-orange-100 text-orange-800";
    case "CRITICAL": return "bg-red-100 text-red-800";
    default: return "bg-slate-100 text-slate-800";
  }
}

export function confidenceColor(confidence: number): string {
  if (confidence >= 0.8) return "text-emerald-600";
  if (confidence >= 0.6) return "text-amber-600";
  return "text-red-600";
}

/** Clock time in Brooklyn (the sidebar clock uses the same zone), e.g. "9:58:05 AM". */
export function formatTime(isoString: string): string {
  try {
    return new Date(isoString).toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      timeZone: "America/New_York",
    });
  } catch {
    return isoString;
  }
}

export function formatHour(hour: number): string {
  const h = Math.floor(hour);
  const m = Math.floor((hour % 1) * 60);
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  return `${h12}:${m.toString().padStart(2, "0")} ${ampm}`;
}
