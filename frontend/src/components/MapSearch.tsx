/* ── Map Search — find a monitored street or a Brooklyn place (overview mode) ── */
"use client";

import { useMemo, useRef, useState } from "react";
import { Search, X, MapPin, Activity, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { GeocodeSuggestion, SegmentSpeed } from "@/lib/types";

export default function MapSearch({
  segments,
  onPickStreet,
  onPickPlace,
  onClear,
}: {
  segments: SegmentSpeed[];
  onPickStreet: (street: string) => void;
  onPickPlace: (place: GeocodeSuggestion) => void;
  onClear: () => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [places, setPlaces] = useState<GeocodeSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Monitored streets match instantly from the live feed
  const streets = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return [];
    const names = [...new Set(segments.map((s) => s.street_name))];
    return names.filter((n) => n.toLowerCase().includes(q)).sort((a, b) => a.length - b.length).slice(0, 4);
  }, [query, segments]);

  const onChange = (value: string) => {
    setQuery(value);
    setOpen(true);
    clearTimeout(debounce.current);
    if (value.trim().length < 3) {
      setPlaces([]);
      return;
    }
    setLoading(true);
    debounce.current = setTimeout(async () => {
      try {
        const data = await api.geocodeSearch(value);
        setPlaces(data?.suggestions || []);
      } catch {
        setPlaces([]);
      } finally {
        setLoading(false);
      }
    }, 300);
  };

  const clear = () => {
    setQuery("");
    setPlaces([]);
    setOpen(false);
    onClear();
  };

  const showList = open && query.trim().length >= 2 && (streets.length > 0 || places.length > 0 || loading);

  return (
    <div className="relative">
      <div className="flex items-center bg-white rounded-lg shadow-md border border-slate-200 px-3 py-2">
        <Search className="w-3.5 h-3.5 text-muted mr-2 shrink-0" />
        <input
          type="text"
          value={query}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
            if (e.key === "Enter") {
              if (streets[0]) { onPickStreet(streets[0]); setQuery(streets[0]); setOpen(false); }
              else if (places[0]) { onPickPlace(places[0]); setQuery(places[0].place_name); setOpen(false); }
            }
          }}
          placeholder="Search a street or place in Brooklyn"
          aria-label="Search a street or place"
          className="flex-1 min-w-0 text-xs text-foreground bg-transparent outline-none placeholder:text-muted"
        />
        {loading && <Loader2 className="w-3.5 h-3.5 text-muted animate-spin ml-1" />}
        {query && (
          <button onClick={clear} aria-label="Clear search" className="ml-1">
            <X className="w-3.5 h-3.5 text-muted hover:text-foreground" />
          </button>
        )}
      </div>

      {showList && (
        <div className="absolute top-full mt-1 w-full bg-white rounded-lg shadow-lg border border-slate-200 max-h-72 overflow-y-auto z-20 text-xs">
          {streets.length > 0 && (
            <>
              <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">Streets with live traffic</p>
              {streets.map((name) => (
                <button
                  key={name}
                  onClick={() => { onPickStreet(name); setQuery(name); setOpen(false); }}
                  className="w-full flex items-center gap-2 text-left px-3 py-2 hover:bg-slate-50"
                >
                  <Activity className="w-3.5 h-3.5 text-primary shrink-0" />
                  <span className="text-foreground">{name}</span>
                </button>
              ))}
            </>
          )}
          {places.length > 0 && (
            <>
              <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">Places</p>
              {places.map((p, i) => (
                <button
                  key={`${p.place_name}-${i}`}
                  onClick={() => { onPickPlace(p); setQuery(p.place_name); setOpen(false); }}
                  className="w-full flex items-center gap-2 text-left px-3 py-2 hover:bg-slate-50"
                >
                  <MapPin className="w-3.5 h-3.5 text-muted shrink-0" />
                  <span className="text-foreground truncate">{p.place_name}</span>
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
