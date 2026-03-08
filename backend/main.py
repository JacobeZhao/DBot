import asyncio
import json
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from typing import AsyncGenerator, List, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from backend.database import init_db, get_connection, DB_PATH
from backend.agent_graph import get_app
from backend.tools.schema_tools import GetTableSchemaTool
from backend.config import config_manager

# LangGraph / SQLite 内部表，不暴露给用户
INTERNAL_TABLES = {"checkpoints", "writes", "checkpoint_blobs", "checkpoint_migrations", "_table_metadata", "_app_config"}

# 服务端 session 历史（内存存储）
_session_history: dict[str, list] = {}
MAX_HISTORY = 20


def _get_max_history() -> int:
    try:
        value = int(config_manager.get("max_history_length", MAX_HISTORY))
    except (TypeError, ValueError):
        return MAX_HISTORY
    return max(1, min(value, 200))


def _append_session_history(session_id: str, entries: list[dict]):
    hist = _session_history.get(session_id, [])
    hist = hist + entries
    _session_history[session_id] = hist[-_get_max_history():]


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


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_COLUMN_TYPES = {"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"}
_FORBIDDEN_WHERE_TOKENS = re.compile(
    r"(;|--|/\*|\*/|\b(drop|alter|attach|detach|pragma|vacuum|reindex|create|replace)\b)",
    re.IGNORECASE,
)
_FORBIDDEN_ALTER_SQL_TOKENS = re.compile(
    r"(;|--|/\*|\*/|\b(attach|detach|pragma|vacuum|reindex|create|replace)\b)",
    re.IGNORECASE,
)


def _is_valid_identifier(name: str) -> bool:
    return bool(name and _IDENTIFIER_RE.fullmatch(name))


def _quote_identifier(name: str) -> str:
    if not _is_valid_identifier(name):
        raise HTTPException(status_code=400, detail=f"非法标识符: {name}")
    return f'"{name}"'


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


# 待用户确认的执行任务 {session_id: {extracted_data, intent}}
_pending_executions: dict[str, dict] = {}

# Agent 节点中文标签
NODE_LABELS: dict[str, str] = {
    "router":           "意图识别",
    "planner":          "制定提取计划",
    "no_table_handler": "自动创建匹配表",
    "extractor":        "数据提取",
    "critic":           "质量检查",
    "confirm_preview":  "生成操作预览",
    "executor":         "执行写入",
    "query":            "生成回复",
    "create_table":     "创建表",
    "drop_table":       "解析删除请求",
    "alter_table":      "解析结构修改",
    "delete_data":      "解析删除数据",
    "list_tables":      "列出所有表",
    "error_end":        "处理异常",
}

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

async def _stream_text(text: str, delay: float = 0.008) -> AsyncGenerator[str, None]:
    """逐字符流式输出文本"""
    for char in text:
        yield _sse({"type": "token", "content": char})
        await asyncio.sleep(delay)

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化数据库
    init_db()
    # 预热 LangGraph App
    await get_app()
    yield


app = FastAPI(title="DBot NL2CLI", lifespan=lifespan)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载前端静态文件
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
    "Connection":    "keep-alive",
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
    history = _session_history.get(request.session_id, [])
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
    }
    config = {"configurable": {"thread_id": request.session_id}}

    async def generate():
        langgraph_app = await get_app()
        final_state: dict = {}

        try:
            async for chunk in langgraph_app.astream(initial_state, config=config):
                for node_name, output in chunk.items():
                    final_state = output
                    label = NODE_LABELS.get(node_name, node_name)
                    yield _sse({"type": "step", "node": node_name, "label": label})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            return

        needs_confirmation = final_state.get("needs_confirmation", False)
        response_text = final_state.get("final_response") or "处理完成"
        intent = final_state.get("intent", "")

        if needs_confirmation:
            _pending_executions[request.session_id] = {
                "extracted_data": final_state.get("extracted_data"),
                "intent": intent,
            }
            yield _sse({"type": "confirm", "response": response_text, "intent": intent})
        else:
            # 逐字符流式输出
            yield _sse({"type": "response_start"})
            async for chunk in _stream_text(response_text):
                yield chunk

            # 更新历史
            _append_session_history(
                request.session_id,
                [
                    {"role": "user", "content": request.message},
                    {"role": "assistant", "content": response_text},
                ],
            )

        yield _sse({
            "type": "done",
            "intent": intent,
            "error": final_state.get("error") or "",
        })

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/schema")
async def get_schema():
    tool = GetTableSchemaTool()
    schema = {k: v for k, v in tool.run().items() if k not in INTERNAL_TABLES}
    return {"schema": schema}


