"""
CreatorLens — FastAPI application.

Endpoints
---------
POST   /api/projects                  Create a project and save the creative brief
POST   /api/projects/{id}/media       Upload a video file
POST   /api/projects/{id}/analyze     Trigger analysis (mock or real)
GET    /api/projects/{id}/status      Poll analysis progress
GET    /api/projects/{id}/analysis    Retrieve the completed AnalysisOutput
POST   /api/projects/{id}/edits       Submit approved edit IDs
GET    /api/projects/{id}/preview     Return the preview file URL or processing status
"""

import json
import logging
import pathlib
import uuid
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import settings
from backend.pipeline.editor import apply_silence_removal
from backend.pipeline.extractor import extract_evidence
from backend.pipeline.granite import analyze as granite_analyze
from backend.schemas import Finding, ProjectBrief

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("creatorlens")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="CreatorLens API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve rendered preview files as static assets
_uploads_dir = pathlib.Path(settings.upload_dir)
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")

# ---------------------------------------------------------------------------
# In-memory project state  (MVP: no database)
# ---------------------------------------------------------------------------

# projects[id] = {
#   "brief": ProjectBrief,
#   "status": "queued" | "processing" | "completed" | "failed",
#   "progress_message": str,
#   "media_path": str | None,
#   "media_meta": dict | None,
#   "analysis_output": dict | None,       # serialized AnalysisOutput
#   "preview_status": "pending" | "processing" | "completed" | "failed",
#   "preview_url": str | None,
# }
projects: dict[str, dict[str, Any]] = {}

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm"}
EXAMPLE_OUTPUT_PATH = pathlib.Path(__file__).parent.parent / "docs" / "example_analysis_output.json"


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):  # noqa: ANN001
    log.exception("Unhandled error on %s", request.url)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Request / response models (endpoint-local shapes)
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    brief: ProjectBrief


class CreateProjectResponse(BaseModel):
    project_id: str
    brief: ProjectBrief


class MediaUploadResponse(BaseModel):
    project_id: str
    filename: str
    size_bytes: int
    duration_seconds: float | None = None  # populated after real extraction
    message: str


class AnalyzeResponse(BaseModel):
    project_id: str
    status: str
    message: str


class StatusResponse(BaseModel):
    project_id: str
    status: str
    progress_message: str


class ApprovedEdit(BaseModel):
    edit_id: str


class SubmitEditsRequest(BaseModel):
    approved_edits: list[ApprovedEdit]


class SubmitEditsResponse(BaseModel):
    project_id: str
    accepted: list[str]
    message: str


class PreviewResponse(BaseModel):
    project_id: str
    status: str
    preview_url: str | None = None
    message: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _require_project(project_id: str) -> dict[str, Any]:
    """Return the project state dict or raise 404."""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return projects[project_id]


def _load_mock_output() -> dict[str, Any]:
    """Load the example AnalysisOutput fixture from docs/."""
    return json.loads(EXAMPLE_OUTPUT_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def health_check():
    return {"message": "Backend is running"}


@app.post("/api/projects", response_model=CreateProjectResponse, status_code=201)
def create_project(body: CreateProjectRequest):
    """Create a new project and persist the creative brief."""
    project_id = str(uuid.uuid4())
    projects[project_id] = {
        "brief": body.brief,
        "status": "queued",
        "progress_message": "Project created. Upload a video to begin.",
        "media_path": None,
        "media_meta": None,
        "analysis_output": None,
        "preview_status": "pending",
        "preview_url": None,
    }
    log.info("project=%s created platform=%s", project_id, body.brief.platform)
    return CreateProjectResponse(project_id=project_id, brief=body.brief)


@app.post("/api/projects/{project_id}/media", response_model=MediaUploadResponse)
async def upload_media(project_id: str, file: UploadFile = File(...)):
    """Accept a video upload, validate it, and save it to disk."""
    state = _require_project(project_id)

    # Validate file extension
    suffix = pathlib.Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix}'. Allowed: {ALLOWED_EXTENSIONS}",
        )

    # Read and validate size
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_bytes} byte limit",
        )

    # Save to UPLOAD_DIR/{project_id}/original{suffix}
    project_dir = pathlib.Path(settings.upload_dir) / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    dest = project_dir / f"original{suffix}"
    dest.write_bytes(data)

    state["media_path"] = str(dest)
    state["media_meta"] = {"filename": file.filename, "size_bytes": len(data)}
    state["progress_message"] = "Media uploaded. Ready to analyze."
    log.info("project=%s media saved size=%d path=%s", project_id, len(data), dest)

    return MediaUploadResponse(
        project_id=project_id,
        filename=file.filename or "",
        size_bytes=len(data),
        message="File uploaded successfully",
    )


@app.post("/api/projects/{project_id}/analyze", response_model=AnalyzeResponse)
def trigger_analysis(project_id: str, background_tasks: BackgroundTasks):
    """
    Trigger analysis.
    If analysis is already completed, returns cached result immediately.
    Otherwise queues a background task and returns status: queued.
    """
    state = _require_project(project_id)

    # Return cached result if already done
    if state["status"] == "completed" and state["analysis_output"] is not None:
        log.info("project=%s analysis already completed — returning cached", project_id)
        return AnalyzeResponse(
            project_id=project_id,
            status="completed",
            message="Analysis already complete. Retrieve results from GET /analysis.",
        )

    if state["media_path"] is None:
        raise HTTPException(status_code=400, detail="Upload a video before triggering analysis.")

    state["status"] = "queued"
    state["progress_message"] = "Analysis queued."
    background_tasks.add_task(_run_analysis, project_id)
    log.info("project=%s analysis queued", project_id)
    return AnalyzeResponse(
        project_id=project_id,
        status="queued",
        message="Analysis queued. Poll GET /status for progress.",
    )


