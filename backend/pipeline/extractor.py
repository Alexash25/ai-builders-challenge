"""
CreatorLens — Media Evidence Extraction Pipeline (Sub-Task 3).

Public interface
----------------
    extract_evidence(video_path: str, brief: ProjectBrief) -> AnalysisInput

Extracts objective signals from a video file using FFmpeg and OpenCV and
assembles them into a validated AnalysisInput ready to be sent to Granite.

Signal sources
--------------
  FFprobe  — duration, fps, width, height
  FFmpeg   — audio WAV extraction, silence detection, frame sampling
  wave/struct — per-window RMS volume in dBFS
  OpenCV   — per-frame brightness and blur (Laplacian variance)
  frame diff — scene-cut detection from consecutive sampled frames

Transcription
-------------
  Mock mode (USE_MOCK_AI=true): loads docs/example_analysis_input.json and
  returns its transcript_segments list unchanged.
  Real mode: placeholder list — wired up in Sub-Task 4.
"""

import json
import logging
import math
import struct
import tempfile
import uuid
import wave
from pathlib import Path
from typing import Optional

import cv2
import ffmpeg

from backend.config import settings
from backend.schemas import AnalysisInput, Finding, ProjectBrief, TranscriptSegment, VideoMetadata

log = logging.getLogger("creatorlens.extractor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRAME_SAMPLE_INTERVAL = 5.0        # seconds between sampled frames
SCENE_CUT_THRESHOLD = 30.0         # mean pixel-value difference to flag a cut
SILENCE_NOISE_FLOOR = -40.0        # dBFS below which audio is considered silent
SILENCE_MIN_DURATION = 0.5         # minimum silence gap length to report
RMS_WINDOW_SECONDS = 5.0           # RMS averaging window in seconds

_FIXTURE_PATH = Path(__file__).parent.parent.parent / "docs" / "example_analysis_input.json"
_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_evidence(video_path: str, brief: ProjectBrief) -> AnalysisInput:
    """
    Extract all media signals from *video_path* and return a validated
    AnalysisInput that packages everything the Granite layer needs.
    """
    video_path = str(video_path)
    log.info("extractor started path=%s", video_path)

    metadata = _probe_metadata(video_path)
    duration = metadata.duration_seconds

    findings: list[Finding] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 1. Extract audio track to WAV
        wav_path = tmp / "audio.wav"
        _extract_audio(video_path, str(wav_path))

        # 2. Silence detection
        silence_findings = _detect_silence(video_path, duration)
        findings.extend(silence_findings)

        # 3. RMS volume per window
        if wav_path.exists():
            rms_findings = _measure_rms(str(wav_path), duration)
            findings.extend(rms_findings)

        # 4. Sample frames every FRAME_SAMPLE_INTERVAL seconds
        frames_dir = tmp / "frames"
        frames_dir.mkdir()
        frame_times = _sample_frames(video_path, duration, str(frames_dir))

        # 5. Per-frame visual analysis (brightness + blur)
        visual_findings = _analyze_frames(frames_dir, frame_times, duration)
        findings.extend(visual_findings)

        # 6. Scene cut detection from consecutive frames
        scene_findings = _detect_scene_cuts(frames_dir, frame_times, duration)
        findings.extend(scene_findings)

    # 7. Transcript segments
    transcript = _get_transcript(duration)

    analysis_input = AnalysisInput(
        project=brief,
        video=metadata,
        transcript_segments=transcript,
        findings=findings,
    )
    log.info(
        "extractor complete findings=%d transcript_segments=%d",
        len(findings),
        len(transcript),
    )
    return analysis_input


# ---------------------------------------------------------------------------
# FFprobe metadata
# ---------------------------------------------------------------------------

def _probe_metadata(video_path: str) -> VideoMetadata:
    """Use ffprobe to read basic video metadata."""
    probe = ffmpeg.probe(video_path)
    video_stream = next(
        (s for s in probe["streams"] if s.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise ValueError(f"No video stream found in {video_path}")

    duration = float(probe["format"].get("duration", 0))
    fps_raw = video_stream.get("r_frame_rate", "25/1")
    num, den = (int(x) for x in fps_raw.split("/"))
    fps = num / den if den else 25.0

    return VideoMetadata(
        duration_seconds=duration,
        fps=fps,
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
    )


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------

def _extract_audio(video_path: str, wav_out: str) -> None:
    """Extract the audio track to a mono 16kHz WAV file."""
    try:
        (
            ffmpeg
            .input(video_path)
            .output(wav_out, ac=1, ar=16000, acodec="pcm_s16le", loglevel="quiet")
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:
        log.warning("audio extraction failed: %s", exc.stderr.decode(errors="replace"))


# ---------------------------------------------------------------------------
# Silence detection
# ---------------------------------------------------------------------------

def _detect_silence(video_path: str, duration: float) -> list[Finding]:
    """Run FFmpeg silencedetect filter; return one Finding per gap."""
    try:
        _, stderr = (
            ffmpeg
            .input(video_path)
            .audio
            .filter("silencedetect", noise=f"{SILENCE_NOISE_FLOOR}dB", duration=SILENCE_MIN_DURATION)
            .output("pipe:", format="null", loglevel="quiet")
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:
        log.warning("silence detection failed: %s", exc.stderr.decode(errors="replace"))
        return []

    stderr_text = stderr.decode(errors="replace")
    findings: list[Finding] = []
    starts: dict[str, float] = {}

    for line in stderr_text.splitlines():
        if "silence_start" in line:
            try:
                val = float(line.split("silence_start:")[1].split()[0])
                starts["last"] = max(0.0, val)
            except (IndexError, ValueError):
                pass
        elif "silence_end" in line and "last" in starts:
            try:
                parts = line.split("|")
                end_val = float(parts[0].split("silence_end:")[1].split()[0])
                dur_val = float(parts[1].split("silence_duration:")[1].split()[0])
                start_val = starts.pop("last")
                end_clamped = min(end_val, duration)
                findings.append(Finding(
                    id=str(uuid.uuid4()),
                    category="audio",
                    start=start_val,
                    end=end_clamped,
                    metric="silence_duration_seconds",
                    value=round(dur_val, 3),
                    interpretation=(
                        f"{dur_val:.1f}s of silence detected between "
                        f"{start_val:.1f}s and {end_clamped:.1f}s."
                    ),
                ))
            except (IndexError, ValueError):
                pass

    return findings


# ---------------------------------------------------------------------------
# RMS volume
# ---------------------------------------------------------------------------

def _measure_rms(wav_path: str, duration: float) -> list[Finding]:
    """Measure RMS amplitude per RMS_WINDOW_SECONDS window from a WAV file."""
    findings: list[Finding] = []
    try:
        with wave.open(wav_path, "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()

            if sampwidth != 2:
                log.warning("Unexpected sample width %d; skipping RMS", sampwidth)
                return findings

            window_frames = int(framerate * RMS_WINDOW_SECONDS)
            t = 0.0
            while True:
                raw = wf.readframes(window_frames)
                if not raw:
                    break
                n_samples = len(raw) // 2
                samples = struct.unpack(f"<{n_samples}h", raw)
                if n_samples == 0:
                    t += RMS_WINDOW_SECONDS
                    continue
                rms = math.sqrt(sum(s * s for s in samples) / n_samples)
                db = 20 * math.log10(rms / 32768.0) if rms > 0 else -96.0
                db = round(db, 2)
                end_t = min(t + RMS_WINDOW_SECONDS, duration)
                level_label = (
                    "very quiet" if db < -40 else
                    "quiet" if db < -25 else
                    "normal" if db < -10 else
                    "loud"
                )
                findings.append(Finding(
                    id=str(uuid.uuid4()),
                    category="audio",
                    start=round(t, 3),
                    end=round(end_t, 3),
                    metric="rms_volume_db",
                    value=db,
                    interpretation=(
                        f"Audio level is {level_label} ({db} dBFS) "
                        f"between {t:.1f}s and {end_t:.1f}s."
                    ),
                ))
                t += RMS_WINDOW_SECONDS
    except Exception as exc:
        log.warning("RMS measurement failed: %s", exc)

    return findings


# ---------------------------------------------------------------------------
# Frame sampling
# ---------------------------------------------------------------------------

def _sample_frames(video_path: str, duration: float, frames_dir: str) -> list[float]:
    """
    Extract one JPEG frame every FRAME_SAMPLE_INTERVAL seconds.
    Returns the list of timestamps that were actually saved.
    """
    times: list[float] = []
    t = 0.0
    while t < duration:
        out_path = Path(frames_dir) / f"frame_{t:.3f}.jpg"
        try:
            (
                ffmpeg
                .input(video_path, ss=t)
                .output(str(out_path), vframes=1, loglevel="quiet")
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            if out_path.exists():
                times.append(round(t, 3))
        except ffmpeg.Error:
            pass
        t += FRAME_SAMPLE_INTERVAL
    return times


# ---------------------------------------------------------------------------
# Visual analysis (brightness + blur)
# ---------------------------------------------------------------------------

def _analyze_frames(
    frames_dir: Path,
    frame_times: list[float],
    duration: float,
) -> list[Finding]:
    """Measure mean brightness and Laplacian-variance blur for each frame."""
    findings: list[Finding] = []
    for t in frame_times:
        img_path = frames_dir / f"frame_{t:.3f}.jpg"
        if not img_path.exists():
            continue
        img = cv2.imread(str(img_path))
        if img is None:
            continue

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        end_t = min(t + FRAME_SAMPLE_INTERVAL, duration)

        # Brightness
        brightness = float(gray.mean())
        b_label = (
            "very dark" if brightness < 30 else
            "dark" if brightness < 80 else
            "normal" if brightness < 180 else
            "bright"
        )
        findings.append(Finding(
            id=str(uuid.uuid4()),
            category="visual",
            start=round(t, 3),
            end=round(end_t, 3),
            metric="mean_brightness",
            value=round(brightness, 2),
            interpretation=(
                f"Frame at {t:.1f}s is {b_label} "
                f"(mean brightness {brightness:.1f}/255)."
            ),
        ))

        # Blur
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        blur = round(blur, 2)
        blur_label = "blurry" if blur < 100 else "sharp"
        findings.append(Finding(
            id=str(uuid.uuid4()),
            category="visual",
            start=round(t, 3),
            end=round(end_t, 3),
            metric="blur_score",
            value=blur,
            interpretation=(
                f"Frame at {t:.1f}s appears {blur_label} "
                f"(Laplacian variance {blur:.1f})."
            ),
        ))

    return findings


# ---------------------------------------------------------------------------
# Scene cut detection
# ---------------------------------------------------------------------------

def _detect_scene_cuts(
    frames_dir: Path,
    frame_times: list[float],
    duration: float,
) -> list[Finding]:
    """Flag large mean-pixel-diff between consecutive frames as scene cuts."""
    findings: list[Finding] = []
    prev_gray: Optional[cv2.typing.MatLike] = None  # type: ignore[name-defined]
    prev_t: Optional[float] = None

    for t in frame_times:
        img_path = frames_dir / f"frame_{t:.3f}.jpg"
        if not img_path.exists():
            prev_gray = None
            prev_t = None
            continue

        img = cv2.imread(str(img_path))
        if img is None:
            prev_gray = None
            prev_t = None
            continue

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if prev_gray is not None and prev_t is not None:
            diff = float(cv2.absdiff(gray, cv2.resize(prev_gray, (gray.shape[1], gray.shape[0]))).mean())
            if diff >= SCENE_CUT_THRESHOLD:
                findings.append(Finding(
                    id=str(uuid.uuid4()),
                    category="pacing",
                    start=round(prev_t, 3),
                    end=round(t, 3),
                    metric="scene_cut",
                    value=round(diff, 2),
                    interpretation=(
                        f"Scene cut detected between {prev_t:.1f}s and {t:.1f}s "
                        f"(mean pixel diff {diff:.1f})."
                    ),
                ))

        prev_gray = gray
        prev_t = t

    return findings


# ---------------------------------------------------------------------------
# Transcription (mock / stub)
# ---------------------------------------------------------------------------

def _get_transcript(duration: float) -> list[TranscriptSegment]:
    """
    Return transcript segments.

    Mock mode  — load from the example_analysis_input.json fixture.
    Real mode  — placeholder; wired to IBM Granite Speech in Sub-Task 4.
    """
    if settings.use_mock_ai:
        try:
            data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
            segments = [TranscriptSegment(**s) for s in data.get("transcript_segments", [])]
            # Clamp any segments that exceed the actual video duration
            clamped = []
            for seg in segments:
                if seg.start > duration:
                    continue
                if seg.end > duration:
                    seg = seg.model_copy(update={"end": duration})
                clamped.append(seg)
            return clamped
        except Exception as exc:
            log.warning("Could not load mock transcript: %s", exc)

    # Real mode stub — Sub-Task 4 will call IBM Granite Speech here
    return []
