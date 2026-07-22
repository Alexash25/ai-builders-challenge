"""
CreatorLens — Pydantic data schemas.

These models define every data contract in the backend pipeline:
  AnalysisInput  — evidence package sent to IBM Granite
  AnalysisOutput — structured feedback returned by IBM Granite

All timestamps are floating-point seconds.
All IDs are stable strings (uuid4 generated at creation time).
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, field_validator, model_validator


# ---------------------------------------------------------------------------
# Input-side models
# ---------------------------------------------------------------------------

class ProjectBrief(BaseModel):
    """Creative brief supplied by the user on the project setup form."""

    goal: str
    platform: str
    audience: str
    tone: str
    target_length_seconds: float

    @field_validator("target_length_seconds")
    @classmethod
    def target_length_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("target_length_seconds must be positive")
        return v


class VideoMetadata(BaseModel):
    """Technical facts about the uploaded video, extracted by FFmpeg."""

    duration_seconds: float
    fps: float
    width: int
    height: int

    @field_validator("duration_seconds", "fps")
    @classmethod
    def positive_float(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Value must be positive")
        return v

    @field_validator("width", "height")
    @classmethod
    def positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Value must be positive")
        return v


class TranscriptSegment(BaseModel):
    """One timestamped spoken segment from the transcription."""

    id: str
    start: float
    end: float
    text: str

    @model_validator(mode="after")
    def start_before_end(self) -> "TranscriptSegment":
        if self.start < 0:
            raise ValueError("start must be >= 0")
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class Finding(BaseModel):
    """
    One objective measurement from the media pipeline.

    Raw numeric value lives in `value`.
    Human-readable sentence lives in `interpretation`.
    These are kept separate so the model receives both signal and context.
    """

    id: str
    category: Literal["audio", "visual", "pacing", "story", "accessibility"]
    start: float
    end: float
    metric: str
    value: Any
    interpretation: str

    @model_validator(mode="after")
    def start_before_end(self) -> "Finding":
        if self.start < 0:
            raise ValueError("start must be >= 0")
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class AnalysisInput(BaseModel):
    """
    Complete evidence package sent to IBM Granite.
    Assembles the project brief, video metadata, transcript, and media findings.
    """

    project: ProjectBrief
    video: VideoMetadata
    transcript_segments: list[TranscriptSegment]
    findings: list[Finding]


# ---------------------------------------------------------------------------
# Output-side models
# ---------------------------------------------------------------------------

class CategoryScores(BaseModel):
    """Five category scores returned by Granite, each 0–100."""

    story: int
    pacing: int
    audio: int
    visuals: int
    accessibility: int

    @field_validator("story", "pacing", "audio", "visuals", "accessibility")
    @classmethod
    def score_range(cls, v: int) -> int:
        if not (0 <= v <= 100):
            raise ValueError("Score must be between 0 and 100")
        return v


class TimelineFeedbackItem(BaseModel):
    """
    One piece of timestamped feedback.
    Rendered as a clickable marker on the frontend video player.
    `evidence_ids` must reference IDs from the AnalysisInput findings or transcript segments.
    `automatic_fix` is only non-null when the backend actually supports that edit operation.
    """

    id: str
    start: float
    end: float
    category: Literal["audio", "visual", "pacing", "story", "accessibility"]
    severity: Literal["low", "medium", "high"]
    evidence_ids: list[str]
    explanation: str
    suggestion: str
    automatic_fix: Optional[Literal["silence_removal"]] = None

    @model_validator(mode="after")
    def start_before_end(self) -> "TimelineFeedbackItem":
        if self.start < 0:
            raise ValueError("start must be >= 0")
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class RecommendedEdit(BaseModel):
    """
    One entry in the prioritized editing plan panel.
    `automatic_fix_eligible` = True means the backend can execute this edit.
    `priority` 1 is highest.
    """

    id: str
    label: str
    description: str
    edit_type: str
    automatic_fix_eligible: bool
    priority: int

    @field_validator("priority")
    @classmethod
    def priority_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("priority must be >= 1")
        return v


class AnalysisOutput(BaseModel):
    """
    Complete response from IBM Granite.
    Everything the frontend needs to render the results view.
    """

    summary: str
    scores: CategoryScores
    timeline_feedback: list[TimelineFeedbackItem]
    recommended_edits: list[RecommendedEdit]
    revised_script: str
