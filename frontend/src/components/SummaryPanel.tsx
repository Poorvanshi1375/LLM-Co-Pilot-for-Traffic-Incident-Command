/* ── Summary Panel — supervisor's final narrative + RAG context ── */
"use client";

import { Brain, FileText, BarChart3, AlertTriangle, ShieldCheck } from "lucide-react";
import { FallbackBadge } from "@/components/StatusOverlays";
import { useTrafficStore } from "@/lib/store";

export default function SummaryPanel() {
  const agentOutput = useTrafficStore((s) => s.agentOutput);

  if (!agentOutput) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted py-12">
        <Brain className="w-10 h-10 mb-3 text-slate-300" />
        <p className="text-sm font-medium">No summary yet</p>
        <p className="text-xs mt-1">The supervisor agent will synthesize all findings here</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-1">
      {/* Final Summary */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Brain className="w-4 h-4 text-purple-600" />
          <h3 className="text-sm font-semibold text-foreground">
            Supervisor Summary
          </h3>
          <FallbackBadge source={agentOutput.agent_status?.supervisor?.source} className="ml-auto" />
        </div>
        <div className="border border-border rounded-lg p-3 bg-purple-50/50">
          <p className="text-xs text-foreground leading-relaxed whitespace-pre-wrap">
            {agentOutput.final_summary}
          </p>
        </div>
      </div>

      {/* Coherence issues found by the supervisor */}
      {(agentOutput.coherence_issues?.length ?? 0) > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-warning" />
            <h3 className="text-sm font-semibold text-foreground">
              Conflicts Between Agents ({agentOutput.coherence_issues!.length})
            </h3>
          </div>
          <ul className="space-y-1.5">
            {agentOutput.coherence_issues!.map((issue, i) => (
              <li key={i} className="border border-amber-200 bg-amber-50 rounded-lg p-2.5 text-xs text-amber-900 leading-relaxed">
                {issue}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* SOP compliance note */}
      {agentOutput.sop_compliance && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <ShieldCheck className="w-4 h-4 text-success" />
            <h3 className="text-sm font-semibold text-foreground">SOP Compliance</h3>
          </div>
          <p className="border border-border rounded-lg p-2.5 bg-white text-xs text-slate-700 leading-relaxed">
            {agentOutput.sop_compliance}
          </p>
        </div>
      )}

      {/* RAG Context */}
      {agentOutput.rag_context?.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <FileText className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-semibold text-foreground">
              Referenced SOPs ({agentOutput.rag_context.length})
            </h3>
          </div>
          <div className="space-y-2">
            {agentOutput.rag_context.map((ctx, i) => (
              <div
                key={i}
                className="border border-border rounded-lg p-2.5 bg-white text-xs text-slate-600 leading-relaxed"
              >
                {ctx.slice(0, 300)}
                {ctx.length > 300 ? "…" : ""}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Evaluation Metrics */}
      {agentOutput.evaluation_metrics &&
        Object.keys(agentOutput.evaluation_metrics).length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <BarChart3 className="w-4 h-4 text-success" />
              <h3 className="text-sm font-semibold text-foreground">
                Evaluation Metrics
              </h3>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(agentOutput.evaluation_metrics).map(
                ([key, val]) => (
                  <div
                    key={key}
                    className="border border-border rounded-lg p-2 bg-white text-center"
                  >
                    <p className="text-[10px] text-muted capitalize">
                      {key.replace(/_/g, " ")}
                    </p>
                    <p className="text-sm font-bold text-foreground">
                      {typeof val === "number"
                        ? val < 1
                          ? `${(val * 100).toFixed(0)}%`
                          : val.toFixed(1)
                        : String(val)}
                    </p>
                  </div>
                )
              )}
            </div>
          </div>
        )}
    </div>
  );
}
