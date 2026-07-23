"""
Tests for backend/main.py endpoint stubs.

All tests run against the FastAPI TestClient with USE_MOCK_AI=true,
so no IBM credentials or FFmpeg are required.

Coverage:
  - Happy path for every endpoint
  - 404 on unknown project
  - 422 on wrong file type
  - 413 on oversized upload
  - 409 on edits submitted before analysis is complete
"""

import io
import pytest
from fastapi.testclient import TestClient

# Force mock mode before importing the app so config is applied
import os
os.environ.setdefault("USE_MOCK_AI", "true")

from backend.main import app, projects  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_BRIEF = {
    "brief": {
        "goal": "Teach Git branching in 90 seconds",
        "platform": "YouTube",
        "audience": "Beginners",
        "tone": "Casual",
        "target_length_seconds": 90.0,
    }
}


def _create_project() -> str:
    """Create a project and return its ID."""
    resp = client.post("/api/projects", json=VALID_BRIEF)
    assert resp.status_code == 201
    return resp.json()["project_id"]


def _fake_video(name: str = "test.mp4", size: int = 1024) -> tuple:
    """Return (files dict, bytes) for a fake upload."""
    data = b"\x00" * size
    return (
        {"file": (name, io.BytesIO(data), "video/mp4")},
        data,
    )


# ---------------------------------------------------------------------------
# POST /api/projects
# ---------------------------------------------------------------------------

def test_create_project_returns_id_and_brief():
    resp = client.post("/api/projects", json=VALID_BRIEF)
    assert resp.status_code == 201
    body = resp.json()
    assert "project_id" in body
    assert body["brief"]["platform"] == "YouTube"


def test_create_project_missing_brief_field():
    bad = {"brief": {"goal": "test"}}  # missing required fields
    resp = client.post("/api/projects", json=bad)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/projects/{id}/media
# ---------------------------------------------------------------------------

def test_upload_media_happy_path():
    pid = _create_project()
    files, _ = _fake_video()
    resp = client.post(f"/api/projects/{pid}/media", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == pid
    assert body["size_bytes"] == 1024


def test_upload_media_wrong_extension():
    pid = _create_project()
    files, _ = _fake_video(name="clip.avi")
    resp = client.post(f"/api/projects/{pid}/media", files=files)
    assert resp.status_code == 422


def test_upload_media_unknown_project():
    files, _ = _fake_video()
    resp = client.post("/api/projects/does-not-exist/media", files=files)
    assert resp.status_code == 404


def test_upload_media_oversized():
    pid = _create_project()
    # Patch the limit temporarily so we don't allocate 500 MB in tests
    from backend import main as main_module
    original = main_module.settings.max_upload_bytes
    main_module.settings.max_upload_bytes = 10
    try:
        files, _ = _fake_video(size=100)
        resp = client.post(f"/api/projects/{pid}/media", files=files)
        assert resp.status_code == 413
    finally:
        main_module.settings.max_upload_bytes = original


# ---------------------------------------------------------------------------
# POST /api/projects/{id}/analyze
# ---------------------------------------------------------------------------

def test_analyze_mock_returns_completed():
    pid = _create_project()
    resp = client.post(f"/api/projects/{pid}/analyze")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"


def test_analyze_unknown_project():
    resp = client.post("/api/projects/ghost/analyze")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/status
# ---------------------------------------------------------------------------

def test_status_after_create():
    pid = _create_project()
    resp = client.get(f"/api/projects/{pid}/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_status_after_analyze():
    pid = _create_project()
    client.post(f"/api/projects/{pid}/analyze")
    resp = client.get(f"/api/projects/{pid}/status")
    assert resp.json()["status"] == "completed"


def test_status_unknown_project():
    resp = client.get("/api/projects/ghost/status")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/analysis
# ---------------------------------------------------------------------------

def test_analysis_before_analyze_returns_404():
    pid = _create_project()
    resp = client.get(f"/api/projects/{pid}/analysis")
    assert resp.status_code == 404


def test_analysis_after_analyze_returns_output():
    pid = _create_project()
    client.post(f"/api/projects/{pid}/analyze")
    resp = client.get(f"/api/projects/{pid}/analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert "summary" in body
    assert "scores" in body
    assert "timeline_feedback" in body


def test_analysis_unknown_project():
    resp = client.get("/api/projects/ghost/analysis")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/projects/{id}/edits
# ---------------------------------------------------------------------------

def test_submit_edits_happy_path():
    pid = _create_project()
    client.post(f"/api/projects/{pid}/analyze")
    payload = {"approved_edits": [{"edit_id": "edit_001"}]}
    resp = client.post(f"/api/projects/{pid}/edits", json=payload)
    assert resp.status_code == 200
    assert "edit_001" in resp.json()["accepted"]


def test_submit_edits_before_analysis_is_409():
    pid = _create_project()
    payload = {"approved_edits": [{"edit_id": "edit_001"}]}
    resp = client.post(f"/api/projects/{pid}/edits", json=payload)
    assert resp.status_code == 409


def test_submit_edits_unknown_project():
    payload = {"approved_edits": [{"edit_id": "edit_001"}]}
    resp = client.post("/api/projects/ghost/edits", json=payload)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/preview
# ---------------------------------------------------------------------------

def test_preview_initial_status_is_pending():
    pid = _create_project()
    resp = client.get(f"/api/projects/{pid}/preview")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_preview_after_edits_submitted_is_processing():
    pid = _create_project()
    client.post(f"/api/projects/{pid}/analyze")
    client.post(f"/api/projects/{pid}/edits", json={"approved_edits": [{"edit_id": "e1"}]})
    resp = client.get(f"/api/projects/{pid}/preview")
    assert resp.json()["status"] == "processing"


def test_preview_unknown_project():
    resp = client.get("/api/projects/ghost/preview")
    assert resp.status_code == 404
