import asyncio
import json
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.agent_graph import get_app
from backend.config import config_manager
from backend.database import DB_PATH, get_connection, init_db
from backend.tools.db_tools import (
    DBCellGetTool,
    DBCellUpdateTool,
    DBRowDeleteTool,
    DBRowInsertTool,
    DBRowUpdateTool,
)
from backend.tools.schema_tools import (
    GetTableSchemaTool,
    add_column,
    drop_column,
    get_table_columns,
    get_table_metadata,
    is_valid_identifier as schema_is_valid_identifier,
    quote_identifier as schema_quote_identifier,
    rename_column,
    save_table_metadata,
    table_exists,
)

# LangGraph / SQLite 内部表，不暴露给用户
INTERNAL_TABLES = {
    "checkpoints",
    "writes",
    "checkpoint_blobs",
    "checkpoint_migrations",
    "_table_metadata",
    "_app_config",
}

# 服务端 session 历史（内存存储）
_session_history: dict[str, list] = {}
_session_active_table: dict[str, str] = {}
MAX_HISTORY = 20

# 待用户确认的执行任务
_pending_executions: dict[str, dict] = {}
_PENDING_CONFIRM_TTL_SECONDS = 60 * 10

PROTECTED_SYSTEM_COLUMNS = {"id", "uuid", "创建时间", "更新时间"}
ALL_SYSTEM_COLUMNS = PROTECTED_SYSTEM_COLUMNS | {"created_at", "updated_at"}

_IDENTIFIER_RE = re.compile(r"^(?!\d)[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*$")
_ALLOWED_COLUMN_TYPES = {"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"}
_FORBIDDEN_WHERE_TOKENS = re.compile(
    r"(;|--|/\*|\*/|\b(drop|alter|attach|detach|pragma|vacuum|reindex|create|replace)\b)",
    re.IGNORECASE,
)
_FORBIDDEN_ALTER_SQL_TOKENS = re.compile(
    r"(;|--|/\*|\*/|\b(attach|detach|pragma|vacuum|reindex|create|replace)\b)",
    re.IGNORECASE,
)

PATCH_TYPE_TO_HINT = {
    "table_overview": "table_overview",
    "active_table": "active_table",
    "schema": "schema",
    "rows": "rows",
}

CONFIRMABLE_INTENTS = {
    "insert",
    "update",
    "drop_table",
    "alter_table",
    "delete_data",
    "row_insert",
    "row_update",
    "row_delete",
    "add_col",
    "drop_col",
    "rename_col",
    "cell_update",
}

# Agent 节点中文标签
NODE_LABELS: dict[str, str] = {
    "router": "意图识别",
    "db_agent": "数据库智能体",
    "table_agent": "数据表智能体",
    "planner": "制定提取计划",
    "no_table_handler": "自动创建匹配表",
    "extractor": "数据提取",
    "critic": "质量检查",
    "confirm_preview": "生成操作预览",
    "executor": "执行写入",
    "query": "生成回复",
    "create_table": "创建表",
    "drop_table": "解析删除请求",
    "alter_table": "解析结构修改",
    "delete_data": "解析删除数据",
    "list_tables": "列出所有表",
    "error_end": "处理异常",
}


def _get_max_history() -> int:
    try:
        value = int(config_manager.get("max_history_length", MAX_HISTORY))
    except (TypeError, ValueError):
        return MAX_HISTORY
    return max(1, min(value, 200))


def _append_session_history(session_id: str, entries: list[dict]):
    hist = _session_history.get(session_id, [])
    hist = hist + entries
    _session_history[session_id] = hist[-_get_max_history() :]


def _active_session_count() -> int:
    return len(_session_history)


def _pending_confirmation_count() -> int:
    return len(_pending_executions)


def _health_db_status() -> dict:
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _health_config_status() -> dict:
    llm = config_manager.get_llm_params()
    return {
        "model": llm.get("model"),
        "has_api_key": bool(llm.get("api_key")),
        "base_url": llm.get("base_url"),
    }