# ── 表管理 API ──────────────────────────────────────────────

@app.get("/tables")
async def list_tables():
    """列出所有用户表（含描述和别名）"""
    from backend.tools.schema_tools import get_table_metadata
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        table_names = [row[0] for row in cursor.fetchall() if row[0] not in INTERNAL_TABLES]
        metadata = get_table_metadata()
        tables = []
        for name in table_names:
            meta = metadata.get(name, {})
            tables.append({
                "name": name,
                "description": meta.get("description", ""),
                "aliases": meta.get("aliases", []),
            })
        return {"tables": tables}
    finally:
        conn.close()


@app.get("/tables/{table_name}")
async def get_table_data(table_name: str):
    """获取指定表的列信息和全部数据"""
    if not _is_valid_identifier(table_name):
        raise HTTPException(status_code=400, detail="表名不合法")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # 验证表存在
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"表 '{table_name}' 不存在")

        quoted_table = _quote_identifier(table_name)
        cursor.execute(f"PRAGMA table_info({quoted_table})")
        columns = [{"name": row[1], "type": row[2], "notnull": bool(row[3]), "pk": bool(row[5])} for row in cursor.fetchall()]

        cursor.execute(f"SELECT * FROM {quoted_table} ORDER BY rowid DESC LIMIT 500")
        rows = [dict(row) for row in cursor.fetchall()]
        return {"table": table_name, "columns": columns, "rows": rows}
    finally:
        conn.close()


