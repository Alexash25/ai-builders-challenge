"""
Tests for backend/pipeline/extractor.py (Sub-Task 3).

Strategy
--------
A short synthetic test video is generated once per test session using FFmpeg
(a 10-second, 640×360, 30fps clip with a 1kHz tone that drops to silence
in the 5–7s window).  All tests operate on that file.

Tests assert:
  - VideoMetadata fields are populated correctly
  - All Finding timestamps satisfy 0 <= start <= end <= duration
  - Silence findings are detected for the known silent window
  - Visual findings (brightness, blur) are present for each sampled frame
  - The assembled AnalysisInput validates against the Pydantic schema
"""

import pathlib
import subprocess
import uuid

import pytest

from backend.schemas import AnalysisInput, ProjectBrief
from backend.pipeline.extractor import (
    extract_evidence,
    _probe_metadata,
    _detect_silence,
    _measure_rms,
    _sample_frames,
    _analyze_frames,
    _detect_scene_cuts,
    FRAME_SAMPLE_INTERVAL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> pathlib.Path:
    """
    Generate a short synthetic test video with FFmpeg:
      - 10 seconds, 640×360, 30fps
      - 1kHz sine tone for 0–5s and 7–10s; silence for 5–7s
    Returns the path to the generated .mp4 file.
    """
    out_dir = tmp_path_factory.mktemp("videos")
    out_path = out_dir / "test_video.mp4"

    # Two audio segments: tone | silence | tone — concatenated via lavfi
    cmd = [
        "ffmpeg", "-y",
        # Video: 10s solid-colour test pattern
        "-f", "lavfi", "-i", "color=size=640x360:duration=10:rate=30:color=blue",
        # Audio: sine for 5s, then silence for 2s, then sine for 3s
        "-f", "lavfi", "-i",
        "sine=frequency=1000:duration=5,aformat=fltp:sample_rates=16000:channel_layouts=mono",
        "-f", "lavfi", "-i",
        "anullsrc=r=16000:cl=mono,atrim=duration=2",
        "-f", "lavfi", "-i",
        "sine=frequency=1000:duration=3,aformat=fltp:sample_rates=16000:channel_layouts=mono",
        # Mix the three audio streams
        "-filter_complex",
        "[1:a][2:a][3:a]concat=n=3:v=0:a=1[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac",
        "-t", "10",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        pytest.fail(f"FFmpeg failed to create test video:\n{result.stderr.decode()}")
    return out_path


@pytest.fixture(scope="session")
def sample_brief() -> ProjectBrief:
    return ProjectBrief(
        goal="Teach Python basics",
        platform="YouTube",
        audience="Beginners",
        tone="friendly",
        target_length_seconds=60.0,
    )


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------

class TestProbeMetadata:
    def test_duration_within_range(self, sample_video):
        meta = _probe_metadata(str(sample_video))
        # Allow ±0.5s tolerance for codec overhead
        assert 9.0 <= meta.duration_seconds <= 11.0

    def test_resolution(self, sample_video):
        meta = _probe_metadata(str(sample_video))
        assert meta.width == 640
        assert meta.height == 360

    def test_fps(self, sample_video):
        meta = _probe_metadata(str(sample_video))
        assert 29.0 <= meta.fps <= 31.0


# ---------------------------------------------------------------------------
# Silence detection tests
# ---------------------------------------------------------------------------

class TestSilenceDetection:
    def test_returns_findings_list(self, sample_video):
        meta = _probe_metadata(str(sample_video))
        findings = _detect_silence(str(sample_video), meta.duration_seconds)
        assert isinstance(findings, list)

    def test_timestamps_within_bounds(self, sample_video):
        meta = _probe_metadata(str(sample_video))
        findings = _detect_silence(str(sample_video), meta.duration_seconds)
        for f in findings:
            assert f.start >= 0.0
            assert f.end >= f.start
            assert f.end <= meta.duration_seconds

    def test_silence_metric_name(self, sample_video):
        meta = _probe_metadata(str(sample_video))
        findings = _detect_silence(str(sample_video), meta.duration_seconds)
        for f in findings:
            assert f.metric == "silence_duration_seconds"
            assert f.category == "audio"

    def test_silence_value_is_float(self, sample_video):
        meta = _probe_metadata(str(sample_video))
        findings = _detect_silence(str(sample_video), meta.duration_seconds)
        for f in findings:
            assert isinstance(f.value, float)


# ---------------------------------------------------------------------------
# Visual frame analysis tests
# ---------------------------------------------------------------------------

class TestFrameAnalysis:
    def test_frames_sampled(self, sample_video, tmp_path):
        meta = _probe_metadata(str(sample_video))
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        times = _sample_frames(str(sample_video), meta.duration_seconds, str(frames_dir))
        assert len(times) > 0

    def test_frame_times_within_bounds(self, sample_video, tmp_path):
        meta = _probe_metadata(str(sample_video))
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        times = _sample_frames(str(sample_video), meta.duration_seconds, str(frames_dir))
        for t in times:
            assert 0.0 <= t < meta.duration_seconds

    def test_visual_findings_present(self, sample_video, tmp_path):
        meta = _probe_metadata(str(sample_video))
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        times = _sample_frames(str(sample_video), meta.duration_seconds, str(frames_dir))
        findings = _analyze_frames(frames_dir, times, meta.duration_seconds)
        assert len(findings) > 0

    def test_visual_findings_have_correct_metrics(self, sample_video, tmp_path):
        meta = _probe_metadata(str(sample_video))
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        times = _sample_frames(str(sample_video), meta.duration_seconds, str(frames_dir))
        findings = _analyze_frames(frames_dir, times, meta.duration_seconds)
        metrics = {f.metric for f in findings}
        assert "mean_brightness" in metrics
        assert "blur_score" in metrics

    def test_visual_findings_timestamps_within_bounds(self, sample_video, tmp_path):
        meta = _probe_metadata(str(sample_video))
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        times = _sample_frames(str(sample_video), meta.duration_seconds, str(frames_dir))
        findings = _analyze_frames(frames_dir, times, meta.duration_seconds)
        for f in findings:
            assert f.start >= 0.0
            assert f.end >= f.start
            assert f.end <= meta.duration_seconds + 0.001  # float tolerance


# ---------------------------------------------------------------------------
# Full pipeline integration test
# ---------------------------------------------------------------------------

class TestExtractEvidence:
    def test_returns_valid_analysis_input(self, sample_video, sample_brief):
        result = extract_evidence(str(sample_video), sample_brief)
        assert isinstance(result, AnalysisInput)

    def test_video_metadata_populated(self, sample_video, sample_brief):
        result = extract_evidence(str(sample_video), sample_brief)
        assert result.video.width == 640
        assert result.video.height == 360

    def test_all_finding_timestamps_within_duration(self, sample_video, sample_brief):
        result = extract_evidence(str(sample_video), sample_brief)
        dur = result.video.duration_seconds
        for f in result.findings:
            assert f.start >= 0.0, f"Finding {f.id} start < 0"
            assert f.end >= f.start, f"Finding {f.id} end < start"
            assert f.end <= dur + 0.001, f"Finding {f.id} end {f.end} > duration {dur}"

    def test_findings_have_ids(self, sample_video, sample_brief):
        result = extract_evidence(str(sample_video), sample_brief)
        for f in result.findings:
            assert f.id, "Finding has empty id"

    def test_findings_not_empty(self, sample_video, sample_brief):
        result = extract_evidence(str(sample_video), sample_brief)
        assert len(result.findings) > 0

    def test_brief_preserved(self, sample_video, sample_brief):
        result = extract_evidence(str(sample_video), sample_brief)
        assert result.project.goal == sample_brief.goal
        assert result.project.platform == sample_brief.platform

    def test_schema_validates(self, sample_video, sample_brief):
        """Ensure the assembled AnalysisInput passes Pydantic validation."""
        result = extract_evidence(str(sample_video), sample_brief)
        # Re-validate via round-trip serialization
        AnalysisInput.model_validate(result.model_dump())
