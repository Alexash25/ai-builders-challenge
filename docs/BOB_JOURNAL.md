# IBM Bob Development Journal — CreatorLens

> Dated record of Bob-assisted development work. Each entry captures the goal, what Bob did, what the human decided, and how the result was verified.
> 
> Required for submission as evidence that IBM Bob was the primary development tool.

---

## Entry Format

```
## YYYY-MM-DD — Short summary
**Team member:** Name
**Goal:** What we needed to accomplish
**Bob task:** The concise instruction given to Bob
**Files/context provided:** Files Bob inspected or changed
**Bob contribution:** Plan, code, tests, debugging, review, or documentation
**Human decisions:** What we accepted, rejected, or modified and why
**Verification:** Commands/tests run and result
**Related work:** Issue, commit, or pull request link
**Next step:** The immediate follow-up
```

---

## Entries

---

## 2026-07-21 — Project orientation and repo exploration

**Team member:** Alex  
**Goal:** Understand the existing repo structure, what the frontend had, and how to get both services running locally.  
**Bob task:** Explore the workspace — read the README, plan files, frontend scaffold, and backend skeleton. Explain what exists and what the next steps are.  
**Files/context provided:** `README.md`, `DEVLOG.md`, `API_CONTRACT.md`, `ARCHITECTURE.md`, `frontend/creative-editing-tool/package.json`, `backend/main.py`, `backend/README.md`, `Plan Schematics/10_Day_Hackathon_Plan.pdf`, `Plan Schematics/ML_Backend_Lead_Tasks.pdf`, `Plan Schematics/IBM_Bob_Task_Plan.pdf`, `Plan Schematics/BACKEND_BUILD_PLAN.md`  
**Bob contribution:** Read all three PDFs and the full repo layout. Identified that the frontend was a default Next.js scaffold (no real UI yet) and the backend was a single health-check endpoint. Explained the full two-service run procedure (activate `.venv`, `uvicorn backend.main:app --reload`, then `npm run dev` in a second terminal). Confirmed `.venv` already contained `fastapi`, `uvicorn`, `pytest`, and other required packages. Summarised the 7-sub-task build plan and flagged that today's work was Sub-Task 1 + Sub-Task 2.  
**Human decisions:** Accepted the run instructions. Decided to proceed directly to Sub-Task 1 and 2 in the same session.  
**Verification:** Confirmed `.venv/Scripts/` contained `uvicorn.exe`, `fastapi.exe`, `pytest.exe`. Confirmed `pydantic-settings` and `python-multipart` were already installed.  
**Related work:** N/A — orientation session, no code changed.  
**Next step:** Run the existing schema tests, then build the FastAPI skeleton.

---

## 2026-07-22 — Sub-Task 1 verification + Sub-Task 2 implementation

**Team member:** Alex  
**Goal:** Confirm Sub-Task 1 was complete, then build the full FastAPI skeleton with all 7 stub endpoints so the frontend could call the backend and render a mock response.  
**Bob task:** Read the existing `backend/schemas.py`, `backend/tests/test_schemas.py`, and both example JSON fixtures. Run the schema tests. Then implement `backend/config.py`, `.env.example`, a fully-featured `backend/main.py`, and `backend/tests/test_endpoints.py` per the spec in `BACKEND_BUILD_PLAN.md`.  
**Files/context provided:** `backend/schemas.py`, `backend/tests/test_schemas.py`, `docs/example_analysis_input.json`, `docs/example_analysis_output.json`, `Plan Schematics/BACKEND_BUILD_PLAN.md`  
**Bob contribution:**
- Ran `pytest backend/tests/test_schemas.py` — confirmed 16/16 passing before touching anything.
- Created `backend/config.py` using `pydantic-settings` with all 8 environment variables (`UPLOAD_DIR`, `MAX_UPLOAD_BYTES`, `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`, `GRANITE_MODEL_ID`, `USE_MOCK_AI`, `FRONTEND_ORIGIN`) and sensible defaults.
- Created `.env.example` at the repo root with all variable names, no real values, and inline comments explaining each one including a note about FFmpeg needing to be on PATH.
- Rewrote `backend/main.py` from the 3-line stub into a full FastAPI application: CORS middleware configured for `http://localhost:3000`, structured logging on every request, a global exception handler returning `{error, detail}` JSON, in-memory project state dict, and all 7 endpoints (`POST /api/projects`, `POST /{id}/media`, `POST /{id}/analyze`, `GET /{id}/status`, `GET /{id}/analysis`, `POST /{id}/edits`, `GET /{id}/preview`). Mock mode loads `docs/example_analysis_output.json` and validates it against the Pydantic schema before returning.
- Created `backend/tests/test_endpoints.py` with 20 tests covering the happy path for every endpoint plus bad-input cases: wrong file extension (422), oversized file (413), edits submitted before analysis (409), and unknown project IDs (404).
- Ran the full test suite — 36/36 passing.

