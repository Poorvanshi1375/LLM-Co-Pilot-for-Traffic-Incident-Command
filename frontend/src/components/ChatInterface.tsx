/* ── Chat Interface — TAO conversational AI ── */
"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { MessageSquare, Send, Bot, User, Wrench, Loader2, FileText, ChevronDown, ChevronRight, Mic, MicOff, Volume2 } from "lucide-react";
import { useTrafficStore } from "@/lib/store";
import { api, errorMessage } from "@/lib/api";
import { FallbackBadge } from "@/components/StatusOverlays";
import { cn, formatTime } from "@/lib/utils";
import type { ChatMessage } from "@/lib/types";

function RagSourceBadges({ sources }: { sources: string[] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-[10px] text-primary hover:underline"
      >
        <FileText className="w-3 h-3" />
        <span>{sources.length} SOP Source{sources.length > 1 ? "s" : ""}</span>
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
      </button>
      {expanded && (
        <div className="mt-1 flex flex-wrap gap-1">
          {sources.map((src, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 text-[10px] bg-primary/10 text-primary rounded-full px-2 py-0.5"
            >
              <FileText className="w-2.5 h-2.5" />
              {src}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ChatInterface() {
  const messages = useTrafficStore((s) => s.messages);
  const addMessage = useTrafficStore((s) => s.addMessage);
  const setMessages = useTrafficStore((s) => s.setMessages);
  const pushToast = useTrafficStore((s) => s.pushToast);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [voiceStatus, setVoiceStatus] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const audioChunks = useRef<Blob[]>([]);
  const silenceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const silenceCheckRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  // Restore this browser's conversation after a reload (the server keeps it per session)
  useEffect(() => {
    if (useTrafficStore.getState().messages.length) return;
    api.getChatHistory()
      .then((res) => { if (res?.messages?.length) setMessages(res.messages); })
      .catch(() => {});
  }, [setMessages]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (silenceTimer.current) clearTimeout(silenceTimer.current);
      if (maxTimer.current) clearTimeout(maxTimer.current);
      if (silenceCheckRef.current) clearInterval(silenceCheckRef.current);
      if (audioCtxRef.current) audioCtxRef.current.close().catch(() => {});
    };
  }, []);

  const speakText = useCallback((text: string, audioBase64?: string) => {
    if (!ttsEnabled || typeof window === "undefined") return;
    window.speechSynthesis.cancel();

    // Prefer gTTS audio if available
    if (audioBase64) {
      try {
        const audioBytes = atob(audioBase64);
        const arr = new Uint8Array(audioBytes.length);
        for (let i = 0; i < audioBytes.length; i++) arr[i] = audioBytes.charCodeAt(i);
        const blob = new Blob([arr], { type: "audio/mpeg" });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.onended = () => URL.revokeObjectURL(url);
        audio.play().catch(() => {});
        return;
      } catch { /* fall through to browser TTS */ }
    }

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.05;
    utterance.pitch = 1;
    window.speechSynthesis.speak(utterance);
  }, [ttsEnabled]);

  const addBotResponse = useCallback((res: any, isVoice: boolean = false) => {
    const botMsg: ChatMessage = {
      role: "assistant",
      content: res.response,
      timestamp: new Date().toISOString(),
      tool_calls: res.tool_calls || [],
      thinking: res.thinking || "",
      rag_sources: res.rag_sources || [],
      source: res.source,
    };
    addMessage(botMsg);
    if (isVoice) speakText(res.response, res.audio_base64);
  }, [addMessage, speakText]);

  // ── Voice recording with silence detection ──
  const SILENCE_THRESHOLD = 15;       // RMS level below which = silence (0-128 range)
  const SILENCE_DURATION_MS = 1500;   // Stop after 1.5s of silence
  const MAX_RECORDING_MS = 15000;     // Hard cap at 15 seconds

  const cleanupRecording = useCallback(() => {
    if (silenceTimer.current) { clearTimeout(silenceTimer.current); silenceTimer.current = null; }
    if (maxTimer.current) { clearTimeout(maxTimer.current); maxTimer.current = null; }
    if (silenceCheckRef.current) { clearInterval(silenceCheckRef.current); silenceCheckRef.current = null; }
    if (audioCtxRef.current) { audioCtxRef.current.close().catch(() => {}); audioCtxRef.current = null; }
    analyserRef.current = null;
    setVoiceStatus("");
  }, []);

  const stopRecording = useCallback(() => {
    cleanupRecording();
    if (mediaRecorder.current && mediaRecorder.current.state !== "inactive") {
      mediaRecorder.current.stop();
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setRecording(false);
  }, [cleanupRecording]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      // Choose best supported mime type
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });
      audioChunks.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunks.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        const blob = new Blob(audioChunks.current, { type: mimeType });
        if (blob.size < 100) return;

        setVoiceStatus("Transcribing…");
        setLoading(true);
        try {
          const res = await api.sendVoice(blob);
          if (res.transcript) {
            addMessage({
              role: "user",
              content: `🎤 ${res.transcript}`,
              timestamp: new Date().toISOString(),
              tool_calls: [],
              thinking: "",
            });
          }
          addBotResponse(res, true);
        } catch (e) {
          addMessage({
            role: "assistant",
            content: `Voice processing failed: ${errorMessage(e)}`,
            timestamp: new Date().toISOString(),
            tool_calls: [],
            thinking: "",
          });
        } finally {
          setLoading(false);
          setVoiceStatus("");
        }
      };

      mediaRecorder.current = recorder;
      // Collect data every 250ms for reliability
      recorder.start(250);
      setRecording(true);
      setVoiceStatus("Listening…");

      // ── Silence detection via Web Audio API ──
      const audioCtx = new AudioContext();
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyserRef.current = analyser;

      const dataArray = new Uint8Array(analyser.fftSize);
      let speechDetected = false;

      silenceCheckRef.current = setInterval(() => {
        if (!analyserRef.current) return;
        analyserRef.current.getByteTimeDomainData(dataArray);
        // Compute RMS
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          const val = dataArray[i] - 128;
          sum += val * val;
        }
        const rms = Math.sqrt(sum / dataArray.length);

        if (rms > SILENCE_THRESHOLD) {
          // Speech detected — cancel any pending silence stop
          speechDetected = true;
          setVoiceStatus("Listening… 🔴");
          if (silenceTimer.current) {
            clearTimeout(silenceTimer.current);
            silenceTimer.current = null;
          }
        } else if (speechDetected && !silenceTimer.current) {
          // Silence after speech — start countdown
          setVoiceStatus("Finishing…");
          silenceTimer.current = setTimeout(() => {
            stopRecording();
          }, SILENCE_DURATION_MS);
        }
      }, 100);

      // Hard maximum recording cap
      maxTimer.current = setTimeout(() => {
        stopRecording();
      }, MAX_RECORDING_MS);

    } catch {
      setVoiceStatus("");
      pushToast("Microphone unavailable — allow microphone access in your browser to use voice chat.");
    }
  }, [addMessage, addBotResponse, stopRecording, cleanupRecording, pushToast]);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: trimmed,
      timestamp: new Date().toISOString(),
      tool_calls: [],
      thinking: "",
    };
    addMessage(userMsg);
    setInput("");
    setLoading(true);

    try {
      const res = await api.sendChat(trimmed);
      addBotResponse(res);
    } catch (e) {
      addMessage({
        role: "assistant",
        content: `Couldn't send that: ${errorMessage(e)}`,
        timestamp: new Date().toISOString(),
        tool_calls: [],
        thinking: "",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full p-1">
      <div className="flex items-center gap-2 mb-3">
        <MessageSquare className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">
          AI Chat — Narrative Agent
        </h3>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto space-y-3 mb-3 pr-1"
        style={{ maxHeight: "calc(100vh - 320px)" }}
      >
        {messages.length === 0 && (
          <div className="text-center py-8 text-muted">
            <Bot className="w-8 h-8 mx-auto mb-2 text-slate-300" />
            <p className="text-xs">Ask about current traffic conditions,</p>
            <p className="text-xs">incident status, or diversion routes.</p>
            <div className="mt-3 space-y-1.5">
              {[
                "What's the current traffic situation?",
                "How bad is the congestion on Atlantic Ave?",
                "What's the diversion route status?",
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => setInput(q)}
                  className="block w-full text-left text-[11px] text-primary hover:bg-primary/5 rounded px-2 py-1 transition-colors"
                >
                  &ldquo;{q}&rdquo;
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={cn(
              "flex gap-2",
              msg.role === "user" ? "justify-end" : "justify-start"
            )}
          >
            {msg.role === "assistant" && (
              <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                <Bot className="w-3.5 h-3.5 text-primary" />
              </div>
            )}
            <div
              className={cn(
                "max-w-[85%] rounded-lg px-3 py-2",
                msg.role === "user"
                  ? "bg-primary text-white"
                  : "bg-slate-50 border border-border"
              )}
            >
              <p className="text-xs leading-relaxed whitespace-pre-wrap">
                {msg.content}
              </p>

              {/* Tool calls */}
              {msg.tool_calls?.length > 0 && (
                <div className="mt-2 space-y-1">
                  {msg.tool_calls.map((tc, j) => (
                    <div
                      key={j}
                      className="flex items-start gap-1 text-[10px] text-muted bg-white/50 rounded px-1.5 py-1"
                    >
                      <Wrench className="w-3 h-3 mt-0.5 flex-shrink-0" />
                      <span>
                        <strong>{tc.tool}</strong>({tc.args}) → {tc.result.slice(0, 80)}
                        {tc.result.length > 80 ? "…" : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {msg.role === "assistant" && <FallbackBadge source={msg.source} className="mt-2" />}

              {/* RAG Source badges */}
              {msg.role === "assistant" && msg.rag_sources && msg.rag_sources.length > 0 && (
                <RagSourceBadges sources={msg.rag_sources} />
              )}

              <p className="text-[9px] mt-1 opacity-60">
                {formatTime(msg.timestamp)}
              </p>
            </div>
            {msg.role === "user" && (
              <div className="w-6 h-6 rounded-full bg-primary flex items-center justify-center flex-shrink-0 mt-0.5">
                <User className="w-3.5 h-3.5 text-white" />
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex items-center gap-2 text-muted">
            <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
              <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" />
            </div>
            <span className="text-xs">Thinking…</span>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="flex flex-col gap-2 border-t border-border pt-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder={recording ? `🎤 ${voiceStatus}` : loading ? "Processing…" : "Ask about traffic conditions…"}
            className="flex-1 text-xs border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
            disabled={loading || recording}
          />
          <button
            onClick={recording ? stopRecording : startRecording}
            disabled={loading}
            className={cn(
              "px-3 py-2 rounded-lg transition-colors",
              recording
                ? "bg-red-500 text-white animate-pulse"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            )}
            title={recording ? "Stop recording" : "Voice input"}
          >
            {recording ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
          </button>
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            className="px-3 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="flex items-center justify-end">
          <button
            onClick={() => {
              setTtsEnabled(!ttsEnabled);
              if (ttsEnabled) window.speechSynthesis.cancel();
            }}
            className={cn(
              "flex items-center gap-1 text-[10px] rounded px-1.5 py-0.5 transition-colors",
              ttsEnabled ? "text-primary bg-primary/10" : "text-muted bg-slate-50"
            )}
          >
            <Volume2 className="w-3 h-3" />
            <span>Voice {ttsEnabled ? "On" : "Off"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
