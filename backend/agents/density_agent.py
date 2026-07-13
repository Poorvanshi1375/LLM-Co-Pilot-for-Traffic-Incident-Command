"""
Density Agent — Vehicle density estimation.
Simulated mode: Fundamental flow equation (density = flow / speed).
Vision mode: Gemini 2.0 Flash for camera frame analysis.
"""
from __future__ import annotations

import asyncio
import json
import os
import base64
from models.schemas import SegmentSpeed, DensityData

from core.key_manager import get_gemini_key

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


def compute_density_simulated(snapshot: list[SegmentSpeed]) -> DensityData:
    """Compute vehicle density from speed feed using fundamental flow equation."""
    densities = {}
    total_vehicles = 0

    for seg in snapshot:
        # Fundamental diagram: density = flow / speed
        # Estimate flow from time-of-day and road characteristics
        density = seg.density if seg.density > 0 else max(5, min(120, 60 / max(seg.speed, 1)))
        densities[seg.street_name] = round(density, 1)

        # Rough vehicle count: density * segment_length_km * lanes
        estimated_vehicles = int(density * 0.3 * 2)  # ~300m avg segment, 2 lanes
        total_vehicles += estimated_vehicles

    # Overall congestion level
    avg_density = sum(densities.values()) / len(densities) if densities else 20
    if avg_density > 80:
        congestion = "GRIDLOCK"
    elif avg_density > 60:
        congestion = "HEAVY"
    elif avg_density > 40:
        congestion = "MODERATE"
    elif avg_density > 20:
        congestion = "LIGHT"
    else:
        congestion = "FREE_FLOW"

    return DensityData(
        segment_densities=densities,
        congestion_level=congestion,
        estimated_vehicles=total_vehicles,
        vision_analysis="Simulated density from traffic flow model",
    )


async def analyze_camera_frame(image_base64: str) -> DensityData:
    """Use Gemini Vision to analyze a camera frame for vehicle density."""
    if not GEMINI_AVAILABLE:
        return DensityData(
            congestion_level="UNKNOWN",
            vision_analysis="Gemini Vision not available",
        )

    try:
        genai.configure(api_key=get_gemini_key())
        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = """Analyze this traffic camera image. Provide:
1. Estimated number of vehicles visible
2. Congestion level (FREE_FLOW / LIGHT / MODERATE / HEAVY / GRIDLOCK)
3. Any incidents visible (collision, breakdown, debris)
4. Lane occupancy estimate

Return JSON:
{
  "estimated_vehicles": 15,
  "congestion_level": "MODERATE",
  "incidents_visible": "Two-vehicle collision in right lane",
  "lane_occupancy_pct": 65
}"""

        import PIL.Image
        import io
        image_data = base64.b64decode(image_base64)
        image = PIL.Image.open(io.BytesIO(image_data))

        response = await asyncio.to_thread(model.generate_content, [prompt, image])
        text = response.text

        # Try to parse JSON from response
        try:
            # Find JSON in response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
            else:
                parsed = {}
        except json.JSONDecodeError:
            parsed = {}

        return DensityData(
            congestion_level=parsed.get("congestion_level", "UNKNOWN"),
            estimated_vehicles=parsed.get("estimated_vehicles", 0),
            vision_analysis=parsed.get("incidents_visible", text[:200]),
        )

    except Exception as e:
        print(f"Vision analysis error: {e}")
        return DensityData(
            congestion_level="UNKNOWN",
            vision_analysis=f"Vision analysis failed: {str(e)[:100]}",
        )


async def run_density_agent(
    snapshot: list[SegmentSpeed],
    camera_frame_b64: str | None = None,
) -> DensityData:
    """Run density estimation — simulated + optional vision."""
    simulated = compute_density_simulated(snapshot)

    if camera_frame_b64:
        vision_result = await analyze_camera_frame(camera_frame_b64)
        # Merge vision data with simulated
        simulated.vision_analysis = vision_result.vision_analysis
        if vision_result.estimated_vehicles > 0:
            simulated.estimated_vehicles = vision_result.estimated_vehicles
        if vision_result.congestion_level != "UNKNOWN":
            simulated.congestion_level = vision_result.congestion_level

    return simulated