def _cleanup_expired_pending():
    now = int(time.time())
    expired = []
    for sid, payload in _pending_executions.items():
        ts = int(payload.get("timestamp") or 0)
        if ts and now - ts > _PENDING_CONFIRM_TTL_SECONDS:
            expired.append(sid)
    for sid in expired:
        _pending_executions.pop(sid, None)


def _is_valid_identifier(name: str) -> bool:
    return bool(name and _IDENTIFIER_RE.fullmatch(name)) and bool(schema_is_valid_identifier(name))


def _quote_identifier(name: str) -> str:
    if not _is_valid_identifier(name):
        raise HTTPException(status_code=400, detail=f"非法标识符: {name}")
    return schema_quote_identifier(name)


def _normalize_identifier(name: str, field_name: str = "标识符") -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail=f"{field_name}不能为空")
    if not _is_valid_identifier(normalized):
        raise HTTPException(status_code=400, detail=f"{field_name}不合法: {normalized}")
    return normalized


def _validate_where_clause(where_clause: str) -> str:
    clause = (where_clause or "").strip()
    if not clause:
        raise HTTPException(status_code=400, detail="删除条件不能为空")
    if _FORBIDDEN_WHERE_TOKENS.search(clause):
        raise HTTPException(status_code=400, detail="检测到不安全的删除条件")
    return clause


def _validate_alter_sql(sql: str) -> str:
    stmt = (sql or "").strip().rstrip(";").strip()
    if not stmt:
        raise HTTPException(status_code=400, detail="表结构修改 SQL 不能为空")
    if _FORBIDDEN_ALTER_SQL_TOKENS.search(stmt):
        raise HTTPException(status_code=400, detail="检测到不安全的表结构修改 SQL")
    if not re.match(r"^ALTER\s+TABLE\s+", stmt, flags=re.IGNORECASE):
        raise HTTPException(status_code=400, detail="仅支持 ALTER TABLE 语句")
    return stmt


def _extract_where_from_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    where = payload.get("where")
    return where if isinstance(where, dict) else {}


def _extract_data_from_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _resolve_confirm_intent(intent: str, extracted_data: dict | None, operation_spec: dict | None = None) -> str:
    normalized = (intent or "").strip()
    if normalized in CONFIRMABLE_INTENTS:
        return normalized

    op_from_spec = ""
    if isinstance(operation_spec, dict):
        op_from_spec = (operation_spec.get("op") or "").strip()
    if op_from_spec in CONFIRMABLE_INTENTS:
        return op_from_spec

    operation = ""
    if isinstance(extracted_data, dict):
        operation = (
            extracted_data.get("operation_type")
            or extracted_data.get("operation")
            or ""
        ).strip()
    if operation in CONFIRMABLE_INTENTS:
        return operation

    legacy_map = {
        "insert": "row_insert",
        "update": "row_update",
        "delete_data": "row_delete",
        "drop_table": "drop_table",
        "alter_table": "alter_table",
    }
    return legacy_map.get(normalized, "")


def _list_user_tables() -> list[str]:
    schema = GetTableSchemaTool().run()
    return [name for name in schema.keys() if name not in INTERNAL_TABLES]


def _build_spec_from_legacy(operation_intent: str, extracted_data: dict | None) -> dict:
    extracted_data = extracted_data or {}
    payload = extracted_data.get("payload") if isinstance(extracted_data, dict) else None
    payload = payload if isinstance(payload, dict) else {}

    op_map = {
        "insert": "row_insert",
        "update": "row_update",
        "delete_data": "row_delete",
    }
    op = op_map.get((operation_intent or "").strip(), (operation_intent or "").strip())
    if not op:
        op = (extracted_data.get("operation_type") or "").strip()

    return {
        "op": op,
        "table": (extracted_data.get("table") or "").strip(),
        "where": _extract_where_from_payload(payload) if payload else (extracted_data.get("where") or {}),
        "data": _extract_data_from_payload(payload) if payload else (extracted_data.get("data") or {}),
        "column": (payload.get("column") if payload else extracted_data.get("column")) or "",
        "value": payload.get("value") if payload else extracted_data.get("value"),
        "new_name": (payload.get("new_name") if payload else extracted_data.get("new_name")) or "",
        "column_type": (payload.get("column_type") if payload else extracted_data.get("column_type")) or "TEXT",
        "requires_confirmation": op in CONFIRMABLE_INTENTS,
    }


