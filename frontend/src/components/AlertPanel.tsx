/* ── Alert Panel — VMS, Radio, Social alerts ── */
"use client";

import { Bell, Monitor, Radio, MessageCircle, Copy, Check } from "lucide-react";
import { useTrafficStore } from "@/lib/store";
import { useState } from "react";
import { FallbackBadge, AgentsWorking } from "@/components/StatusOverlays";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const pushToast = useTrafficStore((s) => s.pushToast);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      pushToast("Couldn't copy — your browser blocked clipboard access. Select the text and copy it manually.");
    }
  };
  return (
    <button
      onClick={handleCopy}
      className="text-muted hover:text-primary transition-colors"
      title="Copy to clipboard"
    >
      {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}

export default function AlertPanel() {
  const agentOutput = useTrafficStore((s) => s.agentOutput);
  const alerts = agentOutput?.alerts;
  const processing = useTrafficStore((s) => s.processing);

  if (!alerts && processing) return <AgentsWorking what="Sign, radio and social alerts" />;
  if (!alerts) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted py-12">
        <Bell className="w-10 h-10 mb-3 text-slate-300" />
        <p className="text-sm font-medium">No alerts generated</p>
        <p className="text-xs mt-1">Alerts appear during active incidents</p>
      </div>
    );
  }

  return (
    <div className="space-y-3 p-1">
      <div className="flex items-center gap-2 mb-2">
        <Bell className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">Public Alert Drafts</h3>
        <FallbackBadge source={alerts.source} className="ml-auto" />
      </div>

      {/* VMS Signs */}
      <div className="border border-border rounded-lg p-3 bg-white">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5">
            <Monitor className="w-3.5 h-3.5 text-amber-600" />
            <span className="text-xs font-semibold text-foreground">
              Variable Message Signs
            </span>
          </div>
          <CopyButton text={alerts.vms.join("\n")} />
        </div>
        <div className="bg-slate-900 rounded-md p-3 font-mono">
          {alerts.vms.map((line, i) => (
            <p key={i} className="text-amber-400 text-xs leading-relaxed">
              {line}
            </p>
          ))}
        </div>
        <p className="text-[10px] text-muted mt-1.5">
          Constraint: ≤20 chars/line, 3 lines
        </p>
      </div>

      {/* Radio Script */}
      <div className="border border-border rounded-lg p-3 bg-white">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5">
            <Radio className="w-3.5 h-3.5 text-blue-600" />
            <span className="text-xs font-semibold text-foreground">
              Radio Script (15s)
            </span>
          </div>
          <CopyButton text={alerts.radio_script} />
        </div>
        <p className="text-xs text-foreground leading-relaxed bg-blue-50 rounded-md p-3 italic">
          &ldquo;{alerts.radio_script}&rdquo;
        </p>
      </div>

      {/* Social Media */}
      <div className="border border-border rounded-lg p-3 bg-white">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5">
            <MessageCircle className="w-3.5 h-3.5 text-sky-500" />
            <span className="text-xs font-semibold text-foreground">
              Social Media Post
            </span>
          </div>
          <CopyButton text={alerts.tweet} />
        </div>
        <p className="text-xs text-foreground leading-relaxed bg-sky-50 rounded-md p-3">
          {alerts.tweet}
        </p>
        <p className="text-[10px] text-muted mt-1.5">
          {alerts.tweet.length}/280 characters
        </p>
      </div>
    </div>
  );
}