**Human decisions:** Accepted all generated code and tests without modification.  
**Verification:** `pytest backend/tests/` → 36 passed in 1.14s. No failures.  
**Related work:** N/A — local session, not yet committed.  
**Next step:** Sub-Task 3 — Media Evidence Extraction Pipeline. Requires FFmpeg on PATH and `opencv-python-headless` in the venv. Confirm both before starting.

---

## 2026-07-23 — Sub-Task 3: Media Evidence Extraction Pipeline

**Team member:** Alex  
**Goal:** Build the FFmpeg + OpenCV evidence extraction pipeline that produces a validated `AnalysisInput` from a real video file.  
**Bob task:** Create `backend/pipeline/extractor.py` with `extract_evidence(video_path, brief) -> AnalysisInput`, covering FFprobe metadata, audio extraction, silence detection, RMS volume, frame sampling, brightness/blur analysis, and scene-cut detection. Add `backend/tests/test_extractor.py` with a synthetic test video generated by FFmpeg.  
**Files/context provided:** `backend/schemas.py`, `backend/pipeline/extractor.py`, `backend/tests/test_extractor.py`, `Plan Schematics/BACKEND_BUILD_PLAN.md`  
**Bob contribution:**
- Confirmed FFmpeg was on PATH (`ffprobe version 8.1.2`) and `opencv-python-headless` (`cv2 5.0.0`) was installed. Installed `ffmpeg-python` (was missing from venv).
- Created `backend/pipeline/__init__.py` and `backend/pipeline/extractor.py` with the full extraction pipeline: FFprobe metadata, mono 16kHz WAV extraction, `silencedetect` filter parsing, per-window RMS in dBFS, frame sampling every 5s, per-frame mean brightness and Laplacian-variance blur, and consecutive-frame scene-cut detection.
- Mock transcript path loads from `docs/example_analysis_input.json` and clamps any segments that exceed the actual video duration.
- Created `backend/fixtures/README.md` placeholder directory.
- Created `pytest.ini` with `pythonpath = .` — this was the root cause of all prior `ModuleNotFoundError: No module named 'backend'` failures. All 36 pre-existing tests were broken without it; adding it restored them immediately.
- Created `backend/tests/test_extractor.py` with 19 tests across 3 classes: `TestProbeMetadata`, `TestSilenceDetection`, `TestFrameAnalysis`, and `TestExtractEvidence`. Tests use a session-scoped synthetic 10-second video with a known 2s silence gap generated by FFmpeg lavfi filters.
- Ran full suite — 55/55 passing.

**Human decisions:** Accepted all generated code. Alex confirmed FFmpeg and cv2 were already installed before the session started.  
**Verification:** `pytest backend/tests/` → 55 passed. `python -c "from backend.pipeline.extractor import extract_evidence; print('ok')"` → ok.  
**Related work:** N/A — local session.  
**Next step:** Sub-Task 4 — IBM Granite Integration Layer (`backend/pipeline/granite.py`).

---

## 2026-07-24 — Sub-Task 4: IBM Granite Integration Layer