def _normalize_operation_spec(operation_spec: dict | None, extracted_data: dict | None, operation_intent: str = "") -> dict:
    extracted_data = extracted_data or {}
    legacy = _build_spec_from_legacy(operation_intent, extracted_data)
    if not isinstance(operation_spec, dict):
        return legacy

    merged = dict(legacy)
    merged.update({k: v for k, v in operation_spec.items() if v is not None})

    if not isinstance(merged.get("where"), dict):
        merged["where"] = legacy.get("where") or {}
    if not isinstance(merged.get("data"), dict):
        merged["data"] = legacy.get("data") or {}

    op = (merged.get("op") or "").strip()
    if not op:
        op = (legacy.get("op") or "").strip()
    merged["op"] = op
    merged["requires_confirmation"] = bool(merged.get("requires_confirmation", op in CONFIRMABLE_INTENTS))
    merged["table"] = (merged.get("table") or "").strip()
    merged["column"] = (merged.get("column") or "").strip()
    merged["new_name"] = (merged.get("new_name") or "").strip()
    merged["column_type"] = (merged.get("column_type") or "TEXT").strip().upper()
    return merged


def _preflight_validate_operation(spec: dict) -> dict:
    op = (spec.get("op") or "").strip()
    table = (spec.get("table") or "").strip()
    where = spec.get("where") if isinstance(spec.get("where"), dict) else {}
    data = spec.get("data") if isinstance(spec.get("data"), dict) else {}
    column = (spec.get("column") or "").strip()

    if not op:
        return {
            "ok": False,
            "code": "missing_op",
            "message": "未识别到可执行操作。",
            "suggestion": "请明确是查询、更新还是删除操作。",
            "options": [],
        }

    if op in {"chat", "query", "list", "create", "switch"}:
        return {"ok": True, "code": "ok", "message": "", "suggestion": "", "options": []}

    if not table:
        return {
            "ok": False,
            "code": "missing_table",
            "message": "缺少目标表名。",
            "suggestion": "请先选择要操作的表。",
            "options": _list_user_tables(),
        }

    if not table_exists(table):
        return {
            "ok": False,
            "code": "table_not_found",
            "message": f"目标表「{table}」不存在。",
            "suggestion": "请确认表名，或先执行列出表。",
            "options": _list_user_tables(),
        }

    columns = [col["name"] for col in get_table_columns(table)]
    colset = set(columns)

    invalid_where = [k for k in where.keys() if k not in colset]
    if invalid_where:
        return {
            "ok": False,
            "code": "invalid_where_columns",
            "message": f"定位字段不存在: {', '.join(invalid_where)}",
            "suggestion": "请使用该表中存在的字段作为 where 条件。",
            "options": columns,
        }

    invalid_data = [k for k in data.keys() if k not in colset]
    if invalid_data:
        return {
            "ok": False,
            "code": "invalid_data_columns",
            "message": f"写入字段不存在: {', '.join(invalid_data)}",
            "suggestion": "请使用该表中存在的字段作为写入列。",
            "options": columns,
        }

    if op in {"row_update", "row_delete", "cell_get", "cell_update", "delete_data"} and not where:
        return {
            "ok": False,
            "code": "missing_where",
            "message": "缺少定位条件 where。",
            "suggestion": "请补充如 id=1 或 uuid=xxx 的定位条件。",
            "options": [c for c in columns if c in {"id", "uuid"}] or columns,
        }

    if op in {"row_insert", "row_update"} and not data:
        return {
            "ok": False,
            "code": "missing_data",
            "message": "缺少写入数据 data。",
            "suggestion": "请补充 字段=值 的数据内容。",
            "options": [c for c in columns if c not in ALL_SYSTEM_COLUMNS] or columns,
        }

    if op in {"cell_get", "cell_update"}:
        if not column:
            return {
                "ok": False,
                "code": "missing_column",
                "message": "缺少单元格字段 column。",
                "suggestion": "请补充要读取或更新的列名。",
                "options": columns,
            }
        if column not in colset:
            return {
                "ok": False,
                "code": "invalid_column",
                "message": f"字段「{column}」不存在。",
                "suggestion": "请从该表字段中选择。",
                "options": columns,
            }
        if op == "cell_update" and "value" not in spec:
            return {
                "ok": False,
                "code": "missing_value",
                "message": "缺少单元格新值 value。",
                "suggestion": "请补充要写入的值。",
                "options": [],
            }

    if op == "add_col":
        new_col = column
        if not new_col:
            return {
                "ok": False,
                "code": "missing_column",
                "message": "新增字段缺少 column。",
                "suggestion": "请补充要新增的字段名。",
                "options": [],
            }

    if op == "rename_col":
        if not column or not (spec.get("new_name") or "").strip():
            return {
                "ok": False,
                "code": "missing_rename_args",
                "message": "重命名字段缺少 column 或 new_name。",
                "suggestion": "请提供原字段名和新字段名。",
                "options": columns,
            }

    return {"ok": True, "code": "ok", "message": "", "suggestion": "", "options": []}


