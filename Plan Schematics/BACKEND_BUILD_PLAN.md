# CreatorLens — ML Backend Build Plan

**Role:** ML Backend Lead  
**Stack:** Python 3.12.4, FastAPI, Pydantic, FFmpeg, OpenCV, IBM Granite via watsonx.ai  
**Build window:** July 21–31, 2026  
**Submission deadline:** Friday, July 31 at 11:59 PM ET  
**Source of truth for team-wide plan:** `Plan Schematics/10_Day_Hackathon_Plan.pdf`  
**Source of truth for Bob task queue:** `Plan Schematics/IBM_Bob_Task_Plan.pdf`  
**Source of truth for backend scope:** `Plan Schematics/ML_Backend_Lead_Tasks.pdf`

---

## Top-Level Overview

The backend is a Python FastAPI service that accepts a video upload and a creative brief, runs a media processing pipeline to extract objective evidence, sends that evidence to IBM Granite, validates the structured response, and returns timestamped creative feedback to the frontend.

The backend owns the full path from raw video file → structured JSON report. It does not own the frontend UI, the FFmpeg rendering of the final edited video (that is the Media/Integration Lead's job), or the SkillsBuild certificate process.

The MVP pipeline in order:
1. Receive video + creative brief → store file, create project record
2. Extract audio, sample frames, detect silence, measure volume and scene boundaries
3. Transcribe speech → word-level timestamped segments
4. Aggregate all evidence into a single `analysis_input` JSON
5. Send to IBM Granite → receive `analysis_output` JSON
6. Validate, clamp, and return to frontend
7. Accept an approved edit ID → hand off to rendering pipeline

---

## Sub-Tasks

---

### Sub-Task 1 — Pydantic Schemas and Example Fixtures

**Status:** `[ ] pending`

**Intent**  
Lock the data contracts before any other code is written. The frontend lead and media lead need versioned example JSON files on Day 1 so they can build independently without waiting for the real pipeline.

**Expected Outcomes**
- `backend/schemas.py` exists with all Pydantic models matching the spec in `ML_Backend_Lead_Tasks.pdf`
- `docs/example_analysis_input.json` — a realistic hand-authored fixture a frontend dev can use as a mock API response
- `docs/example_analysis_output.json` — same, for the Granite response shape
- Schema unit tests pass for both valid and invalid payloads
- No other team member is blocked on data shapes after this task

**Todo List**
1. Create `backend/schemas.py` with Pydantic v2 models:
   - `ProjectBrief` — goal, platform, audience, tone, target_length_seconds
   - `VideoMetadata` — duration_seconds, fps, width, height
   - `TranscriptSegment` — id, start, end, text
   - `Finding` — id, category, start, end, metric, value, interpretation
   - `AnalysisInput` — composes the above four
   - `CategoryScores` — story, pacing, audio, visuals, accessibility (all int 0–100)
   - `TimelineFeedbackItem` — id, start, end, category, severity, evidence_ids, explanation, suggestion, automatic_fix (nullable)
   - `RecommendedEdit` — id, label, description, edit_type, automatic_fix_eligible, priority (int)
   - `AnalysisOutput` — summary, scores, timeline_feedback, recommended_edits, revised_script
2. Add field validators: timestamps must be non-negative; scores must be 0–100; severity must be one of `low | medium | high`
3. Hand-author `docs/example_analysis_input.json` using a fictional 90-second tutorial video scenario
4. Hand-author `docs/example_analysis_output.json` with 3–5 timeline feedback items and 3 recommended edits
5. Create `backend/tests/test_schemas.py` — validate both example JSON files load without error; test that invalid timestamps and out-of-range scores are rejected

**Relevant Context**
- Schema spec: `Plan Schematics/ML_Backend_Lead_Tasks.pdf` pages 3–4
- All timestamps are floating-point seconds
- `automatic_fix` on a `TimelineFeedbackItem` must only be non-null when the backend actually supports that operation (MVP: `silence_removal` only)
- Keep raw metric values separate from model interpretations in `Finding`

---

### Sub-Task 2 — FastAPI Skeleton and Stub Endpoints

**Status:** `[ ] pending`

**Intent**  
Stand up a running FastAPI service with all 7 API endpoints returning stub/mock responses. The frontend lead must be able to call the real server URL on Day 2 and render a complete mock result — no manual file moving.

**Expected Outcomes**
- `backend/main.py` starts with `uvicorn backend.main:app --reload`
- All 7 endpoints exist and return valid stub JSON matching the schemas
- CORS is configured for `http://localhost:3000` (Next.js dev server)
- Upload endpoint accepts a video file and saves it to a project-relative path
- `backend/config.py` loads environment variables via `pydantic-settings`
- `.env.example` exists at the repo root with all required variable names and no real values
- `backend/tests/test_endpoints.py` — at least one test per endpoint using `TestClient`

**Todo List**
1. Create `backend/config.py` using `pydantic-settings` — variables: `UPLOAD_DIR`, `MAX_UPLOAD_BYTES`, `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`, `GRANITE_MODEL_ID`, `USE_MOCK_AI` (bool, default true during dev)
2. Create `.env.example` at repo root with all variable names, no real values, and comments explaining each
3. Write `backend/main.py`:
   - `POST /api/projects` — create project, return project ID and stored brief
   - `POST /api/projects/{id}/media` — accept video upload, validate file type (mp4/mov/webm) and size limit, save to `UPLOAD_DIR/{id}/original.*`, return file metadata stub
   - `POST /api/projects/{id}/analyze` — trigger analysis (stub: return `status: queued`), in mock mode return a complete `AnalysisOutput` immediately
   - `GET /api/projects/{id}/status` — return one of `queued | processing | completed | failed` with a progress message
   - `GET /api/projects/{id}/analysis` — return stored `AnalysisOutput` (stub: load from `docs/example_analysis_output.json`)
   - `POST /api/projects/{id}/edits` — accept list of approved edit IDs, return accepted confirmation
   - `GET /api/projects/{id}/preview` — return preview file URL or processing status
4. Add structured logging using Python's `logging` module — log project ID on every request
5. Add a global exception handler that returns a consistent error envelope: `{error: str, detail: str}`
6. Write `backend/tests/test_endpoints.py` using FastAPI `TestClient` — test happy path for each endpoint and at least one bad-input case (wrong file type, missing fields)

**Relevant Context**
- API contract spec: `Plan Schematics/ML_Backend_Lead_Tasks.pdf` page 2
- Frontend runs on port 3000; backend runs on port 8000
- Project state lives in memory for MVP (no database required)
- `USE_MOCK_AI=true` must make the whole pipeline runnable with no IBM credentials

---

### Sub-Task 3 — Media Evidence Extraction Pipeline

**Status:** `[ ] pending`

**Intent**  
Produce a deterministic `analysis_input` JSON from a real video file using FFmpeg and OpenCV. This is the evidence package that gets sent to Granite. No AI involved yet — purely signal processing.

**Expected Outcomes**
- `backend/pipeline/extractor.py` takes a video file path and returns a populated `AnalysisInput`
- One test video in `sample_media/` produces a valid `analysis_input.json` with no manual editing
- All timestamps obey `0 <= start <= end <= duration`
- Findings have stable IDs and human-readable interpretations
- A fixture file can be saved so downstream development doesn't require reprocessing

**Todo List**
1. Create `backend/pipeline/extractor.py` with a single public function `extract_evidence(video_path: str, brief: ProjectBrief) -> AnalysisInput`
2. Use `ffprobe` (via `ffmpeg-python`) to extract: duration, fps, width, height, audio sample rate
3. Use `ffmpeg` to extract the audio track to a temp WAV file
4. Detect silence gaps: use `ffmpeg`'s `silencedetect` filter — return as `Finding` entries with `metric: silence_duration_seconds`
5. Measure RMS volume per 5-second window using the extracted WAV — return as `Finding` entries with `metric: rms_volume_db`
6. Sample one frame every 5 seconds using `ffmpeg` — save to a temp directory
7. For each sampled frame use OpenCV to measure: mean brightness (0–255), blur score (Laplacian variance) — return as `Finding` entries
8. Detect scene cuts: compare consecutive sampled frames by mean pixel difference — flag cuts above a threshold as `Finding` with `metric: scene_cut`
9. Transcription: if `USE_MOCK_AI=true`, load a stored fixture transcript; otherwise call IBM Granite Speech (stub the interface now, implement in Sub-Task 4)
10. Normalize all findings into `TranscriptSegment` and `Finding` lists with `uuid4`-generated IDs
11. Validate the assembled `AnalysisInput` against the Pydantic schema before returning
12. Create `backend/tests/test_extractor.py` — use a short synthetic test video (generate with FFmpeg in the test setup) to assert timestamp bounds and finding structure

**Relevant Context**
- FFmpeg and ffprobe must be installed on the system and on PATH — document this in `.env.example` comments
- OpenCV: `pip install opencv-python-headless` (no GUI needed)
- Keep raw numeric values in `Finding.value`; put the human-readable sentence in `Finding.interpretation`
- Do not process every frame — sampled frames only (every 5 seconds max)
- Store the fixture output at `backend/fixtures/example_analysis_input.json` after a successful real run

---

### Sub-Task 4 — IBM Granite Integration Layer

**Status:** `[ ] pending`

**Intent**  
Connect the evidence package to IBM Granite via watsonx.ai, enforce structured JSON output, validate and retry on malformed responses, and fall back gracefully when the model is unavailable. The model layer must be fully swappable behind a single interface.

**Expected Outcomes**
- `backend/pipeline/granite.py` exposes one public function `analyze(input: AnalysisInput) -> AnalysisOutput`
- When `USE_MOCK_AI=true`, returns the example fixture without any API call
- When `USE_MOCK_AI=false`, calls watsonx.ai with the correct model ID and credentials from config
- Malformed model output triggers one retry with validation feedback appended to the prompt
- If retry fails, returns a safe partial response (summary + scores only, empty feedback list) rather than crashing
- Three different `AnalysisInput` fixtures all produce schema-valid `AnalysisOutput` responses
- No feedback timestamp exceeds video duration

**Todo List**
1. Create `backend/pipeline/granite.py` with `analyze(input: AnalysisInput) -> AnalysisOutput`
2. Build the system prompt: instruct Granite to act as a collaborative creative director; forbid invented evidence, timestamps, or metrics; require all feedback items to cite at least one `Finding` ID; return JSON only
3. Build the user prompt: serialize `AnalysisInput` to a concise human-readable block (project brief first, then findings summary, then transcript segments)
4. Call `ibm-watsonx-ai` SDK: `ModelInference` with `model_id` from config, `project_id` from config, `params` with `max_new_tokens` and `temperature`
5. Parse the response: extract JSON from the model output text, attempt `AnalysisOutput.model_validate()`
6. On `ValidationError`: append the error message to the prompt and retry once
7. On second failure: log the raw model output and return a safe partial `AnalysisOutput` with `summary="Analysis partially failed"`, zeroed scores, empty lists
8. Post-validation clamp: reject any `timeline_feedback` item whose `start` or `end` exceeds `input.video.duration_seconds`
9. Record model name, latency, and token count in structured logs (never log the API key)
10. Create `backend/fixtures/` directory with three varied `AnalysisInput` JSON files for testing
11. Create `backend/tests/test_granite.py` — mock the watsonx API call; test valid response, malformed response triggering retry, second failure triggering fallback, and timestamp clamping

**Relevant Context**
- IBM SDK: `pip install ibm-watsonx-ai`
- `USE_MOCK_AI=true` must make all tests pass with zero IBM credentials
- Prompt requirements: `Plan Schematics/ML_Backend_Lead_Tasks.pdf` pages 5–6
- The interface must be swappable — if watsonx is unavailable the mock path is one config flag change

---

### Sub-Task 5 — Live Analysis Endpoint and Frontend Integration

**Status:** `[ ] pending`

**Intent**  
Wire the extractor and Granite layer into the `/analyze` endpoint, expose real results to the frontend, add polling/status support, and fix any CORS or serialization issues found during integration.

**Expected Outcomes**
- `POST /api/projects/{id}/analyze` triggers the full real pipeline end-to-end
- `GET /api/projects/{id}/status` returns accurate progress (not just a stub)
- `GET /api/projects/{id}/analysis` returns the real `AnalysisOutput` once complete
- Upload-to-feedback works through the browser twice in a row without errors
- Result is cached — re-calling `/analysis` does not re-run the pipeline

**Todo List**
1. Add `asyncio` background task to `/analyze` — store status in the project state dict; update through `queued → processing → completed/failed`
2. Persist the completed `AnalysisOutput` to `UPLOAD_DIR/{id}/analysis_output.json` so it survives a process restart during demo
3. Update `/status` to read from the project state dict and return a human-readable `progress_message`
4. Update `/analysis` to load from the persisted file if state is `completed`
5. Fix any serialization mismatches found during browser testing — ensure all `float` timestamps serialize as numbers not strings
6. Confirm CORS headers allow the frontend origin for all methods
7. Add a 60-second timeout to the analysis background task — set status to `failed` with a clear message if exceeded
8. Run the full upload-to-results flow manually with a real test video and confirm the frontend renders markers correctly

**Relevant Context**
- Do not add a database — in-memory dict + JSON file persistence is enough for MVP
- If analysis takes >10 seconds, the frontend will poll `/status` — make sure polling does not trigger re-analysis
- Result caching: if `analysis_output.json` already exists for a project, `/analyze` should return early with `status: completed`

---

### Sub-Task 6 — Silence Removal Edit Pipeline

**Status:** `[ ] pending`

**Intent**  
Implement the one required automatic edit: silence removal. When the frontend approves the silence-removal recommendation, the backend trims the detected silence gaps from the video using FFmpeg and produces a playable preview file.

**Expected Outcomes**
- `POST /api/projects/{id}/edits` with `edit_type: silence_removal` triggers FFmpeg processing
- `GET /api/projects/{id}/preview` returns a URL to the rendered file once complete
- The preview file is a valid playable video
- The endpoint reports progress and handles FFmpeg errors without crashing the server

**Todo List**
1. Create `backend/pipeline/editor.py` with `apply_silence_removal(video_path: str, silence_findings: list[Finding]) -> str` — returns the output file path
2. Build the FFmpeg filter graph: use silence gap timestamps from the `Finding` list to construct a `select`/`aselect` filter that cuts those segments
3. Output to `UPLOAD_DIR/{id}/preview.*` — same container format as the input
4. Update `/edits` endpoint to validate that only `silence_removal` is supported in MVP; queue the render as a background task
5. Update `/preview` endpoint to check render status and return the file URL when ready, or `status: processing`
6. Serve the preview file as a static file from FastAPI using `StaticFiles`
7. Add a render timeout (120 seconds) — set preview status to `failed` with a message if exceeded
8. Create `backend/tests/test_editor.py` — use a short synthetic video with a known silence gap, assert the output is shorter than the input

**Relevant Context**
- Silence gap timestamps come from the `Finding` list produced in Sub-Task 3, not re-detected at edit time
- Only `silence_removal` is in scope for MVP — the endpoint must reject other edit types with a clear error
- Output file must be browser-playable — use H.264/AAC in mp4 container

---

### Sub-Task 7 — Integration Freeze and End-to-End Validation

**Status:** `[ ] pending`

**Intent**  
Verify that the complete happy path works on a fresh clone, all secrets and hard-coded paths are removed, and the official demo fixture is deterministic and precomputed.

**Expected Outcomes**
- A teammate can clone the repo, follow `README` setup steps, and complete the demo flow with no manual intervention
- No API key, local absolute path, or private media file is committed
- The official demo sample video + precomputed analysis fixture are committed to `sample_media/`
- All tests pass from `pytest backend/tests/`
- `ARCHITECTURE.md` and `API_CONTRACT.md` are filled in and accurate

**Todo List**
1. Do a fresh-clone simulation: follow only the written setup instructions; fix any step that fails
2. Search the entire repo for hard-coded absolute paths and replace with config-relative paths
3. Run `git grep` for any secret-like strings — confirm `.gitignore` covers `.env` and `UPLOAD_DIR`
4. Commit one sample video (≤30 seconds, royalty-free) to `sample_media/` with its pre-run `analysis_input.json` and `analysis_output.json`
5. Write `docs/ARCHITECTURE.md` from the actual running code — include the pipeline flow, module boundaries, and which IBM services are used where
6. Write `docs/API_CONTRACT.md` from the actual endpoint signatures — include request/response shapes and error envelopes
7. Run the full test suite and fix any failures
8. Confirm the mock path (`USE_MOCK_AI=true`) produces a complete demo flow with no IBM credentials

**Relevant Context**
- Architecture diagram inputs are needed by the frontend lead for the README — deliver `docs/ARCHITECTURE.md` by end of this task
- `API_CONTRACT.md` was already placeholder-created — fill it in, do not rewrite the file from scratch
- `DECISIONS.md` was already placeholder-created — add a brief entry for each major architectural choice made during the build

---

## Environment Variables Reference

All variables go in `.env` (never committed) and `.env.example` (committed with no values):

| Variable | Purpose | Default |
|---|---|---|
| `UPLOAD_DIR` | Where video files are stored | `./uploads` |
| `MAX_UPLOAD_BYTES` | Max video file size | `524288000` (500 MB) |
| `WATSONX_API_KEY` | IBM Cloud API key | — |
| `WATSONX_PROJECT_ID` | watsonx.ai project ID | — |
| `WATSONX_URL` | watsonx.ai endpoint URL | `https://us-south.ml.cloud.ibm.com` |
| `GRANITE_MODEL_ID` | Granite model identifier | `ibm/granite-3-3-8b-instruct` |
| `USE_MOCK_AI` | Skip real IBM calls during dev | `true` |
| `FRONTEND_ORIGIN` | CORS allowed origin | `http://localhost:3000` |

---

## Install Commands (to document in README)

```bash
# Prerequisites: Python 3.12, FFmpeg on PATH, git
cd backend
python -m venv ../.venv
../.venv/Scripts/activate      # Windows
# source ../.venv/bin/activate  # Mac/Linux
pip install -r requirements.txt
cp ../.env.example ../.env     # then fill in real values
uvicorn main:app --reload
```

---

## Required pip Packages

```
fastapi
uvicorn[standard]
pydantic>=2.0
pydantic-settings
python-multipart
ffmpeg-python
opencv-python-headless
ibm-watsonx-ai
pytest
httpx
```
