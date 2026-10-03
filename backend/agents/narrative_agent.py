"""
Narrative Agent — Conversational TAO loop for officer Q&A.
TAO = Thought → Action (tool call) → Observation → Answer.
Uses Groq (gpt-oss) with Gemini as fallback, with multi-turn memory.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from models.schemas import (
    SegmentSpeed, RiskEntry, IncidentDetection, AgentOutput,
    ChatMessage, ChatResponse,
)

from core.llm import generate
from core.risk_scorer import compute_risk_map
from rag.retriever import retrieve_sops

TOOL_PATTERN = r'\[TOOL(?:_CALL)?:\s*(\w+)\(([^)]*)\)\]'


SYSTEM_PROMPT = """You are TrafficMind, an AI co-pilot assisting traffic control officers in Brooklyn, New York.
You have access to real-time traffic sensor data and incident management tools.

PERSONA: Friendly, professional, conversational. Speak naturally like a knowledgeable colleague — not a document reader.
The officer stays in command — you handle the cognitive load and give them clear, actionable information.

AVAILABLE TOOLS (use by including [TOOL_CALL: tool_name(args)] in your thinking):
- get_speed(street_name) → current speed in mph and % of normal
- get_risk_score(street_name) → risk score 0-1 with breakdown
- check_diversion_status() → current diversion route: streets, risk reduction, share of traffic redirected
- get_density(street_name) → vehicle density and congestion level

HOW TO RESPOND:
1. Think through the question internally
2. Call any tools needed to get data
3. Write a clear, natural-language answer using the data
4. Reference specific numbers when helpful (e.g., "Flatbush is moving at 12 mph, about 40% of normal")
5. End with confidence level: [Confidence: HIGH/MEDIUM/LOW]