def _build_clarify_payload(preflight: dict, spec: dict) -> dict:
    return {
        "type": "clarify",
        "question": preflight.get("message") or "需要补充信息后才能继续执行。",
        "options": preflight.get("options") or [],
        "context": {
            "code": preflight.get("code") or "validation_failed",
            "suggestion": preflight.get("suggestion") or "",
            "op": spec.get("op") or "",
            "table": spec.get("table") or "",
        },
    }


def _build_clarify_text(preflight: dict) -> str:
    message = (preflight.get("message") or "需要补充信息后才能继续执行。").strip()
    suggestion = (preflight.get("suggestion") or "").strip()
    if suggestion:
        return f"{message}\n建议：{suggestion}"
    return message


def _build_step_payload(node_name: str, label: str, state: dict) -> dict:
    payload = {"type": "step", "node": node_name, "label": label}
    agent = (state.get("step_agent") or "").strip()
    phase = (state.get("step_phase") or "").strip()
    patch = state.get("step_patch")

    if agent:
        payload["agent"] = agent
    if phase:
        payload["phase"] = phase
    if isinstance(patch, dict):
        payload["patch"] = patch
    return payload


def _merge_final_patch(final_state: dict) -> dict | None:
    patches = final_state.get("ui_patches") or []
    if isinstance(patches, list) and patches:
        last = patches[-1]
        if isinstance(last, dict):
            return last
    patch = final_state.get("step_patch")
    return patch if isinstance(patch, dict) else None


def _determine_done_refresh(final_state: dict, patch: dict | None = None) -> dict:
    final_patch = patch or _merge_final_patch(final_state)
    if not final_patch:
        return {"refresh": False}

    patch_type = final_patch.get("type")
    return {
        "refresh": True,
        "hint": PATCH_TYPE_TO_HINT.get(patch_type, "rows"),
        "table": final_patch.get("table") or final_state.get("active_table") or "",
        "patch_type": patch_type,
    }


def _validate_table_and_columns(table: str, columns: list[str]):
    norm_table = _normalize_identifier(table, "表名")
    if norm_table in INTERNAL_TABLES:
        raise HTTPException(status_code=403, detail="不允许操作系统内部表")
    if not table_exists(norm_table):
        raise HTTPException(status_code=404, detail=f"表 '{norm_table}' 不存在")

    existing = {col["name"] for col in get_table_columns(norm_table)}
    for col in columns:
        norm_col = _normalize_identifier(col, "字段名")
        if norm_col not in existing:
            raise HTTPException(status_code=400, detail=f"字段不存在: {norm_col}")


