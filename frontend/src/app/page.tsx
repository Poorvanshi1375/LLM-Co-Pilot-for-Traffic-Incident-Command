/* ── Landing Page — marketing-grade hero ── */
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { motion } from "framer-motion";
import {
  Zap, TrafficCone, Navigation, Bell, MessageSquare,
  Brain, Gauge, Shield, BarChart3, ArrowRight,
  Radio, Monitor, GitBranch, Layers,
} from "lucide-react";

const FEATURES = [
  {
    icon: TrafficCone,
    title: "Signal Re-Timing",
    desc: "AI-driven phase optimization for upstream intersections within seconds of incident detection.",
    color: "text-amber-600",
    bg: "bg-amber-50",
  },
  {
    icon: Navigation,
    title: "Dynamic Routing",
    desc: "Risk-weighted shortest paths on the real Brooklyn road graph route traffic around the blocked zone in real time.",
    color: "text-blue-600",
    bg: "bg-blue-50",
  },
  {
    icon: Bell,
    title: "Public Alerts",
    desc: "Format-constrained VMS signs, 15-second radio scripts, and social media posts — all auto-generated.",
    color: "text-sky-600",
    bg: "bg-sky-50",
  },
  {
    icon: MessageSquare,
    title: "Conversational AI",
    desc: "Natural-language Q&A with tool-calling, providing officers real-time situational awareness.",
    color: "text-emerald-600",
    bg: "bg-emerald-50",
  },
  {
    icon: Brain,
    title: "Multi-Agent Orchestration",
    desc: "A supervisor agent checks the specialist agents' outputs for conflicts after they run in parallel.",
    color: "text-purple-600",
    bg: "bg-purple-50",
  },
  {
    icon: Gauge,
    title: "Vehicle Density",
    desc: "Dual-mode density estimation via flow equations and Gemini Vision for camera-based counting.",
    color: "text-rose-600",
    bg: "bg-rose-50",
  },
];

const TECH = [
  { icon: Layers, label: "Next.js + TypeScript" },
  { icon: GitBranch, label: "Parallel Multi-Agent Pipeline" },
  { icon: Brain, label: "Groq gpt-oss-120b + Gemini 2.5 Flash" },
  { icon: Monitor, label: "Mapbox GL Maps" },
  { icon: Radio, label: "WebSocket Real-Time Feed" },
  { icon: Shield, label: "RAG + 12 SOP Documents" },
];

const STATS = [
  { value: "6", label: "AI Agents" },
  { value: "~6s", label: "Full Agent Response" },
  { value: "250", label: "Road Segments" },
  { value: "12", label: "SOP Documents" },
];

const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.1, duration: 0.5, ease: "easeOut" as const },
  }),
};

