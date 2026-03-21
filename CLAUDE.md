# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

### Setup
- Install Python dependencies: `python -m pip install -r requirements.txt`
- Create `.env` from `.env.example` and fill in API keys
- Required env vars:
  - `DEEPSEEK_API_KEY`: DeepSeek API key (primary LLM provider)
  - `DEEPSEEK_BASE_URL`: DeepSeek endpoint (default: `https://api.deepseek.com/v1`)
  - `DEEPSEEK_MODEL`: Model name (default: `deepseek-chat`)
  - `OPENAI_API_KEY`: OpenAI API key (optional, legacy)
  - `DB_PATH`: SQLite database path (default: `./dataspeak.db`)
  - `DEFAULT_LLM_PROVIDER`: `deepseek` or `openai` (default: `deepseek`)
  - `AUTO_EXECUTE_ENABLED`: Auto-execute safe tool calls (default: `false`)

### Run backend
```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --app-dir . --reload
```
- App root: `http://127.0.0.1:8000/`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

### Run React frontend (dev)
```bash
cd frontend-react && npm install && npm run dev
```
- Dev server: `http://localhost:3000`
- Vite proxies `/api/*` → `http://127.0.0.1:8001/v2/*` (note: proxy target port is 8001, backend runs on 8000 — adjust as needed)

### Database reset
```bash
rm -f ./dataspeak.db
```
DB is auto-initialized on next startup via `backend/database.py:init_db()`.

### Syntax checks (no test suite yet)
```bash
python -m py_compile backend/main.py
node --check frontend-react/src/App.jsx
```

## Architecture

### Overview
DBot is a natural-language-to-database tool. Users chat in natural language; the system uses DeepSeek (or OpenAI) function calling to translate intent into SQLite operations.

**Two frontend versions exist:**
- `frontend/` — legacy plain HTML/CSS/JS, served as static files by FastAPI at `/static`
- `frontend-react/` — new React+Vite SPA (in progress), runs separately on port 3000

### Backend structure (`backend/`)

```
backend/
├── main.py              # FastAPI app, all /v2/* endpoints, lifespan, CORS
├── config.py            # ExtendedConfigManager — multi-provider LLM config (.env + DB _app_config)
├── database.py          # SQLite init (todos, _table_metadata), get_connection()
├── state.py             # Dataclasses: ChatSession, ToolCall, Confirmation, Message, ChatRequest/Response
├── handlers/
│   └── chat_handler.py  # ChatHandler + SessionManager — full chat workflow orchestration
├── services/
│   └── deepseek_service.py  # DeepSeekService — OpenAI-compatible API calls, tool parsing, serialization
└── tools/
    ├── registry.py      # ToolRegistry — registration, confirmation logic, auto-execute config
    ├── init_tools.py    # Registers all tools at import time, provides get_tools_for_llm()
    ├── db_tools.py      # Data CRUD: insert_row, update_row, delete_row, query_data, get/update_cell_value
    └── schema_tools.py  # DDL: create_table, drop_table, add/drop/rename_column, get_schema, list_tables
```

### Request flow
1. `POST /v2/chat` → `ChatHandler.handle_chat()`
2. Builds message history from `ChatSession`, calls DeepSeek with tool schemas
3. If tool_calls returned → check confirmation need → auto-execute or await `/v2/confirm`
4. Tool results fed back to LLM for final natural-language response

### Key design patterns
- **Tool registry** (`init_tools.py`): All tools registered at module import with OpenAI-compatible JSON Schema. Each tool has `confidence_level` (SAFE/RISKY/DESTRUCTIVE) and `requires_confirmation` flag.
- **Confirmation flow**: RISKY/DESTRUCTIVE tools require user approval. `ChatSession.pending_confirmation` holds staged `ToolCall` objects until `/v2/confirm` approves or rejects.
- **Auto-execute mode**: Configurable via env/DB config. Only SAFE tools in the allow-list can auto-execute.
- **Session management**: In-memory `SessionManager` — sessions are lost on restart. Hourly cleanup of idle sessions.
- **Config merging**: `.env` defaults → `_app_config` DB table overrides. `ExtendedConfigManager` singleton.

### API endpoints
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v2/chat` | Chat with tool calling |
| POST | `/v2/confirm` | Approve/reject pending operations |
| GET | `/v2/tables` | List all user tables with columns |
| GET | `/v2/tables/{name}` | Query table data |
| POST | `/v2/tables` | Create table |
| DELETE | `/v2/tables/{name}` | Drop table |
| GET | `/v2/config` | Get config (masked secrets) |
| PUT | `/v2/config` | Update config |
| POST | `/v2/config/test` | Test LLM connection |
| GET | `/v2/sessions/{id}` | Session info |
| PUT | `/v2/sessions/{id}/auto-execute` | Toggle auto-execute |

### Internal SQLite tables (excluded from user display)
`checkpoints`, `writes`, `checkpoint_blobs`, `checkpoint_migrations`, `_table_metadata`, `_app_config`

### Coordination points when changing behavior
- **Adding tools**: `backend/tools/db_tools.py` or `schema_tools.py` (impl + schema) → `init_tools.py` (register) → `registry.py` (confirmation message template)
- **Changing confirmation flow**: `registry.py` + `chat_handler.py._check_confirmation_need()` + `main.py:/v2/confirm` + frontend confirm UI
- **Adding API endpoints**: `backend/main.py` + `frontend-react/src/services/apiService.js`

### Known issues / in-progress
- React frontend dependencies not installed; Vite proxy targets port 8001 but backend defaults to 8000
- `frontend-react/src/services/apiService.js` may reference endpoints not yet implemented on backend
- `backup-old-architecture/` contains the original LangGraph-based agent system (kept for reference)
- `.env.example` contains a real-looking API key — should be replaced with placeholders