def _execute_operation(
    operation_intent: str,
    extracted_data: dict | None,
    operation_spec: dict | None = None,
) -> tuple[str, dict | None, str | None]:
    spec = _normalize_operation_spec(operation_spec, extracted_data, operation_intent)
    intent = (spec.get("op") or operation_intent or "").strip()

    table = _normalize_identifier((spec.get("table") or "").strip(), "表名")
    where = spec.get("where") if isinstance(spec.get("where"), dict) else {}
    data = spec.get("data") if isinstance(spec.get("data"), dict) else {}
    column = (spec.get("column") or "").strip()
    value = spec.get("value")

    if intent in {"insert", "row_insert"}:
        _validate_table_and_columns(table, list(data.keys()))
        result = DBRowInsertTool().run(table=table, data=data)
        patch = {"type": "rows", "table": table, "refresh": True}
        return f"✅ 数据已插入表「{table}」，ID: {result.get('rowid')}", patch, "row_insert"

    if intent in {"update", "row_update"}:
        _validate_table_and_columns(table, list(data.keys()) + list(where.keys()))
        result = DBRowUpdateTool().run(table=table, where=where, data=data)
        patch = {"type": "rows", "table": table, "refresh": True}
        return f"✅ 已更新表「{table}」，影响行数: {result.get('rows_affected')}", patch, "row_update"

    if intent in {"delete_data", "row_delete"}:
        if where:
            _validate_table_and_columns(table, list(where.keys()))
            result = DBRowDeleteTool().run(table=table, where=where)
            patch = {"type": "rows", "table": table, "refresh": True}
            return f"✅ 已从表「{table}」删除 {result.get('rows_affected')} 条记录", patch, "row_delete"

        where_clause = (extracted_data or {}).get("where_clause", "")
        safe_clause = _validate_where_clause(where_clause)
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {_quote_identifier(table)} WHERE {safe_clause}")
            rows = cursor.rowcount
            conn.commit()
        finally:
            conn.close()
        patch = {"type": "rows", "table": table, "refresh": True}
        return f"✅ 已从表「{table}」删除 {rows} 条记录", patch, "row_delete"

    if intent == "drop_table":
        if table in INTERNAL_TABLES:
            raise HTTPException(status_code=403, detail="不允许操作系统内部表")
        conn = get_connection()
        try:
            conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(table)}")
            conn.commit()
        finally:
            conn.close()
        patch = {"type": "table_overview", "refresh": True, "active_table": ""}
        return f"✅ 已删除表「{table}」", patch, "drop_table"

    if intent in {"alter_table", "add_col", "drop_col", "rename_col"}:
        if table in INTERNAL_TABLES:
            raise HTTPException(status_code=403, detail="不允许操作系统内部表")

        if intent == "add_col":
            col = _normalize_identifier(column, "字段名")
            col_type = (spec.get("column_type") or "TEXT").strip().upper()
            add_column(table, col, col_type, bool(spec.get("notnull", False)), str(spec.get("default", "")))
            patch = {"type": "schema", "table": table, "refresh": True}
            return f"✅ 已在表「{table}」新增字段「{col}」", patch, "add_col"

        if intent == "drop_col":
            col = _normalize_identifier(column, "字段名")
            drop_column(table, col)
            patch = {"type": "schema", "table": table, "refresh": True}
            return f"✅ 已从表「{table}」删除字段「{col}」", patch, "drop_col"

        if intent == "rename_col":
            old = _normalize_identifier(column, "原字段名")
            new = _normalize_identifier((spec.get("new_name") or ""), "新字段名")
            rename_column(table, old, new)
            patch = {"type": "schema", "table": table, "refresh": True}
            return f"✅ 已将表「{table}」字段「{old}」重命名为「{new}」", patch, "rename_col"

        sqls = (extracted_data or {}).get("sqls", [])
        if not isinstance(sqls, list) or not sqls:
            raise HTTPException(status_code=400, detail="缺少有效的表结构修改语句")

        conn = get_connection()
        try:
            for sql in sqls:
                safe_sql = _validate_alter_sql(sql)
                conn.execute(safe_sql)
            conn.commit()
        finally:
            conn.close()
        patch = {"type": "schema", "table": table, "refresh": True}
        return f"✅ 表结构修改完成：{(extracted_data or {}).get('description', '')}", patch, "alter_table"

    if intent == "cell_get":
        col = _normalize_identifier(column, "字段名")
        _validate_table_and_columns(table, list(where.keys()) + [col])
        result = DBCellGetTool().run(table=table, where=where, column=col)
        patch = {"type": "rows", "table": table, "refresh": False}
        message = f"✅ 单元格查询结果：表「{table}」中 {where} 的「{col}」= {result.get('value')}"
        return message, patch, "cell_get"

    if intent == "cell_update":
        col = _normalize_identifier(column, "字段名")
        _validate_table_and_columns(table, list(where.keys()) + [col])
        DBCellUpdateTool().run(table=table, where=where, column=col, value=value)
        patch = {"type": "rows", "table": table, "refresh": True}
        return f"✅ 已更新表「{table}」中 {where} 的「{col}」", patch, "cell_update"

    raise HTTPException(status_code=400, detail=f"不支持的操作类型: {intent}")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_text(text: str, delay: float = 0.008) -> AsyncGenerator[str, None]:
    for char in text:
        yield _sse({"type": "token", "content": char})
        await asyncio.sleep(delay)


