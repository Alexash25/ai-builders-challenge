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

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.config import settings
from backend.schemas import AnalysisOutput, ProjectBrief

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
def trigger_analysis(project_id: str):
    """
    Trigger analysis.
    In mock mode (USE_MOCK_AI=true): returns a complete AnalysisOutput immediately.
    In real mode: queues background processing (Sub-Task 5).
    """
    state = _require_project(project_id)

    if settings.use_mock_ai:
        mock_data = _load_mock_output()
        # Validate against schema before storing
        AnalysisOutput.model_validate(mock_data)
        state["analysis_output"] = mock_data
        state["status"] = "completed"
        state["progress_message"] = "Analysis complete (mock mode)."
        log.info("project=%s analysis complete (mock)", project_id)
        return AnalyzeResponse(
            project_id=project_id,
            status="completed",
            message="Mock analysis complete. Retrieve results from GET /analysis.",
        )

    # Real pipeline — Sub-Task 5 will wire this up
    state["status"] = "queued"
    state["progress_message"] = "Analysis queued."
    log.info("project=%s analysis queued (real mode)", project_id)
    return AnalyzeResponse(
        project_id=project_id,
        status="queued",
        message="Analysis queued. Poll GET /status for progress.",
    )


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
def submit_edits(project_id: str, body: SubmitEditsRequest):
    """Accept a list of approved edit IDs and queue them for rendering."""
    state = _require_project(project_id)
    if state["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail="Analysis must be completed before submitting edits",
        )
    accepted = [e.edit_id for e in body.approved_edits]
    state["preview_status"] = "processing"
    state["progress_message"] = f"Rendering {len(accepted)} edit(s)."
    log.info("project=%s edits accepted=%s", project_id, accepted)
    return SubmitEditsResponse(
        project_id=project_id,
        accepted=accepted,
        message=f"{len(accepted)} edit(s) accepted. Poll GET /preview for the result.",
    )


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
