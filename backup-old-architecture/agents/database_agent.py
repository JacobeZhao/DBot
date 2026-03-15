import json
import re
from typing import Any

import openai
from langchain_openai import ChatOpenAI
from rich.console import Console
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.config import config_manager
from backend.state import DataSpeakState
from backend.tools.schema_tools import GetTableSchemaTool, INTERNAL_TABLES, get_table_metadata

console = Console()

SYSTEM_PROMPT_DATABASE_AGENT = """你是数据库智能体（库级决策）。

任务：基于用户输入、会话当前表、数据库表与别名，输出结构化路由决策。

你必须输出 JSON：
{
  "is_data_related": true|false,
  "operation_type": "list|switch|create|drop_table|alter_table|delete_data|add_col|drop_col|rename_col|row_insert|row_update|row_delete|cell_get|cell_update|query|chat",
  "target_level": "database|table|column|row|cell",
  "active_table": "表名或空",
  "reason": "简短中文说明"
}

规则：
1) 非数据库相关输出 is_data_related=false, operation_type=chat, target_level=database。
2) 表匹配优先顺序：当前 active_table > 表名精确匹配 > 别名匹配。
3) 若是“查看有哪些表/列出表”，operation_type=list, target_level=database。
4) 只输出 JSON，不要额外文本。
"""

CONFIRMABLE_OPS = {
    "row_insert",
    "row_update",
    "row_delete",
    "add_col",
    "drop_col",
    "rename_col",
    "cell_update",
    "drop_table",
    "alter_table",
    "delete_data",
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
    reraise=True,
)
def _call_llm(llm: ChatOpenAI, messages: list[dict[str, Any]]) -> str:
    return llm.invoke(messages).content


