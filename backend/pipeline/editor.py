"""
CreatorLens — Silence Removal Edit Pipeline (Sub-Task 6).

Public interface
---------------
    apply_silence_removal(video_path: str, silence_findings: list[Finding]) -> str

Takes the original video and the silence Finding list produced by the extractor,
builds an FFmpeg filter graph that cuts those gaps out, and writes a browser-playable
H.264/AAC mp4 to the same project directory.  Returns the output file path.
"""

import logging
import pathlib
import uuid

import ffmpeg

from backend.schemas import Finding

log = logging.getLogger("creatorlens.editor")


def apply_silence_removal(video_path: str, silence_findings: list[Finding]) -> str:
    """
    Remove silence gaps from *video_path* and return the output file path.

    Parameters
    ----------
    video_path      : path to the original uploaded video
    silence_findings: Finding objects with metric == "silence_duration_seconds"

    Returns
    -------
    Path to the rendered preview file (mp4, H.264/AAC).

    Raises
    ------
    ValueError  if no silence findings are provided
    RuntimeError if FFmpeg fails
    """
    if not silence_findings:
        raise ValueError("No silence findings provided — nothing to remove.")

    video_path = str(video_path)
    out_path = _output_path(video_path)

    # Probe total duration so we can build keep-segments
    probe = ffmpeg.probe(video_path)
    duration = float(probe["format"]["duration"])

    keep_segments = _invert_silences(silence_findings, duration)
    log.info(
        "editor silence_removal segments_to_keep=%d path=%s",
        len(keep_segments),
        video_path,
    )

    if not keep_segments:
        raise ValueError("Silence covers the entire video — nothing to keep.")

    _render(video_path, keep_segments, str(out_path))
    log.info("editor render complete out=%s", out_path)
    return str(out_path)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _output_path(video_path: str) -> pathlib.Path:
    """Return <project_dir>/preview.mp4 next to the original file."""
    return pathlib.Path(video_path).parent / "preview.mp4"


def _invert_silences(
    findings: list[Finding],
    duration: float,
    min_keep: float = 0.1,
) -> list[tuple[float, float]]:
    """
    Convert silence intervals into the segments we WANT to keep.

    Example
    -------
    silence: [(5.0, 7.0)]  duration: 10.0
    keep:    [(0.0, 5.0), (7.0, 10.0)]
    """
    # Sort silence gaps by start time
    gaps = sorted(
        [(max(0.0, f.start), min(duration, f.end)) for f in findings],
        key=lambda x: x[0],
    )

    keep: list[tuple[float, float]] = []
    cursor = 0.0

    for gap_start, gap_end in gaps:
        if gap_start > cursor + min_keep:
            keep.append((cursor, gap_start))
        cursor = max(cursor, gap_end)

    # Keep any remaining content after the last silence gap
    if duration - cursor > min_keep:
        keep.append((cursor, duration))

    return keep


def _render(
    video_path: str,
    keep_segments: list[tuple[float, float]],
    out_path: str,
) -> None:
    """
    Build and run an FFmpeg filter graph that keeps only *keep_segments*.

    Uses the trim/atrim + concat approach:
      - For each segment: trim video + atrim audio, reset timestamps with setpts/asetpts
      - concat all segments back together
      - encode as H.264/AAC mp4
    """
    n = len(keep_segments)
    streams = []
    input_file = ffmpeg.input(video_path)

    for i, (start, end) in enumerate(keep_segments):
        v = (
            input_file.video
            .filter("trim", start=start, end=end)
            .filter("setpts", "PTS-STARTPTS")
        )
        a = (
            input_file.audio
            .filter("atrim", start=start, end=end)
            .filter("asetpts", "PTS-STARTPTS")
        )
        streams.extend([v, a])

    # concat: n segments, 1 video stream, 1 audio stream per segment
    joined = ffmpeg.concat(*streams, v=1, a=1)

    try:
        (
            ffmpeg
            .output(
                joined,
                out_path,
                vcodec="libx264",
                acodec="aac",
                preset="fast",
                crf=23,
                loglevel="quiet",
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise RuntimeError(f"FFmpeg render failed: {stderr}") from exc