CRITICAL RULES:
- NEVER reproduce SOP text verbatim. You have reference SOPs for background knowledge only — use them to inform your judgment, then answer in your OWN words conversationally.
- DO NOT dump raw data tables or tool output. Synthesize information into a helpful, human-readable response.
- If you have SOP context, weave the relevant guidance naturally into your answer (e.g., "Based on our protocols, you'd want to..." rather than copying SOP paragraphs).
- Keep answers concise — 2-4 sentences for simple questions, more for complex safety assessments.
- Write plain text only: no Markdown (no **bold**, no # headings, no bullet symbols). Use short sentences, or simple numbered lines like "1. ..." when listing.
- Be proactive: if data suggests something the officer should know, mention it.
- ONLY state facts and numbers that appear in CURRENT SITUATION or tool observations. If the data you need is not there, say plainly that you don't have it. Never estimate or invent figures (compliance rates, flows, percentages).

IMPORTANT: Maintain context across the conversation. Reference previous questions/answers when relevant.
If the officer asks about safety (e.g., "Is it safe to open the southbound lane?"),
check speed, risk, and density data before answering."""


class NarrativeAgent:
    """Conversational agent with TAO loop and tool access."""

    def __init__(self, feed_engine=None):
        self._messages: list[ChatMessage] = []
        self._incident: IncidentDetection | None = None
        self._agent_output: AgentOutput | None = None
        self._snapshot: list[SegmentSpeed] = []
        self._risk_map: list[RiskEntry] = []
        self._feed_engine = feed_engine

    def _get_live_snapshot(self) -> list[SegmentSpeed]:
        """Get live data from feed engine, falling back to last incident snapshot."""
        if self._feed_engine:
            return self._feed_engine.get_snapshot()
        return self._snapshot

    def _get_live_risk_map(self) -> list[RiskEntry]:
        """Compute live risk scores from current feed data."""
        snapshot = self._get_live_snapshot()
        if snapshot:
            hour = self._feed_engine.get_simulated_hour() if self._feed_engine else 9.0
            return compute_risk_map(snapshot, hour)
        return self._risk_map

    def set_context(
        self,
        incident: IncidentDetection,
        agent_output: AgentOutput,
        snapshot: list[SegmentSpeed],
        risk_map: list[RiskEntry],
    ):
        """Update the agent's context with latest data."""
        self._incident = incident
        self._agent_output = agent_output
        self._snapshot = snapshot
        self._risk_map = risk_map

    def _execute_tool(self, tool_name: str, args: str) -> str:
        """Execute a TAO tool call and return observation."""
        live_snapshot = self._get_live_snapshot()
        live_risk = self._get_live_risk_map()
        speed_by_name = {s.street_name.lower(): s for s in live_snapshot}
        risk_by_name = {r.street_name.lower(): r for r in live_risk}

        if tool_name == "get_speed":
            street = args.strip().strip('"').strip("'").lower()
            # Fuzzy match
            matched = None
            for name, seg in speed_by_name.items():
                if street in name or name in street:
                    matched = seg
                    break
            if matched:
                pct = round(matched.speed / matched.free_flow_speed * 100, 1) if matched.free_flow_speed > 0 else 0
                return f"{matched.street_name}: {matched.speed} mph ({pct}% of normal {matched.free_flow_speed} mph), density: {matched.density} veh/km"
            return f"No speed data found for '{args}'"

        elif tool_name == "get_risk_score":
            street = args.strip().strip('"').strip("'").lower()
            matched = None
            for name, risk in risk_by_name.items():
                if street in name or name in street:
                    matched = risk
                    break
            if matched:
                return (f"{matched.street_name}: risk score {matched.score:.2f} "
                       f"(speed_dev: {matched.speed_deviation:.2f}, "
                       f"historical: {matched.historical_rate:.2f}, "
                       f"tod: {matched.tod_weight:.2f})")
            return f"No risk data found for '{args}'"

        elif tool_name == "check_diversion_status":
            if self._agent_output and self._agent_output.diversion:
                d = self._agent_output.diversion
                return (f"Diversion ACTIVE via {' → '.join(d.route_street_names[:4])}. "
                       f"Risk delta: {d.risk_delta_pct}% safer. "
                       f"Volume redistribution: {d.diversion_volume_pct}%. "
                       f"Confidence: {d.confidence:.0%}")
            return "No active diversion route."

        elif tool_name == "get_density":
            street = args.strip().strip('"').strip("'").lower()
            if self._agent_output and self._agent_output.density:
                density = self._agent_output.density.segment_densities.get(street)
                if density:
                    return f"{street}: density {density} veh/km, overall congestion: {self._agent_output.density.congestion_level}"
            # Fallback to live snapshot density
            for seg in live_snapshot:
                if street in seg.street_name.lower() or seg.street_name.lower() in street:
                    return f"{seg.street_name}: density {seg.density} veh/km"
            return f"No density data for '{args}'"

        return f"Unknown tool: {tool_name}"

    @staticmethod
    def _speed_line(seg: SegmentSpeed) -> str:
        pct = round(seg.speed / seg.free_flow_speed * 100) if seg.free_flow_speed > 0 else 0
        return (f"  {seg.street_name}: {seg.speed:.0f} mph ({pct}% of {seg.free_flow_speed:.0f} mph free-flow), "
                f"density {seg.density:.0f} veh/km")

    def _relevant_segments(self, snapshot: list[SegmentSpeed], question: str, limit: int = 30) -> list[SegmentSpeed]:
        """Streets named in the question, then near the incident, then the most congested."""
        q = question.lower()

        def named(seg: SegmentSpeed) -> bool:
            name = seg.street_name.lower()
            short = name.replace(" avenue", " ave").replace(" street", " st").replace(" boulevard", " blvd")
            return name in q or short in q or name.split(" ")[0] in q.split()

        mentioned = [s for s in snapshot if named(s)][:10]
        near: list[SegmentSpeed] = []
        if self._incident:
            from core.risk_scorer import _haversine
            inc = self._incident
            near = sorted(
                (s for s in snapshot if _haversine(inc.lat, inc.lon, s.lat, s.lon) < 1.0),
                key=lambda s: _haversine(inc.lat, inc.lon, s.lat, s.lon),
            )[:10]
        congested = sorted(snapshot, key=lambda s: s.speed / max(s.free_flow_speed, 1))[:15]

        chosen, seen = [], set()
        for s in mentioned + near + congested:
            if s.segment_id not in seen:
                seen.add(s.segment_id)
                chosen.append(s)
        return chosen[:limit]

    async def chat(self, user_message: str, voice: bool = False) -> ChatResponse:
        """Process officer's question through TAO loop."""
        self._messages.append(ChatMessage(
            role="user",
            content=user_message,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

        # RAG: retrieve relevant SOP documents
        rag_docs = retrieve_sops(user_message, top_k=2)
        rag_sources: list[str] = []
        if rag_docs:
            for doc in rag_docs:
                # Extract doc name from "[Doc Name]\ncontent" format
                if doc.startswith("[") and "]" in doc:
                    name = doc[1:doc.index("]")]
                    rag_sources.append(name)

        # Build context
        context_parts = []

        if rag_docs:
            context_parts.append("REFERENCE KNOWLEDGE (use as background — do NOT quote verbatim):\n" + "\n---\n".join(rag_docs))

        if self._incident:
            context_parts.append(
                f"ACTIVE INCIDENT: {self._incident.severity.value} on {self._incident.street_name} "
                f"(detected {self._incident.timestamp}). "
                f"Duration estimate: {self._incident.duration_estimate_min} min. "
                f"Description: {self._incident.description}"
            )

        else:
            context_parts.append("ACTIVE INCIDENT: none. No diversion, signal plan or alerts are active.")

        # Live traffic data: a focused selection keeps the prompt small (LLM free tiers
        # cap tokens per minute) while covering what the officer is likely asking about
        live_snapshot = self._get_live_snapshot()
        if live_snapshot:
            context_parts.append(
                "LIVE SENSOR DATA (selected monitored streets; others are not listed):\n"
                + "\n".join(self._speed_line(seg) for seg in self._relevant_segments(live_snapshot, user_message))
            )

        if self._agent_output:
            if self._agent_output.signal_recommendations:
                sigs = [f"  - {s.intersection_name}: {s.recommended_phase} ({s.confidence:.0%})"
                       for s in self._agent_output.signal_recommendations[:3]]
                context_parts.append("SIGNAL RECOMMENDATIONS:\n" + "\n".join(sigs))
            if self._agent_output.diversion:
                d = self._agent_output.diversion
                context_parts.append(
                    f"DIVERSION (planned, not measured): via {' → '.join(d.route_street_names[:6])}; "
                    f"{d.risk_delta_pct}% lower risk than the incident segment; about {d.time_delta_min} min longer; "
                    f"model estimate {d.diversion_volume_pct}% of traffic redirected. "
                    "Driver compliance with the diversion is NOT measured — never report a compliance figure."
                )
            if self._agent_output.final_summary:
                context_parts.append(f"SUMMARY: {self._agent_output.final_summary}")

        context = "\n\n".join(context_parts)

        # Build conversation history for Gemini
        history_text = ""
        for msg in self._messages[-10:]:  # Last 10 messages
            role_label = "OFFICER" if msg.role == "user" else "TRAFFICMIND"
            history_text += f"\n{role_label}: {msg.content}"

        voice_instruction = """

VOICE MODE — This answer will be spoken aloud via text-to-speech.
Be EXTREMELY concise: 1-2 short sentences max. Give only the key data point or action.
No greetings, no filler, no "Let me check" — just the essential answer.""" if voice else ""

        prompt = f"""{SYSTEM_PROMPT}

CURRENT SITUATION:
{context}

CONVERSATION HISTORY:
{history_text}{voice_instruction}

Respond to the officer's latest question naturally and conversationally. Use tools if needed by including [TOOL: tool_name("arg")] in your thinking.
Synthesize any reference knowledge into your own words — never copy it verbatim. Then provide the final answer."""

        try:
            # Chat is the busiest caller: Groq first (generous limits), Gemini as fallback
            response_text = await generate(
                prompt, max_tokens=400 if voice else 1024, temperature=0.4, prefer="groq",
            )
            thinking = ""
            tool_calls = []

            # TAO loop: execute any tool calls the model asked for, then re-query
            matches = re.findall(TOOL_PATTERN, response_text)
            for tool_name, tool_args in matches:
                # Strip keyword arg syntax like street_name='...'
                clean_args = re.sub(r'^\w+=', '', tool_args).strip().strip("'\"")
                observation = self._execute_tool(tool_name, clean_args)
                tool_calls.append({"tool": tool_name, "args": clean_args, "result": observation})

            if tool_calls:
                observations = "\n".join(f"[{tc['tool']}] → {tc['result']}" for tc in tool_calls)
                follow_up = (
                    "Provide a clear, data-backed answer to the officer. No further tool calls needed. "
                    "Do NOT include [TOOL_CALL:...] markers in your answer."
                )
                thinking = response_text
                response_text = await generate(
                    f"{prompt}\n\nTOOL OBSERVATIONS:\n{observations}\n\n{follow_up}",
                    max_tokens=400 if voice else 800,
                    temperature=0.3,
                    prefer="groq",
                )

        except Exception as e:
            print(f"Narrative agent error: {e}")
            return self._fallback_response(user_message, rag_sources, error=str(e)[:200])

        # Determine confidence from response
        confidence = 0.8
        if "[Confidence: HIGH]" in response_text or "high confidence" in response_text.lower():
            confidence = 0.9
        elif "[Confidence: LOW]" in response_text or "low confidence" in response_text.lower():
            confidence = 0.5

        # Clean response
        for tag in ("[Confidence: HIGH]", "[Confidence: MEDIUM]", "[Confidence: LOW]"):
            response_text = response_text.replace(tag, "")
        response_text = re.sub(TOOL_PATTERN, '', response_text)
        response_text = re.sub(r'\[TOOL_RESPONSE:[^\]]*\]', '', response_text)
        # The chat panel and text-to-speech show plain text: drop leftover Markdown markers
        response_text = re.sub(r'\*\*(.+?)\*\*', r'\1', response_text)
        response_text = re.sub(r'^\s*[*•-]\s+', '- ', response_text, flags=re.MULTILINE)
        response_text = re.sub(r'^#+\s*', '', response_text, flags=re.MULTILINE).strip()

        self._messages.append(ChatMessage(
            role="assistant",
            content=response_text,
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool_calls=tool_calls,
            thinking=thinking,
        ))

        return ChatResponse(
            response=response_text,
            thinking=thinking,
            tool_calls=tool_calls,
            confidence=confidence,
            rag_sources=rag_sources,
        )

    def _fallback_response(self, question: str, rag_sources: list[str], error: str = "") -> ChatResponse:
        """Rule-based answer from live tool data when the LLM is unavailable."""
        q = question.lower()
        tool_calls = []

        live_snapshot = self._get_live_snapshot()
        if "safe" in q or "open" in q or "lane" in q:
            if self._incident:
                for tool in ("get_speed", "get_risk_score"):
                    obs = self._execute_tool(tool, self._incident.street_name)
                    tool_calls.append({"tool": tool, "args": self._incident.street_name, "result": obs})
        elif "speed" in q:
            for seg in live_snapshot[:5]:
                obs = self._execute_tool("get_speed", seg.street_name)
                tool_calls.append({"tool": "get_speed", "args": seg.street_name, "result": obs})
        elif "diversion" in q or "route" in q:
            obs = self._execute_tool("check_diversion_status", "")
            tool_calls.append({"tool": "check_diversion_status", "args": "", "result": obs})
        elif "risk" in q or "danger" in q:
            top = sorted(self._get_live_risk_map(), key=lambda r: r.score, reverse=True)[:5]
            for r in top:
                obs = self._execute_tool("get_risk_score", r.street_name)
                tool_calls.append({"tool": "get_risk_score", "args": r.street_name, "result": obs})

        if tool_calls:
            response = "The AI assistant is unavailable, so here is the raw sensor data: " + "; ".join(
                tc["result"] for tc in tool_calls
            )
        else:
            response = (
                "The AI assistant is unavailable right now. I can still report speeds, risk scores "
                "and diversion status — try asking about one of those."
            )

        self._messages.append(ChatMessage(
            role="assistant",
            content=response,
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool_calls=tool_calls,
        ))

        return ChatResponse(
            response=response,
            tool_calls=tool_calls,
            confidence=0.5,
            rag_sources=rag_sources,
            source="fallback",
            error=error,
        )

    def get_messages(self) -> list[ChatMessage]:
        return self._messages

    def clear(self):
        """Forget the conversation and the resolved incident's context."""
        self._messages.clear()
        self._incident = None
        self._agent_output = None
        self._snapshot = []
        self._risk_map = []