**Team member:** Alex  
**Goal:** Build `backend/pipeline/granite.py` with mock and real watsonx.ai paths, retry logic, timestamp clamping, and a safe fallback response.  
**Bob task:** Implement `analyze(AnalysisInput) -> AnalysisOutput` in `backend/pipeline/granite.py`. Mock mode returns the fixture. Real mode calls watsonx.ai with one retry on bad JSON and a safe partial fallback on second failure.  
**Files/context provided:** `backend/pipeline/granite.py`, `backend/schemas.py`, `backend/config.py`, `docs/example_analysis_output.json`  
**Bob contribution:**
- Wrote `granite.py` with `analyze`, `_build_system_prompt`, `_build_user_prompt`, `_call_granite`, and `_parse_and_validate`.
- `_parse_and_validate` strips markdown code fences, parses JSON, validates against `AnalysisOutput`, and clamps feedback items beyond the video duration.
- `_call_granite` wraps SDK imports in a `try/except ImportError` so the server doesn't crash if `ibm-watsonx-ai` is absent.
- Added `str()` cast on `model.generate_text()` return value to satisfy VS Code type checker (SDK stubs return `str | list | dict`).
- Repeatedly fixed `_call_granite` and `_parse_and_validate` after Alex accidentally overwrote the file multiple times during the session.
- Investigated watsonx.ai free tier model access — found that `ibm/granite-3-3-8b-instruct` and `ibm/granite-3-1-8b-instruct` are not available on the Lite plan. Queried live API; only `ibm/granite-3-1-8b-base` was present but does not support `text_generation`. Updated `.env.example` with correct model ID and a note to use `USE_MOCK_AI=true` during development.

**Human decisions:** Kept `USE_MOCK_AI=true` as the active dev path. Alex will seek hackathon promo access or IBM support for instruct model access separately. Accepted all Bob-generated code after repeated manual edits were reverted.  
**Verification:** `python -c "from backend.pipeline.granite import analyze; print('ok')"` → ok. Mock mode returns valid `AnalysisOutput` from fixture.  
**Related work:** N/A — local session.  
**Next step:** Sub-Task 5 — Wire extractor + granite into the live `/analyze` endpoint with background task and status polling.

---

## 2026-07-24 — Sub-Task 5: Live Analysis Endpoint + watsonx.ai Model Discovery

**Team member:** Alex  
**Goal:** Wire the real extraction + Granite pipeline into the `/analyze` endpoint with background task processing, status polling, and disk persistence. Also discover and confirm a working IBM Granite model on the free tier.  
**Bob task:** Update `backend/main.py` `/analyze` endpoint to run `extract_evidence` + `granite_analyze` in a `BackgroundTask`, update status `queued → processing → completed/failed`, persist result to `uploads/{id}/analysis_output.json`, and return cached result on repeat calls. Update endpoint tests to match new behaviour.  
**Files/context provided:** `backend/main.py`, `backend/tests/test_endpoints.py`, `backend/pipeline/extractor.py`, `backend/pipeline/granite.py`  
**Bob contribution:**
- Added `BackgroundTasks` to `/analyze`, blocking calls with no media upload (400), caching completed results, and queuing `_run_analysis` worker.
- Implemented `_run_analysis`: runs `extract_evidence` → `granite_analyze` → writes `analysis_output.json` to disk → updates project state.
- Updated 5 endpoint tests that assumed immediate mock completion — rewrote them to match the queued background model.
- Queried live watsonx.ai API and discovered `ibm/granite-4-h-small` — confirmed it responds to `generate_text` prompts.
- Identified API deprecation warning: `/ml/v1/text/generation` is deprecated; need to migrate to chat API (`/ml/v1/text/chat`) in the next session.
- Full test suite: 38/38 passing after endpoint test updates.

**Human decisions:** Alex ran the full pipeline end-to-end through the Swagger UI (`http://localhost:8000/docs`) using a real video. The extractor returned genuine measurements: audio quiet at -38.63 dBFS, mean brightness 33.7/255 (dark frame), blur score 2818.8 (sharp). Alex correctly identified the project ID issue (typed "goob" instead of the UUID) and resolved it independently — solid debugging. Alex also noticed `granite-4-h-small` appearing in the model list and flagged it for investigation. All of this was sharp, hands-on work — Alex drove the live testing and caught real issues that automated tests wouldn't surface.  
**Verification:** Backend log showed `project=e6117b42-... analysis complete`. Swagger UI returned full JSON with real findings. `granite-4-h-small` connection test printed a response.  
**Related work:** N/A — local session.  
**Next step:** Migrate `_call_granite` to use the chat API (`generate` with messages), set `GRANITE_MODEL_ID=ibm/granite-4-h-small` and `USE_MOCK_AI=false`, then move to Sub-Task 6 — Silence Removal Edit Pipeline.
