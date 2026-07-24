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
