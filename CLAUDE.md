# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

### Setup
- Install dependencies:
  - `python -m pip install -r requirements.txt`

### Run the app (backend + frontend static files)
- From repo root:
  - `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --app-dir .`
- Open:
  - App UI: `http://127.0.0.1:8000/`
  - API docs: `http://127.0.0.1:8000/docs`
  - Health: `http://127.0.0.1:8000/health`

### Database reset (common during local development)
- DB file is controlled by `DB_PATH` (default `./dataspeak.db`)
- Reset and re-init on next startup:
  - `rm -f ./dataspeak.db`

### Checks used in this repo
- There is currently no configured pytest/lint toolchain in the repo.
- Common targeted checks:
  - Python syntax check: `python -m py_compile backend/main.py`
  - JS syntax check: `node --check frontend/app.js`
- If/when pytest tests are added, run one test with:
  - `python -m pytest path/to/test_file.py::test_name`

## High-level architecture

## Overview
- Single-process FastAPI app serves both API and static frontend (`backend/main.py`).
- Core logic is a LangGraph workflow with multiple intent-specific agents (`backend/agent_graph.py`).
- Storage is SQLite (`dataspeak.db` by default) plus in-memory session state for chat history and pending confirmations.

## Request/response flow
- `POST /chat`:
  - Builds initial `DataSpeakState` with `chat_history` from server memory.
  - Streams graph progress via SSE (`type: step`) as each node executes.
  - Returns either:
    - normal streamed response (`response_start` + `token` + `done`), or
    - confirmation preview (`confirm`) for write operations.
- `POST /confirm/{session_id}`:
  - Executes previously staged write operation and streams result.
- `POST /cancel/{session_id}`:
  - Cancels staged write operation.

## LangGraph workflow structure
- Entry: `router` (intent classification from user input + recent chat history).
- Intent routing:
  - `insert|update` → `planner` → `extractor` → `critic` → `confirm_preview`
  - `create_table` → `create_table`
  - `drop_table` → `drop_table` → (`confirm_preview` or direct end on parse failure)
  - `alter_table` → `alter_table` → (`confirm_preview` or direct end)
  - `delete_data` → `delete_data` → (`confirm_preview` or direct end)
  - `list_tables` → `list_tables`
  - `query|chat` → `query`
- Critic retry loop:
  - `FAIL` can re-run `extractor` up to 2 retries, then `error_end`.

## State and confirmation model
- Shared graph state type: `DataSpeakState` (`backend/state.py`).
- Confirmation is explicit:
  - `confirm_preview_node` sets `needs_confirmation=True` and human-readable preview.
  - Actual DB mutation happens only after `/confirm/{session_id}`.

## Database and metadata model
- Base tables initialized in `backend/database.py`:
  - `todos` (default user table)
  - `_table_metadata` (description + aliases for semantic matching)
- Runtime/internal tables excluded from user display:
  - `checkpoints`, `writes`, `checkpoint_blobs`, `checkpoint_migrations`, `_table_metadata`
- Schema/metadata helpers live in `backend/tools/schema_tools.py`.
- Insert/update primitives live in `backend/tools/db_tools.py`.

## Configuration model
- Runtime config manager: `backend/config.py` (`ConfigManager` singleton as `config_manager`).
- Merge order: `.env` defaults + DB overrides from `_app_config`.
- Config API endpoints in `backend/main.py`:
  - `GET /config`, `PUT /config`, `POST /config/batch`, `POST /config/test`, `DELETE /config/{key}`
- Important nuance:
  - Some agents use `config_manager.get_llm_params()`.
  - Some agents still read `OPENAI_MODEL` directly via `os.getenv`.

## Frontend architecture
- Plain HTML/CSS/JS (no frontend framework): `frontend/index.html`, `frontend/app.js`.
- Layout is now DB-focused:
  - Left: session list
  - Middle: narrower chat panel
  - Right: primary table/data panel
- `app.js` consumes SSE event types: `step`, `response_start`, `token`, `confirm`, `done`, `error`.
- Settings are in a modal (`#settings-modal`) and persisted in `localStorage`.

## Coordination points when changing behavior
- Adding/changing intents usually requires synchronized edits in:
  - `backend/agents/router_agent.py` (prompt + parsing)
  - `backend/agent_graph.py` (routing conditions + graph edges)
  - `backend/main.py` (`NODE_LABELS`, refresh behavior assumptions)
  - `frontend/app.js` (intent-based table refresh logic)
- Changing write-confirmation behavior requires updates across:
  - `confirm_preview_node` in `backend/agent_graph.py`
  - `/confirm/{session_id}` and pending state handling in `backend/main.py`
  - confirm card + actions in `frontend/app.js`

## Repo-specific notes
- No README/cursor/copilot instruction files were found at the time this guide was generated.
- `config.yaml` exists but is not part of this FastAPI runtime path in current code.