load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    await get_app()
    yield


app = FastAPI(title="DBot NL2CLI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str


class ChatResponse(BaseModel):
    session_id: str
    response: str
    intent: str = ""
    error: str = ""
    needs_confirmation: bool = False


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@app.get("/")
async def root():
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "DBot NL2CLI API is running. Visit /docs for API documentation."}


@app.post("/chat")
async def chat(request: ChatRequest):
    _cleanup_expired_pending()

    history = _session_history.get(request.session_id, [])
    active_table = _session_active_table.get(request.session_id, "")

    initial_state = {
        "user_input": request.message,
        "intent": "",
        "schema_info": None,
        "extraction_plan": None,
        "extracted_data": None,
        "critic_result": None,
        "retry_count": 0,
        "final_response": None,
        "error": None,
        "session_id": request.session_id,
        "chat_history": history,
        "needs_confirmation": False,
        "confirmation_preview": None,
        "newly_created_table": None,
        "is_data_related": True,
        "active_table": active_table or None,
        "target_level": None,
        "operation_type": None,
        "react_steps": [],
        "ui_patches": [],
        "step_agent": "",
        "step_phase": "",
        "step_patch": None,
    }
    config = {"configurable": {"thread_id": request.session_id}}

    async def generate():
        langgraph_app = await get_app()
        final_state: dict = {}

        try:
            async for chunk in langgraph_app.astream(initial_state, config=config):
                for node_name, output in chunk.items():
                    final_state = output if isinstance(output, dict) else {}
                    label = NODE_LABELS.get(node_name, node_name)
                    yield _sse(_build_step_payload(node_name, label, final_state))
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            yield _sse({"type": "done", "intent": "", "error": str(e), "refresh_hint": {"refresh": False}})
            return

        active = (final_state.get("active_table") or "").strip()
        if active and _is_valid_identifier(active):
            _session_active_table[request.session_id] = active

        needs_confirmation = bool(final_state.get("needs_confirmation", False))
        response_text = final_state.get("final_response") or "处理完成"
        intent = final_state.get("intent", "")

        if needs_confirmation:
            resolved_intent = _resolve_confirm_intent(intent, final_state.get("extracted_data") or {})
            if not resolved_intent:
                err = "待确认操作缺少有效类型"
                yield _sse({"type": "error", "message": err})
                yield _sse({"type": "done", "intent": intent or "", "error": err, "refresh_hint": {"refresh": False}})
                return

            _pending_executions[request.session_id] = {
                "extracted_data": final_state.get("extracted_data") or {},
                "intent": resolved_intent,
                "active_table": active,
                "ui_patches": list(final_state.get("ui_patches") or []),
                "timestamp": int(time.time()),
            }
            yield _sse({"type": "confirm", "response": response_text, "intent": resolved_intent})
        else:
            yield _sse({"type": "response_start"})
            async for chunk in _stream_text(response_text):
                yield chunk

            _append_session_history(
                request.session_id,
                [
                    {"role": "user", "content": request.message},
                    {"role": "assistant", "content": response_text},
                ],
            )

        final_patch = _merge_final_patch(final_state)
        done_refresh = {"refresh": False} if needs_confirmation else _determine_done_refresh(final_state, final_patch)
        yield _sse(
            {
                "type": "done",
                "intent": intent,
                "error": final_state.get("error") or "",
                "refresh_hint": done_refresh,
                "active_table": final_state.get("active_table") or "",
            }
        )

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/schema")
async def get_schema():
    tool = GetTableSchemaTool()
    schema = {k: v for k, v in tool.run().items() if k not in INTERNAL_TABLES}
    return {"schema": schema}


