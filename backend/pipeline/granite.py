"""
IBM Granite Integration Layer

Public Interface:

analyze(input: AnalysisInput) -> AnalysisOutput

Mock mode returns the example fixture without making an API call.
Real mode calls watsonx.ai and validates the structured JSON.
"""

import json
import logging
import pathlib
import time

from backend.config import settings
from backend.schemas import AnalysisInput, AnalysisOutput, CategoryScores

log = logging.getLogger(__name__)

_FIXTURE_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "docs"
    / "example_analysis_output.json"
)

_SAFE_FALLBACK = AnalysisOutput(
    summary="Analysis partially failed. Please review manually.",
    scores=CategoryScores(
        story=0,
        pacing=0,
        audio=0,
        visuals=0,
        accessibility=0,
    ),
    timeline_feedback=[],
    recommended_edits=[],
    revised_script="",
)


def analyze(analysis_input: AnalysisInput) -> AnalysisOutput:
    """Run Granite analysis on the evidence package."""
    if settings.use_mock_ai:
        log.info("Granite mock mode enabled - returning fixture")
        raw = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        return AnalysisOutput.model_validate(raw)

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(analysis_input)
    return _call_granite(system_prompt, user_prompt, analysis_input)


def _build_system_prompt() -> str:
    """Return the instructions that control Granite's behavior."""
    return (
        "You are a collaborative AI creative director. "
        "Analyze the provided video evidence and return ONLY valid JSON "
        "matching the AnalysisOutput schema. "
        "Do not invent timestamps, metrics, or findings that are not present "
        "in the evidence. "
        "Every timeline_feedback item must cite at least one finding ID "
        "from the evidence package. "
        "Return JSON only—no prose, markdown, or code fences."
    )


def _build_user_prompt(inp: AnalysisInput) -> str:
    """Convert the structured evidence package into a readable prompt."""
    brief = inp.project
    lines = [
        "=== PROJECT BRIEF ===",
        f"Goal: {brief.goal}",
        f"Platform: {brief.platform}",
        f"Audience: {brief.audience}",
        f"Tone: {brief.tone}",
        f"Target length: {brief.target_length_seconds}s",
        "",
        "=== VIDEO METADATA ===",
        (
            f"Duration: {inp.video.duration_seconds:.1f}s | "
            f"Resolution: {inp.video.width}x{inp.video.height} | "
            f"FPS: {inp.video.fps:.1f}"
        ),
        "",
        "=== FINDINGS SUMMARY ===",
    ]

    for finding in inp.findings:
        lines.append(
            f"[{finding.id}] "
            f"{finding.category} | "
            f"{finding.metric} | "
            f"{finding.start:.1f}s-{finding.end:.1f}s | "
            f"value={finding.value} | "
            f"{finding.interpretation}"
        )

    lines.extend(["", "=== TRANSCRIPT ==="])

    for segment in inp.transcript_segments:
        lines.append(
            f"[{segment.id}] "
            f"{segment.start:.1f}s-{segment.end:.1f}s: "
            f"{segment.text}"
        )

    lines.extend(["", "Return a single JSON object matching the AnalysisOutput schema."])
    return "\n".join(lines)


def _call_granite(
    system_prompt: str,
    user_prompt: str,
    inp: AnalysisInput,
) -> AnalysisOutput:
    """Call watsonx.ai and validate the response. One retry on bad JSON."""
    try:
        from ibm_watsonx_ai import Credentials
        from ibm_watsonx_ai.foundation_models import ModelInference
    except ImportError:
        log.error("ibm-watsonx-ai not installed. Set USE_MOCK_AI=true or pip install ibm-watsonx-ai")
        return _SAFE_FALLBACK

    credentials = Credentials(
        url=settings.watsonx_url,
        api_key=settings.watsonx_api_key,
    )
    model = ModelInference(
        model_id=settings.granite_model_id,
        credentials=credentials,
        project_id=settings.watsonx_project_id,
        params={"max_new_tokens": 2048, "temperature": 0.1},
    )

    prompt = f"<|system|>\n{system_prompt}\n<|user|>\n{user_prompt}\n<|assistant|>\n"

    t0 = time.time()
    response = str(model.generate_text(prompt=prompt))
    latency = round(time.time() - t0, 2)
    log.info("Granite response latency=%.2fs", latency)

    output, error = _parse_and_validate(response, inp)
    if output:
        return output

    # Retry once with the validation error appended to the prompt
    log.warning("Granite first attempt invalid — retrying. error=%s", error)
    retry_prompt = (
        prompt
        + response
        + f"\n\nThe above response failed validation: {error}\n"
        + "Fix the JSON and return ONLY the corrected object.\n<|assistant|>\n"
    )
    response2 = str(model.generate_text(prompt=retry_prompt))
    output2, error2 = _parse_and_validate(response2, inp)
    if output2:
        return output2

    log.error("Granite retry also failed. error=%s raw=%s", error2, response2[:500])
    return _SAFE_FALLBACK


def _parse_and_validate(raw: str, inp: AnalysisInput):
    """Extract and validate JSON from model output. Returns (output, error)."""
    from pydantic import ValidationError

    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"JSON decode error: {exc}"

    try:
        output = AnalysisOutput.model_validate(data)
    except ValidationError as exc:
        return None, str(exc)

    # Clamp any feedback items that exceed the video duration
    duration = inp.video.duration_seconds
    output = output.model_copy(update={
        "timeline_feedback": [
            item for item in output.timeline_feedback
            if item.start <= duration and item.end <= duration
        ]
    })
    return output, None