def _run_analysis(project_id: str) -> None:
    """Background worker: extract evidence → call Granite → persist result."""
    state = projects.get(project_id)
    if state is None:
        return

    try:
        state["status"] = "processing"
        state["progress_message"] = "Extracting media evidence…"
        log.info("project=%s analysis started", project_id)

        brief = state["brief"]
        media_path = state["media_path"]

        # Step 1 — extract evidence from the video
        analysis_input = extract_evidence(media_path, brief)
        state["progress_message"] = "Running AI analysis…"

        # Step 2 — send evidence to Granite
        analysis_output = granite_analyze(analysis_input)

        # Step 3 — persist to disk so it survives restarts
        output_dict = analysis_output.model_dump()
        output_path = pathlib.Path(settings.upload_dir) / project_id / "analysis_output.json"
        output_path.write_text(json.dumps(output_dict, indent=2), encoding="utf-8")

        state["analysis_output"] = output_dict
        state["status"] = "completed"
        state["progress_message"] = "Analysis complete."
        log.info("project=%s analysis complete", project_id)

    except Exception as exc:
        state["status"] = "failed"
        state["progress_message"] = f"Analysis failed: {exc}"
        log.exception("project=%s analysis failed", project_id)


@app.get("/api/projects/{project_id}/status", response_model=StatusResponse)
def get_status(project_id: str):
    """Return the current analysis status and a human-readable progress message."""
    state = _require_project(project_id)
    log.info("project=%s status=%s", project_id, state["status"])
    return StatusResponse(
        project_id=project_id,
        status=state["status"],
        progress_message=state["progress_message"],
    )


@app.get("/api/projects/{project_id}/analysis")
def get_analysis(project_id: str):
    """Return the completed AnalysisOutput, or 404 if not yet available."""
    state = _require_project(project_id)
    if state["status"] != "completed" or state["analysis_output"] is None:
        raise HTTPException(
            status_code=404,
            detail=f"Analysis not yet available. Current status: '{state['status']}'",
        )
    log.info("project=%s analysis retrieved", project_id)
    return state["analysis_output"]


@app.post("/api/projects/{project_id}/edits", response_model=SubmitEditsResponse)
def submit_edits(
    project_id: str,
    body: SubmitEditsRequest,
    background_tasks: BackgroundTasks,
):
    """Accept approved edit IDs and queue silence removal rendering."""
    state = _require_project(project_id)
    if state["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail="Analysis must be completed before submitting edits",
        )

    accepted = [e.edit_id for e in body.approved_edits]

    # Only silence_removal is supported in MVP
    silence_requested = any("silence" in eid.lower() for eid in accepted)
    if not silence_requested:
        raise HTTPException(
            status_code=400,
            detail="Only 'silence_removal' edits are supported in MVP.",
        )

    state["preview_status"] = "processing"
    state["progress_message"] = "Rendering silence removal…"
    background_tasks.add_task(_run_silence_removal, project_id)
    log.info("project=%s edits accepted=%s", project_id, accepted)
    return SubmitEditsResponse(
        project_id=project_id,
        accepted=accepted,
        message="Silence removal queued. Poll GET /preview for the result.",
    )


def _run_silence_removal(project_id: str) -> None:
    """Background worker: apply silence removal and update preview state."""
    state = projects.get(project_id)
    if state is None:
        return

    try:
        media_path = state["media_path"]
        analysis = state["analysis_output"] or {}

        # Pull silence findings out of the stored analysis output
        silence_findings = [
            Finding(**f)
            for f in analysis.get("findings", [])
            if f.get("metric") == "silence_duration_seconds"
        ]

        # Fall back to findings stored in media_meta if analysis_output lacks them
        if not silence_findings and state.get("media_meta"):
            silence_findings = []

        if not silence_findings:
            log.warning("project=%s no silence findings — skipping render", project_id)
            state["preview_status"] = "failed"
            state["progress_message"] = "No silence gaps found to remove."
            return

        out_path = apply_silence_removal(media_path, silence_findings)

        # Build a URL the browser can fetch
        rel = pathlib.Path(out_path).relative_to(pathlib.Path(settings.upload_dir))
        preview_url = f"/uploads/{rel.as_posix()}"

        state["preview_url"] = preview_url
        state["preview_status"] = "completed"
        state["progress_message"] = "Preview ready."
        log.info("project=%s preview ready url=%s", project_id, preview_url)

    except Exception as exc:
        state["preview_status"] = "failed"
        state["progress_message"] = f"Render failed: {exc}"
        log.exception("project=%s silence removal failed", project_id)


@app.get("/api/projects/{project_id}/preview", response_model=PreviewResponse)
def get_preview(project_id: str):
    """Return the preview file URL, or the current rendering status."""
    state = _require_project(project_id)
    log.info("project=%s preview_status=%s", project_id, state["preview_status"])
    return PreviewResponse(
        project_id=project_id,
        status=state["preview_status"],
        preview_url=state["preview_url"],
        message=(
            "Preview ready." if state["preview_status"] == "completed"
            else f"Preview status: {state['preview_status']}"
        ),
    )
