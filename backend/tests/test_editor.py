"""
Tests for backend/pipeline/editor.py (Sub-Task 6).

Strategy
--------
A short synthetic 10-second video with a known 2-second silence gap (5s–7s)
is generated once per session using FFmpeg. Tests assert:
  - The output file exists and is a valid video
  - The output is shorter than the input (silence was removed)
  - Passing no silence findings raises ValueError
  - _invert_silences produces correct keep-segments
"""

import pathlib
import subprocess

import pytest

from backend.schemas import Finding
from backend.pipeline.editor import apply_silence_removal, _invert_silences


# ---------------------------------------------------------------------------
# Session fixture — same synthetic video as test_extractor.py
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> pathlib.Path:
    out_dir = tmp_path_factory.mktemp("editor_videos")
    out_path = out_dir / "test_video.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=size=640x360:duration=10:rate=30:color=blue",
        "-f", "lavfi", "-i",
        "sine=frequency=1000:duration=5,aformat=fltp:sample_rates=16000:channel_layouts=mono",
        "-f", "lavfi", "-i",
        "anullsrc=r=16000:cl=mono,atrim=duration=2",
        "-f", "lavfi", "-i",
        "sine=frequency=1000:duration=3,aformat=fltp:sample_rates=16000:channel_layouts=mono",
        "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-t", "10",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        pytest.fail(f"FFmpeg failed:\n{result.stderr.decode()}")
    return out_path


@pytest.fixture
def silence_finding() -> Finding:
    """A single silence finding matching the 5s–7s gap in the test video."""
    return Finding(
        id="test-silence-01",
        category="audio",
        start=5.0,
        end=7.0,
        metric="silence_duration_seconds",
        value=2.0,
        interpretation="2s of silence at 5–7s.",
    )


# ---------------------------------------------------------------------------
# _invert_silences unit tests
# ---------------------------------------------------------------------------

class TestInvertSilences:
    def test_single_gap_in_middle(self, silence_finding):
        keep = _invert_silences([silence_finding], duration=10.0)
        assert len(keep) == 2
        assert keep[0] == (0.0, 5.0)
        assert keep[1] == (7.0, 10.0)

    def test_gap_at_start(self):
        f = Finding(
            id="s1", category="audio", start=0.0, end=3.0,
            metric="silence_duration_seconds", value=3.0,
            interpretation="silence at start",
        )
        keep = _invert_silences([f], duration=10.0)
        assert keep[0][0] == 3.0

    def test_gap_at_end(self):
        f = Finding(
            id="s2", category="audio", start=8.0, end=10.0,
            metric="silence_duration_seconds", value=2.0,
            interpretation="silence at end",
        )
        keep = _invert_silences([f], duration=10.0)
        assert keep[-1][1] == 8.0

    def test_no_gaps_returns_full_duration(self):
        keep = _invert_silences([], duration=10.0)
        assert keep == [(0.0, 10.0)]


# ---------------------------------------------------------------------------
# apply_silence_removal integration tests
# ---------------------------------------------------------------------------

class TestApplySilenceRemoval:
    def test_output_file_created(self, sample_video, silence_finding):
        out = apply_silence_removal(str(sample_video), [silence_finding])
        assert pathlib.Path(out).exists()

    def test_output_is_shorter_than_input(self, sample_video, silence_finding):
        import ffmpeg
        out = apply_silence_removal(str(sample_video), [silence_finding])
        input_dur = float(ffmpeg.probe(str(sample_video))["format"]["duration"])
        output_dur = float(ffmpeg.probe(out)["format"]["duration"])
        assert output_dur < input_dur

    def test_output_is_valid_video(self, sample_video, silence_finding):
        import ffmpeg
        out = apply_silence_removal(str(sample_video), [silence_finding])
        probe = ffmpeg.probe(out)
        video_streams = [s for s in probe["streams"] if s["codec_type"] == "video"]
        assert len(video_streams) == 1

    def test_no_findings_raises(self, sample_video):
        with pytest.raises(ValueError, match="No silence findings"):
            apply_silence_removal(str(sample_video), [])