# ── 表管理 API ──────────────────────────────────────────────

@app.get("/tables")
async def list_tables():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        table_names = [row[0] for row in cursor.fetchall() if row[0] not in INTERNAL_TABLES]
        metadata = get_table_metadata()
        tables = []
        for name in table_names:
            meta = metadata.get(name, {})
            tables.append(
                {
                    "name": name,
                    "description": meta.get("description", ""),
                    "aliases": meta.get("aliases", []),
                }
            )
        return {"tables": tables}
    finally:
        conn.close()


@app.get("/tables/{table_name}")
async def get_table_data(table_name: str):
    table_name = _normalize_identifier(table_name, "表名")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"表 '{table_name}' 不存在")

        quoted_table = _quote_identifier(table_name)
        cursor.execute(f"PRAGMA table_info({quoted_table})")
        columns = [
            {"name": row[1], "type": row[2], "notnull": bool(row[3]), "pk": bool(row[5])}
            for row in cursor.fetchall()
        ]

        cursor.execute(f"SELECT * FROM {quoted_table} ORDER BY rowid DESC LIMIT 500")
        rows = [dict(row) for row in cursor.fetchall()]
        return {"table": table_name, "columns": columns, "rows": rows}
    finally:
        conn.close()


@app.delete("/tables/{table_name}")
async def delete_table(table_name: str):
    table_name = _normalize_identifier(table_name, "表名")
    if table_name in INTERNAL_TABLES:
        raise HTTPException(status_code=403, detail="不允许删除系统内部表")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"表 '{table_name}' 不存在")
        cursor.execute(f"DROP TABLE {_quote_identifier(table_name)}")
        conn.commit()
        return {"success": True, "message": f"表 '{table_name}' 已删除"}
    finally:
        conn.close()


class ColumnDef(BaseModel):
    name: str
    type: str = "TEXT"
    notnull: bool = False
    default: str = ""


class CreateTableRequest(BaseModel):
    table_name: str
    columns: List[ColumnDef]
    description: str = ""
    aliases: List[str] = []


