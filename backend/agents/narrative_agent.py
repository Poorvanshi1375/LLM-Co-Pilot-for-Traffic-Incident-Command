"""
Narrative Agent — Conversational TAO loop for officer Q&A.
TAO = Thought → Action (tool call) → Observation → Answer.
Uses Gemini 2.0 Flash with multi-turn memory.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from models.schemas import (
    SegmentSpeed, RiskEntry, IncidentDetection, AgentOutput,
    ChatMessage, ChatResponse,
)

from core.key_manager import get_gemini_key
from core.risk_scorer import compute_risk_map
from rag.retriever import retrieve_sops

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


SYSTEM_PROMPT = """You are TrafficMind, an AI co-pilot assisting traffic control officers in Brooklyn, New York.
You have access to real-time traffic sensor data and incident management tools.

PERSONA: Friendly, professional, conversational. Speak naturally like a knowledgeable colleague — not a document reader.
The officer stays in command — you handle the cognitive load and give them clear, actionable information.

AVAILABLE TOOLS (use by including [TOOL_CALL: tool_name(args)] in your thinking):
- get_speed(street_name) → current speed in mph and % of normal
- get_risk_score(street_name) → risk score 0-1 with breakdown
- check_diversion_status() → current diversion route status and compliance
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
- Be proactive: if data suggests something the officer should know, mention it.

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

    async def chat(self, user_message: str, voice: bool = False) -> ChatResponse:
        """Process officer's question through TAO loop."""
        self._messages.append(ChatMessage(
            role="user",
            content=user_message,
            timestamp=datetime.now().isoformat(),
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

        # Inject live traffic data so Gemini can answer any street question
        live_snapshot = self._get_live_snapshot()
        if live_snapshot:
            # Build a compact speed table for the LLM
            speed_lines = []
            for seg in live_snapshot:
                pct = round(seg.speed / seg.free_flow_speed * 100) if seg.free_flow_speed > 0 else 0
                speed_lines.append(f"  {seg.street_name}: {seg.speed:.0f} mph ({pct}% of {seg.free_flow_speed:.0f} mph free-flow), density {seg.density:.0f} veh/km")
            context_parts.append("LIVE SENSOR DATA (all monitored streets):\n" + "\n".join(speed_lines))

        if self._agent_output:
            if self._agent_output.signal_recommendations:
                sigs = [f"  - {s.intersection_name}: {s.recommended_phase} ({s.confidence:.0%})"
                       for s in self._agent_output.signal_recommendations[:3]]
                context_parts.append("SIGNAL RECOMMENDATIONS:\n" + "\n".join(sigs))
            if self._agent_output.diversion:
                d = self._agent_output.diversion
                context_parts.append(f"DIVERSION: via {' → '.join(d.route_street_names[:4])}, {d.risk_delta_pct}% safer")
            if self._agent_output.final_summary:
                context_parts.append(f"SUMMARY: {self._agent_output.final_summary}")

        context = "\n\n".join(context_parts)

        # Build conversation history for Gemini
        history_text = ""
        for msg in self._messages[-10:]:  # Last 10 messages
            role_label = "OFFICER" if msg.role == "user" else "TRAFFICMIND"
            history_text += f"\n{role_label}: {msg.content}"

        if not GEMINI_AVAILABLE:
            # Fallback: direct tool-based response
            return await self._fallback_response(user_message)

        # Try up to 3 different API keys on rate-limit errors
        last_error = None
        for _attempt in range(3):
            try:
                genai.configure(api_key=get_gemini_key())
                model = genai.GenerativeModel("gemini-2.5-flash")

                voice_instruction = """

⚠️ VOICE MODE — This answer will be spoken aloud via text-to-speech.
Be EXTREMELY concise: 1-2 short sentences max. Give only the key data point or action.
No greetings, no filler, no "Let me check" — just the essential answer.""" if voice else ""

                prompt = f"""{SYSTEM_PROMPT}

CURRENT SITUATION:
{context}

CONVERSATION HISTORY:
{history_text}{voice_instruction}

Respond to the officer's latest question naturally and conversationally. Use tools if needed by including [TOOL: tool_name("arg")] in your thinking.
Synthesize any reference knowledge into your own words — never copy it verbatim. Then provide the final answer."""

                response = await asyncio.to_thread(
                    model.generate_content,
                    prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=0.4,
                        max_output_tokens=256 if voice else 1024,
                    ),
                )

                response_text = response.text
                thinking = ""
                tool_calls = []

                # Check if response contains tool calls
                if "[TOOL:" in response_text or "[TOOL_CALL:" in response_text:
                    import re
                    tool_pattern = r'\[TOOL(?:_CALL)?:\s*(\w+)\(([^)]*)\)\]'
                    matches = re.findall(tool_pattern, response_text)

                    for tool_name, tool_args in matches:
                        # Strip keyword arg syntax like street_name='...'
                        clean_args = re.sub(r'^\w+=', '', tool_args).strip().strip("'\"")
                        observation = self._execute_tool(tool_name, clean_args)
                        tool_calls.append({
                            "tool": tool_name,
                            "args": clean_args,
                            "result": observation,
                        })

                    # If we found tool calls, re-query with observations
                    if tool_calls:
                        observations = "\n".join([f"[{tc['tool']}] → {tc['result']}" for tc in tool_calls])
                        follow_up = f"""Based on these tool observations:
{observations}

Provide a clear, data-backed answer to the officer. No further tool calls needed. Do NOT include [TOOL_CALL:...] markers in your answer."""

                        response2 = await asyncio.to_thread(
                            model.generate_content,
                            f"{prompt}\n\nTOOL OBSERVATIONS:\n{observations}\n\n{follow_up}",
                            generation_config=genai.GenerationConfig(
                                temperature=0.3,
                                max_output_tokens=800,
                            ),
                        )
                        thinking = response_text
                        response_text = response2.text

                # Determine confidence from response
                confidence = 0.8
                if "[Confidence: HIGH]" in response_text or "high confidence" in response_text.lower():
                    confidence = 0.9
                elif "[Confidence: LOW]" in response_text or "low confidence" in response_text.lower():
                    confidence = 0.5

                # Clean response
                import re as _re
                response_text = response_text.replace("[Confidence: HIGH]", "").replace("[Confidence: MEDIUM]", "").replace("[Confidence: LOW]", "")
                # Strip any remaining tool call markers from final text
                response_text = _re.sub(r'\[TOOL(?:_CALL)?:\s*\w+\([^)]*\)\]', '', response_text)
                response_text = _re.sub(r'\[TOOL_RESPONSE:[^\]]*\]', '', response_text)
                response_text = response_text.strip()

                self._messages.append(ChatMessage(
                    role="assistant",
                    content=response_text,
                    timestamp=datetime.now().isoformat(),
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

            except Exception as e:
                last_error = e
                print(f"Narrative agent error (attempt {_attempt+1}): {e}")
                continue  # Try next API key

        # All retries exhausted
        print(f"All Gemini attempts failed, using fallback")
        return await self._fallback_response(user_message)

    async def _fallback_response(self, question: str) -> ChatResponse:
        """Generate response using available data, with LLM layer if possible."""
        q = question.lower()
        tool_calls = []

        # RAG: retrieve relevant SOP documents for fallback too
        rag_docs = retrieve_sops(question, top_k=2)
        rag_sources: list[str] = []
        if rag_docs:
            for doc in rag_docs:
                if doc.startswith("[") and "]" in doc:
                    rag_sources.append(doc[1:doc.index("]")])

        # Gather relevant data via tools (uses live data now)
        live_snapshot = self._get_live_snapshot()
        if "safe" in q or "open" in q or "lane" in q:
            if self._incident:
                obs = self._execute_tool("get_speed", self._incident.street_name)
                tool_calls.append({"tool": "get_speed", "args": self._incident.street_name, "result": obs})
                risk_obs = self._execute_tool("get_risk_score", self._incident.street_name)
                tool_calls.append({"tool": "get_risk_score", "args": self._incident.street_name, "result": risk_obs})
        elif "speed" in q:
            for seg in live_snapshot[:5]:
                obs = self._execute_tool("get_speed", seg.street_name)
                tool_calls.append({"tool": "get_speed", "args": seg.street_name, "result": obs})
        elif "diversion" in q or "route" in q:
            obs = self._execute_tool("check_diversion_status", "")
            tool_calls.append({"tool": "check_diversion_status", "args": "", "result": obs})
        elif "risk" in q or "danger" in q:
            for r in self._risk_map[:5]:
                obs = self._execute_tool("get_risk_score", r.street_name)
                tool_calls.append({"tool": "get_risk_score", "args": r.street_name, "result": obs})

        # Build a mini-prompt with all gathered data and try Gemini
        data_text = "\n".join(f"- {tc['result']}" for tc in tool_calls) if tool_calls else "No specific tool data gathered."
        rag_text = "\n---\n".join(rag_docs) if rag_docs else "No reference documents available."

        context_parts = []
        if self._incident:
            context_parts.append(
                f"Active incident: {self._incident.severity.value} on {self._incident.street_name} — {self._incident.description}"
            )
        if self._agent_output and self._agent_output.final_summary:
            context_parts.append(f"Situation summary: {self._agent_output.final_summary}")

        fallback_prompt = f"""You are TrafficMind, a friendly and knowledgeable AI traffic co-pilot for Brooklyn officers.
Answer the officer's question naturally and conversationally. Use the data and reference knowledge below to inform your answer, but write in your OWN words — never copy reference text verbatim.

OFFICER'S QUESTION: {question}

SENSOR DATA:
{data_text}

SITUATION CONTEXT:
{chr(10).join(context_parts) if context_parts else "No active incident."}

REFERENCE KNOWLEDGE (paraphrase, do not quote):
{rag_text}

Write a helpful, concise, conversational response. 2-4 sentences."""

        # Try Gemini for natural language generation (retry with different keys)
        if GEMINI_AVAILABLE:
            for _fb_attempt in range(3):
                try:
                    genai.configure(api_key=get_gemini_key())
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    resp = await asyncio.to_thread(
                        model.generate_content,
                        fallback_prompt,
                        generation_config=genai.GenerationConfig(temperature=0.5, max_output_tokens=800),
                    )
                    response = resp.text.replace("[Confidence: HIGH]", "").replace("[Confidence: MEDIUM]", "").replace("[Confidence: LOW]", "").strip()
                    confidence = 0.75
                    break
                except Exception as fb_err:
                    print(f"Fallback Gemini attempt {_fb_attempt+1}: {fb_err}")
                    continue
            else:
                # All retries failed — true fallback
                if tool_calls:
                    response = "Here's what I found: " + "; ".join(tc["result"] for tc in tool_calls)
                else:
                    response = "I can help with speed data, risk scores, diversion status, and safety assessments. What would you like to know?"
                confidence = 0.5
        else:
            if tool_calls:
                response = "Here's what I found: " + "; ".join(tc["result"] for tc in tool_calls)
            else:
                response = "I can help with speed data, risk scores, diversion status, and safety assessments. What would you like to know?"
            confidence = 0.5

        self._messages.append(ChatMessage(
            role="assistant",
            content=response,
            timestamp=datetime.now().isoformat(),
            tool_calls=tool_calls,
        ))

        return ChatResponse(
            response=response,
            tool_calls=tool_calls,
            confidence=confidence,
            rag_sources=rag_sources,
        )

    def get_messages(self) -> list[ChatMessage]:
        return self._messages

    def clear(self):
        self._messages.clear()
