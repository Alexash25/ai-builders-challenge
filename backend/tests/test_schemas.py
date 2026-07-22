"""
Tests for backend/schemas.py

Covers:
  - Valid example fixtures load without error
  - Field validators reject out-of-range scores
  - Timestamp validators reject invalid ranges
  - Finding and TranscriptSegment enforce start <= end
"""

import json
import pathlib
import pytest
from pydantic import ValidationError

from backend.schemas import (
    AnalysisInput,
    AnalysisOutput,
    CategoryScores,
    Finding,
    ProjectBrief,
    RecommendedEdit,
    TimelineFeedbackItem,
    TranscriptSegment,
    VideoMetadata,
)

DOCS = pathlib.Path(__file__).parent.parent.parent / "docs"


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

def test_example_analysis_input_loads():
    """The hand-authored input fixture must be schema-valid."""
    data = json.loads((DOCS / "example_analysis_input.json").read_text())
    obj = AnalysisInput.model_validate(data)
    assert len(obj.transcript_segments) > 0
    assert len(obj.findings) > 0
    assert obj.video.duration_seconds > 0


def test_example_analysis_output_loads():
    """The hand-authored output fixture must be schema-valid."""
    data = json.loads((DOCS / "example_analysis_output.json").read_text())
    obj = AnalysisOutput.model_validate(data)
    assert obj.summary
    assert len(obj.timeline_feedback) > 0
    assert len(obj.recommended_edits) > 0
    assert obj.revised_script


# ---------------------------------------------------------------------------
# CategoryScores validation
# ---------------------------------------------------------------------------

def test_scores_reject_above_100():
    with pytest.raises(ValidationError):
        CategoryScores(story=101, pacing=50, audio=50, visuals=50, accessibility=50)


def test_scores_reject_below_0():
    with pytest.raises(ValidationError):
        CategoryScores(story=50, pacing=-1, audio=50, visuals=50, accessibility=50)


def test_scores_accept_boundary_values():
    s = CategoryScores(story=0, pacing=100, audio=50, visuals=0, accessibility=100)
    assert s.story == 0
    assert s.pacing == 100


# ---------------------------------------------------------------------------
# Timestamp validation — TranscriptSegment
# ---------------------------------------------------------------------------

def test_transcript_segment_rejects_end_before_start():
    with pytest.raises(ValidationError):
        TranscriptSegment(id="s1", start=10.0, end=5.0, text="bad")


def test_transcript_segment_rejects_negative_start():
    with pytest.raises(ValidationError):
        TranscriptSegment(id="s1", start=-1.0, end=5.0, text="bad")


def test_transcript_segment_accepts_equal_start_end():
    seg = TranscriptSegment(id="s1", start=5.0, end=5.0, text="point in time")
    assert seg.start == seg.end


# ---------------------------------------------------------------------------
# Timestamp validation — Finding
# ---------------------------------------------------------------------------

def test_finding_rejects_end_before_start():
    with pytest.raises(ValidationError):
        Finding(
            id="f1", category="audio", start=20.0, end=10.0,
            metric="silence_duration_seconds", value=3.5,
            interpretation="bad"
        )


def test_finding_rejects_negative_start():
    with pytest.raises(ValidationError):
        Finding(
            id="f1", category="audio", start=-5.0, end=10.0,
            metric="silence_duration_seconds", value=3.5,
            interpretation="bad"
        )


# ---------------------------------------------------------------------------
# TimelineFeedbackItem validation
# ---------------------------------------------------------------------------

def test_feedback_item_rejects_invalid_severity():
    with pytest.raises(ValidationError):
        TimelineFeedbackItem(
            id="fb1", start=0.0, end=5.0, category="audio",
            severity="critical",  # not a valid literal
            evidence_ids=["find_001"],
            explanation="test", suggestion="test"
        )


def test_feedback_item_rejects_invalid_category():
    with pytest.raises(ValidationError):
        TimelineFeedbackItem(
            id="fb1", start=0.0, end=5.0, category="emotion",  # not valid
            severity="high", evidence_ids=[], explanation="x", suggestion="x"
        )


def test_feedback_item_automatic_fix_defaults_none():
    item = TimelineFeedbackItem(
        id="fb1", start=0.0, end=5.0, category="audio",
        severity="low", evidence_ids=[],
        explanation="test", suggestion="test"
    )
    assert item.automatic_fix is None


# ---------------------------------------------------------------------------
# RecommendedEdit validation
# ---------------------------------------------------------------------------

def test_recommended_edit_rejects_zero_priority():
    with pytest.raises(ValidationError):
        RecommendedEdit(
            id="e1", label="test", description="test",
            edit_type="silence_removal",
            automatic_fix_eligible=True,
            priority=0
        )


# ---------------------------------------------------------------------------
# VideoMetadata validation
# ---------------------------------------------------------------------------

def test_video_metadata_rejects_zero_duration():
    with pytest.raises(ValidationError):
        VideoMetadata(duration_seconds=0.0, fps=30.0, width=1920, height=1080)


def test_project_brief_rejects_zero_target_length():
    with pytest.raises(ValidationError):
        ProjectBrief(
            goal="test", platform="YouTube", audience="everyone",
            tone="casual", target_length_seconds=0.0
        )