@app.post("/tables")
async def create_table(request: CreateTableRequest):
    name = _normalize_identifier(request.table_name, "表名")
    if name in INTERNAL_TABLES:
        raise HTTPException(status_code=403, detail="表名与系统保留名冲突")

    all_defs = [
        "id INTEGER PRIMARY KEY AUTOINCREMENT",
        "uuid TEXT DEFAULT (lower(hex(randomblob(16))))",
        "创建时间 TEXT DEFAULT (datetime('now', 'localtime'))",
        "更新时间 TEXT DEFAULT (datetime('now', 'localtime'))",
    ]

    for col in request.columns:
        col_name = _normalize_identifier(col.name, "字段名")
        if col_name in PROTECTED_SYSTEM_COLUMNS:
            raise HTTPException(status_code=400, detail=f"字段名为系统保留字段: {col_name}")

        col_type = (col.type or "TEXT").strip().upper()
        if col_type not in _ALLOWED_COLUMN_TYPES:
            raise HTTPException(status_code=400, detail=f"不支持的字段类型: {col_type}")

        col_sql = f"{_quote_identifier(col_name)} {col_type}"
        if col.notnull:
            col_sql += " NOT NULL"
        if col.default:
            escaped_default = str(col.default).replace("'", "''")
            col_sql += f" DEFAULT '{escaped_default}'"
        all_defs.append(col_sql)

    sql = f"CREATE TABLE IF NOT EXISTS {_quote_identifier(name)} ({', '.join(all_defs)})"

    conn = get_connection()
    try:
        conn.execute(sql)
        conn.commit()
        save_table_metadata(name, request.description, request.aliases)
        return {"success": True, "message": f"表 '{name}' 创建成功", "sql": sql}
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@app.post("/confirm/{session_id}")
async def confirm_execution(session_id: str):
    _cleanup_expired_pending()

    pending = _pending_executions.pop(session_id, None)
    if not pending:

        async def _not_found():
            yield _sse({"type": "error", "message": "没有待确认的操作，可能已超时或已处理"})
            yield _sse({"type": "done", "intent": "", "error": "not_found", "refresh_hint": {"refresh": False}})

        return StreamingResponse(_not_found(), media_type="text/event-stream", headers=SSE_HEADERS)

    extracted_data = pending.get("extracted_data") or {}
    intent = pending.get("intent") or ""

    async def generate():
        try:
            yield _sse({"type": "step", "node": "confirm_execution", "label": "执行确认操作", "agent": "数据表智能体", "phase": "action"})

            response_text, patch, final_intent = _execute_operation(intent, extracted_data)

            table_for_session = ""
            if isinstance(patch, dict) and patch.get("type") == "active_table":
                table_for_session = (patch.get("table") or "").strip()
            elif isinstance(extracted_data, dict):
                table_for_session = (extracted_data.get("table") or "").strip()

            if table_for_session and _is_valid_identifier(table_for_session):
                _session_active_table[session_id] = table_for_session

            if isinstance(patch, dict):
                yield _sse(
                    {
                        "type": "step",
                        "node": "confirm_execution",
                        "label": "已生成界面补丁",
                        "agent": "数据表智能体",
                        "phase": "observation",
                        "patch": patch,
                    }
                )

            _append_session_history(session_id, [{"role": "assistant", "content": response_text}])

            yield _sse({"type": "response_start"})
            async for chunk in _stream_text(response_text):
                yield chunk

            final_state = {
                "active_table": table_for_session or pending.get("active_table") or "",
                "ui_patches": [patch] if isinstance(patch, dict) else [],
            }
            yield _sse(
                {
                    "type": "done",
                    "intent": final_intent or intent,
                    "error": "",
                    "refresh_hint": _determine_done_refresh(final_state, patch),
                    "active_table": final_state.get("active_table") or "",
                }
            )
        except Exception as e:
            message = e.detail if isinstance(e, HTTPException) else str(e)
            yield _sse({"type": "error", "message": message})
            yield _sse({"type": "done", "intent": intent, "error": message, "refresh_hint": {"refresh": False}})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/cancel/{session_id}")
async def cancel_execution(session_id: str):
    _pending_executions.pop(session_id, None)
    return {"success": True, "response": "操作已取消"}


@app.get("/health")
async def health():
    db_status = _health_db_status()
    overall = "ok" if db_status.get("ok") else "degraded"
    return {
        "status": overall,
        "service": "DBot NL2CLI",
        "db": db_status,
        "config": _health_config_status(),
        "active_sessions": _active_session_count(),
        "pending_confirmations": _pending_confirmation_count(),
        "max_history_length": _get_max_history(),
        "db_path": DB_PATH,
    }


# ── 配置管理 API ──────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    key: str
    value: Any
    description: str = ""


class ConfigTestRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None


@app.get("/config")
async def get_config():
    return config_manager.get_all()


@app.put("/config")
async def update_config(update: ConfigUpdate):
    success = config_manager.update(update.key, update.value, update.description)
    if not success:
        raise HTTPException(status_code=400, detail="配置更新失败，请检查参数类型和取值范围")
    return {"success": True}


@app.post("/config/batch")
async def batch_update_config(updates: List[ConfigUpdate]):
    update_dict = {item.key: item.value for item in updates}
    success = config_manager.batch_update(update_dict)
    if not success:
        raise HTTPException(status_code=400, detail="批量配置更新失败，请检查参数类型和取值范围")
    return {"success": True, "updated": len(updates)}


@app.post("/config/test")
async def test_config(test_request: Optional[ConfigTestRequest] = None):
    if test_request is None:
        test_config_params = None
    else:
        test_config_params = {k: v for k, v in test_request.model_dump().items() if v is not None}

    result = config_manager.test_connection(test_config_params)
    return result


@app.delete("/config/{key}")
async def reset_config(key: str):
    success = config_manager.reset_to_default(key)
    return {"success": success}