@app.delete("/tables/{table_name}")
async def delete_table(table_name: str):
    """删除指定表"""
    if not _is_valid_identifier(table_name):
        raise HTTPException(status_code=400, detail="表名不合法")
    if table_name in INTERNAL_TABLES:
        raise HTTPException(status_code=403, detail="不允许删除系统内部表")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        )
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
    """创建新表"""
    name = request.table_name.strip()
    if not _is_valid_identifier(name):
        raise HTTPException(status_code=400, detail="表名只允许字母、数字和下划线，且不能以数字开头")
    if name in INTERNAL_TABLES:
        raise HTTPException(status_code=403, detail="表名与系统保留名冲突")

    all_defs = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]

    for col in request.columns:
        col_name = (col.name or "").strip()
        if not _is_valid_identifier(col_name):
            raise HTTPException(status_code=400, detail=f"字段名不合法: {col_name}")

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

    all_defs.append("created_at TEXT DEFAULT (datetime('now', 'localtime'))")
    sql = f"CREATE TABLE IF NOT EXISTS {_quote_identifier(name)} ({', '.join(all_defs)})"

    conn = get_connection()
    try:
        conn.execute(sql)
        conn.commit()
        # 保存元数据
        from backend.tools.schema_tools import save_table_metadata
        save_table_metadata(name, request.description, request.aliases)
        return {"success": True, "message": f"表 '{name}' 创建成功", "sql": sql}
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@app.post("/confirm/{session_id}")
async def confirm_execution(session_id: str):
    """用户确认执行待处理的操作（支持 insert/update/drop_table/alter_table/delete_data）"""
    pending = _pending_executions.pop(session_id, None)
    if not pending:
        async def _not_found():
            yield _sse({"type": "error", "message": "没有待确认的操作，可能已超时或已处理"})
            yield _sse({"type": "done", "intent": "", "error": "not_found"})
        return StreamingResponse(_not_found(), media_type="text/event-stream", headers=SSE_HEADERS)

    from backend.tools.db_tools import DBInsertTool, DBUpdateTool

    extracted_data = pending["extracted_data"]
    intent = pending["intent"]

    async def generate():
        try:
            if intent == "insert":
                table = (extracted_data.get("table") or "").strip()
                if table in INTERNAL_TABLES:
                    raise HTTPException(status_code=403, detail="不允许操作系统内部表")
                data = extracted_data.get("data", {})
                result = DBInsertTool().run(table=table, data=data)
                response_text = f"✅ 数据已插入表「{table}」，ID: {result.get('rowid')}"

            elif intent == "update":
                table = (extracted_data.get("table") or "").strip()
                if table in INTERNAL_TABLES:
                    raise HTTPException(status_code=403, detail="不允许操作系统内部表")
                data = extracted_data.get("data", {})
                where = extracted_data.get("where", {})
                result = DBUpdateTool().run(table=table, data=data, where=where)
                response_text = f"✅ 已更新表「{table}」，影响行数: {result.get('rows_affected')}"

            elif intent == "drop_table":
                table = (extracted_data.get("table") or "").strip()
                if not _is_valid_identifier(table):
                    raise HTTPException(status_code=400, detail="目标表名不合法")
                if table in INTERNAL_TABLES:
                    raise HTTPException(status_code=403, detail="不允许操作系统内部表")

                conn = get_connection()
                try:
                    conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(table)}")
                    conn.commit()
                finally:
                    conn.close()
                response_text = f"✅ 已删除表「{table}」"

            elif intent == "alter_table":
                table = (extracted_data.get("table") or "").strip()
                if table in INTERNAL_TABLES:
                    raise HTTPException(status_code=403, detail="不允许操作系统内部表")
                sqls = extracted_data.get("sqls", [])
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
                response_text = f"✅ 表结构修改完成：{extracted_data.get('description', '')}"

            elif intent == "delete_data":
                table = (extracted_data.get("table") or "").strip()
                if not _is_valid_identifier(table):
                    raise HTTPException(status_code=400, detail="目标表名不合法")
                if table in INTERNAL_TABLES:
                    raise HTTPException(status_code=403, detail="不允许操作系统内部表")

                where_clause = _validate_where_clause(extracted_data.get("where_clause", ""))
                conn = get_connection()
                rows = 0
                try:
                    cursor = conn.cursor()
                    cursor.execute(f"DELETE FROM {_quote_identifier(table)} WHERE {where_clause}")
                    rows = cursor.rowcount
                    conn.commit()
                finally:
                    conn.close()
                response_text = f"✅ 已从表「{table}」删除 {rows} 条记录"

            else:
                yield _sse({"type": "error", "message": f"不支持的操作类型: {intent}"})
                yield _sse({"type": "done", "intent": intent, "error": "unsupported"})
                return

            # 写入历史
            _append_session_history(session_id, [{"role": "assistant", "content": response_text}])

            yield _sse({"type": "response_start"})
            async for chunk in _stream_text(response_text):
                yield chunk
            yield _sse({"type": "done", "intent": intent, "error": ""})

        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            yield _sse({"type": "done", "intent": intent, "error": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/cancel/{session_id}")
async def cancel_execution(session_id: str):
    """用户取消待处理的写操作"""
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
    """获取所有配置（敏感信息已脱敏）"""
    return config_manager.get_all()


@app.put("/config")
async def update_config(update: ConfigUpdate):
    """更新单个配置项"""
    success = config_manager.update(update.key, update.value, update.description)
    if not success:
        raise HTTPException(status_code=400, detail="配置更新失败，请检查参数类型和取值范围")
    return {"success": True}


@app.post("/config/batch")
async def batch_update_config(updates: List[ConfigUpdate]):
    """批量更新配置项"""
    update_dict = {item.key: item.value for item in updates}
    success = config_manager.batch_update(update_dict)
    if not success:
        raise HTTPException(status_code=400, detail="批量配置更新失败，请检查参数类型和取值范围")
    return {"success": True, "updated": len(updates)}


@app.post("/config/test")
async def test_config(test_request: Optional[ConfigTestRequest] = None):
    """测试配置连接性（主要测试LLM API）"""
    if test_request is None:
        test_config_params = None
    else:
        test_config_params = {
            k: v for k, v in test_request.model_dump().items() if v is not None
        }

    result = config_manager.test_connection(test_config_params)
    return result


@app.delete("/config/{key}")
async def reset_config(key: str):
    """重置配置项为默认值"""
    success = config_manager.reset_to_default(key)
    return {"success": success}