export default function Home() {
  const router = useRouter();

  // Start waking the (free-tier, possibly sleeping) backend before the user opens the dashboard
  useEffect(() => {
    api.health().catch(() => {});
  }, []);

  return (
    <div className="min-h-screen bg-white">
      {/* Header */}
      <header className="fixed top-0 w-full z-50 glass-card border-b border-border/50">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <Zap className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-bold text-foreground">TrafficMind</span>
          </div>
          <nav className="hidden md:flex items-center gap-8 text-sm text-muted">
            <a href="#features" className="hover:text-foreground transition-colors">Features</a>
            <a href="#architecture" className="hover:text-foreground transition-colors">Architecture</a>
            <a href="#tech" className="hover:text-foreground transition-colors">Tech Stack</a>
          </nav>
          <button
            onClick={() => router.push("/dashboard")}
            className="px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors flex items-center gap-1.5"
          >
            Launch Dashboard
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Hero */}
      <section className="pt-32 pb-20 px-6">
        <div className="max-w-4xl mx-auto text-center">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <div className="inline-flex items-center gap-2 px-3 py-1 bg-primary/5 border border-primary/20 rounded-full text-xs text-primary font-medium mb-6">
              <Zap className="w-3 h-3" />
              LLM-Powered Traffic Incident Command · Demo on a simulated Brooklyn traffic feed
            </div>
          </motion.div>

          <motion.h1
            className="text-5xl md:text-6xl font-bold text-foreground leading-tight mb-6"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1, duration: 0.6 }}
          >
            Your AI Co-Pilot for{" "}
            <span className="gradient-text">Traffic Incident</span>{" "}
            Command
          </motion.h1>

          <motion.p
            className="text-lg text-muted max-w-2xl mx-auto mb-10 leading-relaxed"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.6 }}
          >
            TrafficMind orchestrates six specialized AI agents to deliver signal re-timing,
            dynamic routing, public alerts, and real-time situational awareness — reducing
            incident response time from minutes to seconds.
          </motion.p>

          <motion.div
            className="flex items-center justify-center gap-4"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, duration: 0.6 }}
          >
            <button
              onClick={() => router.push("/dashboard")}
              className="px-6 py-3 bg-primary text-white font-medium rounded-xl hover:bg-primary/90 transition-colors flex items-center gap-2 shadow-lg shadow-primary/20"
            >
              Open Command Center
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => router.push("/twin")}
              className="px-6 py-3 border border-border text-foreground font-medium rounded-xl hover:bg-accent transition-colors"
            >
              View Digital Twin
            </button>
          </motion.div>

          {/* Stats */}
          <motion.div
            className="grid grid-cols-4 gap-6 max-w-xl mx-auto mt-16"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4, duration: 0.6 }}
          >
            {STATS.map((stat) => (
              <div key={stat.label} className="text-center">
                <p className="text-3xl font-bold gradient-text">{stat.value}</p>
                <p className="text-xs text-muted mt-1">{stat.label}</p>
              </div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-20 px-6 bg-slate-50/50">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold text-foreground mb-3">
              Six AI Agents, One Command Center
            </h2>
            <p className="text-muted max-w-2xl mx-auto">
              Each agent specializes in a critical aspect of incident management,
              orchestrated by a supervisor for coherent, conflict-free responses.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f, i) => (
              <motion.div
                key={f.title}
                custom={i}
                variants={fadeUp}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                className="bg-white border border-border rounded-xl p-6 hover:shadow-md transition-shadow"
              >
                <div className={`w-10 h-10 ${f.bg} rounded-lg flex items-center justify-center mb-4`}>
                  <f.icon className={`w-5 h-5 ${f.color}`} />
                </div>
                <h3 className="text-sm font-semibold text-foreground mb-2">{f.title}</h3>
                <p className="text-xs text-muted leading-relaxed">{f.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Architecture */}
      <section id="architecture" className="py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold text-foreground mb-3">
              Multi-Agent Architecture
            </h2>
            <p className="text-muted max-w-2xl mx-auto">
              Built on a parallel fan-out agent pipeline, RAG-enhanced decision making,
              and real-time WebSocket communication.
            </p>
          </div>

          {/* Architecture Diagram */}
          <div className="bg-white border border-border rounded-2xl p-8">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              {/* Data Layer */}
              <div className="text-center">
                <div className="bg-blue-50 rounded-xl p-4 mb-3">
                  <BarChart3 className="w-8 h-8 text-primary mx-auto mb-2" />
                  <h4 className="text-sm font-semibold text-foreground">Data Layer</h4>
                </div>
                <div className="space-y-1.5 text-xs text-muted">
                  <p>Brooklyn Road Network (OSMnx)</p>
                  <p>Speed Feed Engine (5s ticks)</p>
                  <p>Risk Scorer + Anomaly Detector</p>
                  <p>21 Historical Hotspots</p>
                </div>
              </div>

              {/* Agent Layer */}
              <div className="text-center">
                <div className="bg-purple-50 rounded-xl p-4 mb-3">
                  <Brain className="w-8 h-8 text-purple-600 mx-auto mb-2" />
                  <h4 className="text-sm font-semibold text-foreground">Agent Layer</h4>
                </div>
                <div className="space-y-1.5 text-xs text-muted">
                  <p>Signal Agent (Groq gpt-oss)</p>
                  <p>Routing Agent (road graph + Groq)</p>
                  <p>Alert Agent (3-format Groq)</p>
                  <p>Density Agent (Gemini Vision)</p>
                  <p>Supervisor (Gemini 2.5 Flash)</p>
                  <p>Narrative Agent (Groq + Gemini)</p>
                </div>
              </div>

              {/* Presentation Layer */}
              <div className="text-center">
                <div className="bg-emerald-50 rounded-xl p-4 mb-3">
                  <Monitor className="w-8 h-8 text-emerald-600 mx-auto mb-2" />
                  <h4 className="text-sm font-semibold text-foreground">Presentation Layer</h4>
                </div>
                <div className="space-y-1.5 text-xs text-muted">
                  <p>Mapbox GL Live Traffic Map</p>
                  <p>Real-Time Dashboard</p>
                  <p>Digital Twin Comparison</p>
                  <p>Conversational Interface</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Tech Stack */}
      <section id="tech" className="py-20 px-6 bg-slate-50/50">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold text-foreground mb-3">Tech Stack</h2>
            <p className="text-muted">Production-grade, SaaS-ready infrastructure</p>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {TECH.map((t, i) => (
              <motion.div
                key={t.label}
                custom={i}
                variants={fadeUp}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                className="bg-white border border-border rounded-xl p-4 flex items-center gap-3 hover:shadow-sm transition-shadow"
              >
                <t.icon className="w-5 h-5 text-primary flex-shrink-0" />
                <span className="text-sm font-medium text-foreground">{t.label}</span>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-8 px-6 border-t border-border">
        <div className="max-w-6xl mx-auto flex items-center justify-between text-xs text-muted">
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 rounded bg-primary flex items-center justify-center">
              <Zap className="w-3 h-3 text-white" />
            </div>
            <span>TrafficMind — Built for Aestrix Hackathon 2026</span>
          </div>
          <span>Team 2AM Coders</span>
        </div>
      </footer>
    </div>
  );
}