def _parse_json(content: str) -> dict:
    raw = (content or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("database_agent 未返回合法 JSON")


def _table_match(user_input: str, active_table: str, tables: list[dict]) -> tuple[str, str]:
    text = (user_input or "").lower()
    if active_table:
        return active_table, "active_table"

    for tbl in tables:
        name = (tbl.get("name") or "").lower()
        if name and name in text:
            return tbl.get("name") or "", "table_name"

    for tbl in tables:
        for alias in tbl.get("aliases", []):
            if (alias or "").lower() in text:
                return tbl.get("name") or "", "table_alias"
    return "", "none"


def _normalize_operation(op: str) -> str:
    op = (op or "").strip()
    aliases = {
        "drop": "drop_table",
        "alter": "alter_table",
        "delete": "delete_data",
        "insert": "row_insert",
        "update": "row_update",
        "list_tables": "list",
    }
    return aliases.get(op, op or "query")


def _map_router_intent_to_operation(intent: str) -> str:
    mapping = {
        "create_table": "create",
        "drop_table": "drop_table",
        "alter_table": "alter_table",
        "insert": "row_insert",
        "update": "row_update",
        "delete_data": "row_delete",
        "list_tables": "list",
        "query": "query",
        "chat": "chat",
    }
    return mapping.get((intent or "").strip(), "query")


def _target_level_for_operation(operation_type: str) -> str:
    op = _normalize_operation(operation_type)
    if op in {"list", "query", "chat"}:
        return "database"
    if op in {"create", "drop_table", "switch"}:
        return "table"
    if op in {"add_col", "drop_col", "rename_col", "alter_table"}:
        return "column"
    if op in {"row_insert", "row_update", "row_delete", "delete_data"}:
        return "row"
    if op in {"cell_get", "cell_update"}:
        return "cell"
    return "database"


def _build_operation_spec(operation_type: str, table: str) -> dict:
    op = _normalize_operation(operation_type)
    return {
        "op": op,
        "table": table or "",
        "where": {},
        "data": {},
        "column": "",
        "value": None,
        "new_name": "",
        "column_type": "TEXT",
        "requires_confirmation": op in CONFIRMABLE_OPS,
    }


def database_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold blue][DB_AGENT][/bold blue] 进行数据库级路由决策...")

    router_intent = (state.get("intent") or "").strip()
    router_confidence = float(state.get("intent_confidence") or 0.0)

    schema = GetTableSchemaTool().run()
    metadata = get_table_metadata()
    tables = []
    for name in schema:
        if name in INTERNAL_TABLES:
            continue
        meta = metadata.get(name, {})
        tables.append(
            {
                "name": name,
                "description": meta.get("description", ""),
                "aliases": meta.get("aliases", []),
            }
        )

    llm_params = config_manager.get_llm_params()
    llm = ChatOpenAI(
        model=llm_params.get("model", "gpt-4o-mini"),
        temperature=0,
        api_key=llm_params.get("api_key"),
        base_url=llm_params.get("base_url"),
    )

    active_table = (state.get("active_table") or "").strip()
    history = state.get("chat_history") or []
    history_text = "\n".join([f"{'用户' if h.get('role') == 'user' else '助手'}: {h.get('content', '')}" for h in history[-6:]])

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_DATABASE_AGENT},
        {
            "role": "user",
            "content": (
                f"router_intent: {router_intent or '无'}\n"
                f"router_confidence: {router_confidence:.2f}\n"
                f"当前会话 active_table: {active_table or '无'}\n"
                f"可用表: {json.dumps(tables, ensure_ascii=False)}\n"
                f"历史: {history_text}\n"
                f"当前输入: {state.get('user_input', '')}"
            ),
        },
    ]

    matched_table, matched_source = _table_match(state.get("user_input", ""), active_table, tables)
    fallback = {
        "is_data_related": True,
        "operation_type": _map_router_intent_to_operation(router_intent),
        "target_level": _target_level_for_operation(_map_router_intent_to_operation(router_intent)),
        "active_table": matched_table,
        "reason": "回退到 router 决策",
    }

    try:
        parsed = _parse_json(_call_llm(llm, messages))
    except Exception as e:
        console.print(f"[bold blue][DB_AGENT][/bold blue] LLM 路由失败，使用回退: {e}")
        parsed = fallback

    parsed_op = _normalize_operation(parsed.get("operation_type") or "query")
    router_op = _normalize_operation(_map_router_intent_to_operation(router_intent))

    if router_confidence >= 0.85 and router_op:
        operation_type = router_op
        fusion_reason = f"采用高置信 router({router_confidence:.2f})"
    elif router_confidence >= 0.7 and parsed_op == router_op:
        operation_type = router_op
        fusion_reason = "router 与 db_agent 一致"
    elif parsed_op:
        operation_type = parsed_op
        fusion_reason = "采用 db_agent 决策"
    else:
        operation_type = router_op or "query"
        fusion_reason = "db_agent 缺失，回退 router"

    if operation_type == "chat" and router_op != "chat" and router_confidence >= 0.7:
        operation_type = router_op
        fusion_reason = "避免误判 chat，采用 router"

    is_data_related = bool(parsed.get("is_data_related", operation_type != "chat"))
    if operation_type != "chat":
        is_data_related = True

    final_table = (parsed.get("active_table") or "").strip() or matched_table

    if operation_type in {
        "row_insert",
        "row_update",
        "row_delete",
        "delete_data",
        "add_col",
        "drop_col",
        "rename_col",
        "cell_get",
        "cell_update",
        "drop_table",
        "alter_table",
    } and not final_table:
        options = [t.get("name", "") for t in tables if t.get("name")]
        clarification_question = "你要操作哪张表？"
        return {
            **state,
            "is_data_related": True,
            "intent": router_intent or state.get("intent") or "query",
            "operation_type": operation_type,
            "target_level": _target_level_for_operation(operation_type),
            "active_table": None,
            "operation_spec": _build_operation_spec(operation_type, ""),
            "needs_clarification": True,
            "clarification_question": clarification_question,
            "clarification_options": options,
            "final_response": clarification_question,
            "react_steps": list(state.get("react_steps") or [])
            + [
                {
                    "agent": "数据库智能体",
                    "phase": "thought",
                    "label": f"缺少目标表，触发澄清（匹配来源: {matched_source}）",
                }
            ],
            "step_agent": "数据库智能体",
            "step_phase": "thought",
            "step_patch": None,
            "source_agent": "database_agent",
            "routing_reason": f"{parsed.get('reason', '')} | {fusion_reason}",
            "db_tables_snapshot": tables,
            "db_intent": operation_type,
            "need_create_table": False,
            "create_table_hint": "",
        }

    target_level = _target_level_for_operation(operation_type)
    operation_spec = _build_operation_spec(operation_type, final_table)

    patch = {
        "type": "table_overview",
        "tables": tables,
        "active_table": final_table or "",
    }

    react_step = {
        "agent": "数据库智能体",
        "phase": "thought",
        "label": f"{parsed.get('reason') or '库级判断'} | {fusion_reason}",
    }

    if operation_type == "list":
        list_response = "当前数据库中还没有可用业务表。"
        if tables:
            lines = [f"当前共有 {len(tables)} 张表："]
            for idx, t in enumerate(tables, 1):
                desc = t.get("description", "")
                aliases = t.get("aliases", [])
                line = f"{idx}. {t.get('name', '')}"
                if desc:
                    line += f" —— {desc}"
                if aliases:
                    line += f"（别名：{', '.join(aliases)}）"
                lines.append(line)
            list_response = "\n".join(lines)

        return {
            **state,
            "is_data_related": True,
            "intent": "list_tables",
            "operation_type": "list",
            "target_level": "database",
            "active_table": final_table or None,
            "operation_spec": operation_spec,
            "final_response": list_response,
            "react_steps": list(state.get("react_steps") or []) + [react_step],
            "ui_patches": list(state.get("ui_patches") or []) + [patch],
            "step_agent": "数据库智能体",
            "step_phase": "observation",
            "step_patch": patch,
            "source_agent": "database_agent",
            "routing_reason": f"{parsed.get('reason', '')} | {fusion_reason}",
            "db_tables_snapshot": tables,
            "db_intent": "list",
            "need_create_table": False,
            "create_table_hint": "",
        }

    return {
        **state,
        "is_data_related": is_data_related,
        "intent": state.get("intent") or router_intent or "query",
        "operation_type": operation_type,
        "target_level": target_level,
        "active_table": final_table or None,
        "operation_spec": operation_spec,
        "react_steps": list(state.get("react_steps") or []) + [react_step],
        "ui_patches": list(state.get("ui_patches") or []) + [patch],
        "step_agent": "数据库智能体",
        "step_phase": "thought",
        "step_patch": patch,
        "source_agent": "database_agent",
        "routing_reason": f"{parsed.get('reason', '')} | {fusion_reason}",
        "db_tables_snapshot": tables,
        "db_intent": operation_type,
        "need_create_table": operation_type == "create",
        "create_table_hint": "",
    }
