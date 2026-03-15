import json
import re
from typing import Any

import openai
from langchain_openai import ChatOpenAI
from rich.console import Console
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.config import config_manager
from backend.state import DataSpeakState
from backend.tools.db_tools import DBCellGetTool
from backend.tools.schema_tools import get_table_columns, table_exists

console = Console()

SYSTEM_PROMPT_TABLE_AGENT = """你是数据表智能体（槽位补全器）。

你会收到：operation_spec 初稿、当前表、字段列表、用户输入。
请只做槽位补全，不要改操作类型 op。

输出 JSON：
{
  "payload": {
    "where": {},
    "data": {},
    "column": "",
    "value": null,
    "new_name": "",
    "column_type": "TEXT"
  },
  "reason": "简短中文说明"
}

要求：
1) 仅补充 payload，不重判 op。
2) where/data 的键必须来自 columns。
3) 无法确定时留空对象/空字符串。
4) 只返回 JSON。
"""

CONFIRMABLE_OPS = {
    "add_col",
    "drop_col",
    "rename_col",
    "row_insert",
    "row_update",
    "row_delete",
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
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError("table_agent 未返回合法 JSON")


def _extract_pairs(text: str) -> list[tuple[str, str]]:
    pairs = []
    if not text:
        return pairs
    pattern = r"([A-Za-z0-9_\u4e00-\u9fff]+)\s*[=:：]\s*([^,，。\n]+)"
    for m in re.finditer(pattern, text):
        key = (m.group(1) or "").strip()
        value = (m.group(2) or "").strip().strip('"').strip("'")
        if key:
            pairs.append((key, value))
    return pairs


def _coerce_value(raw: str):
    if raw is None:
        return None
    value = (raw or "").strip()
    if not value:
        return ""
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except Exception:
            return value
    if re.fullmatch(r"-?\d+\.\d+", value):
        try:
            return float(value)
        except Exception:
            return value
    lowered = value.lower()
    if lowered in {"null", "none"}:
        return None
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    return value


def _extract_where_and_data(user_input: str, columns: list[str], op: str) -> tuple[dict, dict]:
    where = {}
    data = {}
    text = user_input or ""

    id_match = re.search(r"\bid\s*[=:：]\s*(\d+)", text, flags=re.IGNORECASE)
    if id_match and "id" in columns:
        where["id"] = int(id_match.group(1))

    uuid_match = re.search(r"uuid\s*[=:：]\s*([A-Za-z0-9\-]+)", text, flags=re.IGNORECASE)
    if uuid_match and "uuid" in columns:
        where["uuid"] = uuid_match.group(1)

    pairs = _extract_pairs(text)
    col_set = set(columns)

    for key, value in pairs:
        if key not in col_set:
            continue
        coerced = _coerce_value(value)
        if op in {"row_update", "cell_update"} and key in {"id", "uuid"}:
            where[key] = coerced
        elif op in {"row_delete", "cell_get"}:
            where[key] = coerced
        else:
            data[key] = coerced

    if op in {"row_update", "cell_update"} and not where and pairs:
        for key, value in pairs:
            if key in {"id", "uuid"} and key in col_set:
                where[key] = _coerce_value(value)

    if op == "row_update" and data:
        for key in list(data.keys()):
            if key in where:
                data.pop(key, None)

    return where, data


def _merge_payload(base: dict, llm_payload: dict | None, rule_where: dict, rule_data: dict, columns: list[str]) -> dict:
    merged = {
        "where": dict(base.get("where") or {}),
        "data": dict(base.get("data") or {}),
        "column": base.get("column") or "",
        "value": base.get("value"),
        "new_name": base.get("new_name") or "",
        "column_type": base.get("column_type") or "TEXT",
    }

    if isinstance(llm_payload, dict):
        llm_where = llm_payload.get("where") if isinstance(llm_payload.get("where"), dict) else {}
        llm_data = llm_payload.get("data") if isinstance(llm_payload.get("data"), dict) else {}

        for key, value in llm_where.items():
            if key in columns:
                merged["where"][key] = value
        for key, value in llm_data.items():
            if key in columns:
                merged["data"][key] = value

        if llm_payload.get("column"):
            merged["column"] = llm_payload.get("column")
        if "value" in llm_payload:
            merged["value"] = llm_payload.get("value")
        if llm_payload.get("new_name"):
            merged["new_name"] = llm_payload.get("new_name")
        if llm_payload.get("column_type"):
            merged["column_type"] = llm_payload.get("column_type")

    for key, value in rule_where.items():
        merged["where"].setdefault(key, value)
    for key, value in rule_data.items():
        merged["data"].setdefault(key, value)

    if merged.get("column") and merged["column"] not in columns:
        merged["column"] = ""

    return merged


def build_operation_spec(operation_type: str, table: str, payload: dict, existing_spec: dict | None = None) -> dict:
    base = dict(existing_spec or {})
    base.update(
        {
            "op": operation_type,
            "table": table or "",
            "where": payload.get("where") or {},
            "data": payload.get("data") or {},
            "column": payload.get("column") or "",
            "value": payload.get("value"),
            "new_name": payload.get("new_name") or "",
            "column_type": payload.get("column_type") or "TEXT",
            "requires_confirmation": operation_type in CONFIRMABLE_OPS,
        }
    )
    return base


def _clarification_for_missing_slots(op: str, spec: dict, columns: list[str]) -> tuple[str, list[str]]:
    if op in {"row_update", "row_delete", "cell_get", "cell_update"} and not spec.get("where"):
        options = [c for c in columns if c in {"id", "uuid"}] or columns[:5]
        return "缺少定位条件。请补充 where（例如 id=1 或 uuid=xxx）。", options

    if op in {"row_insert", "row_update"} and not spec.get("data"):
        options = [c for c in columns if c not in {"id", "uuid", "创建时间", "更新时间"}][:6]
        return "缺少要写入的数据。请补充 字段=值。", options

    if op in {"cell_get", "cell_update"} and not spec.get("column"):
        return "缺少目标字段。请指定要读取/更新的列名。", columns[:8]

    if op == "cell_update" and spec.get("value") is None:
        return "缺少单元格新值。请补充值。", []

    return "", []


def table_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold yellow][TABLE_AGENT][/bold yellow] 进行表级规划与执行...")

    operation_type = (state.get("operation_type") or "query").strip()
    active_table = (state.get("active_table") or "").strip()
    user_input = state.get("user_input") or ""

    if state.get("needs_clarification"):
        return {
            **state,
            "step_agent": "数据表智能体",
            "step_phase": "thought",
            "step_patch": None,
            "source_agent": "table_agent",
        }

    if not state.get("is_data_related", True):
        return {
            **state,
            "final_response": "这是非数据库请求，我会按聊天方式回复。",
            "intent": "chat",
            "step_agent": "数据表智能体",
            "step_phase": "observation",
            "step_patch": None,
            "source_agent": "table_agent",
        }

    if operation_type in {"chat", "query", "list"}:
        return {
            **state,
            "step_agent": "数据表智能体",
            "step_phase": "observation",
            "step_patch": None,
            "source_agent": "table_agent",
        }

    if not active_table and operation_type not in {"create", "drop_table"}:
        return {
            **state,
            "needs_clarification": True,
            "clarification_question": "你要操作哪张表？",
            "clarification_options": [t.get("name", "") for t in (state.get("db_tables_snapshot") or []) if t.get("name")],
            "final_response": "你要操作哪张表？",
            "step_agent": "数据表智能体",
            "step_phase": "thought",
            "source_agent": "table_agent",
        }

    columns = [c["name"] for c in get_table_columns(active_table)] if active_table and table_exists(active_table) else []

    existing_spec = state.get("operation_spec") or {}
    base_payload = {
        "where": dict(existing_spec.get("where") or {}),
        "data": dict(existing_spec.get("data") or {}),
        "column": existing_spec.get("column") or "",
        "value": existing_spec.get("value"),
        "new_name": existing_spec.get("new_name") or "",
        "column_type": existing_spec.get("column_type") or "TEXT",
    }

    rule_where, rule_data = _extract_where_and_data(user_input, columns, operation_type)

    llm_payload = {}
    if columns:
        llm_params = config_manager.get_llm_params()
        llm = ChatOpenAI(
            model=llm_params.get("model", "gpt-4o-mini"),
            temperature=0,
            api_key=llm_params.get("api_key"),
            base_url=llm_params.get("base_url"),
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_TABLE_AGENT},
            {
                "role": "user",
                "content": (
                    f"op: {operation_type}\n"
                    f"table: {active_table or '无'}\n"
                    f"columns: {columns}\n"
                    f"operation_spec: {json.dumps(existing_spec, ensure_ascii=False)}\n"
                    f"user_input: {user_input}"
                ),
            },
        ]

        try:
            parsed = _parse_json(_call_llm(llm, messages))
            llm_payload = parsed.get("payload") if isinstance(parsed.get("payload"), dict) else {}
        except Exception as e:
            console.print(f"[bold yellow][TABLE_AGENT][/bold yellow] LLM 补槽失败，使用规则结果: {e}")
            llm_payload = {}

    payload = _merge_payload(base_payload, llm_payload, rule_where, rule_data, columns)

    if operation_type in {"cell_get", "cell_update"} and not payload.get("column"):
        for col in columns:
            if col in user_input:
                payload["column"] = col
                break

    spec = build_operation_spec(operation_type, active_table, payload, existing_spec)

    extracted = {
        "table": spec.get("table") or active_table,
        "operation_type": operation_type,
        "target_level": state.get("target_level") or "table",
        "payload": payload,
        "where": payload.get("where") or {},
        "data": payload.get("data") or {},
    }

    clarification_question, clarification_options = _clarification_for_missing_slots(operation_type, spec, columns)
    if clarification_question:
        react_steps = list(state.get("react_steps") or [])
        react_steps.append(
            {
                "agent": "数据表智能体",
                "phase": "thought",
                "label": f"槽位缺失，触发澄清：{operation_type}",
            }
        )
        return {
            **state,
            "operation_spec": spec,
            "extracted_data": extracted,
            "needs_clarification": True,
            "clarification_question": clarification_question,
            "clarification_options": clarification_options,
            "final_response": clarification_question,
            "react_steps": react_steps,
            "step_agent": "数据表智能体",
            "step_phase": "thought",
            "step_patch": None,
            "source_agent": "table_agent",
        }

    react_steps = list(state.get("react_steps") or [])
    react_steps.append(
        {
            "agent": "数据表智能体",
            "phase": "thought",
            "label": f"完成槽位构建：{operation_type}",
        }
    )

    if operation_type == "cell_get":
        try:
            result = DBCellGetTool().run(
                table=spec.get("table") or active_table,
                where=spec.get("where") or {},
                column=spec.get("column") or "",
            )
            patch = {"type": "rows", "table": spec.get("table") or active_table, "refresh": True}
            react_steps.append({"agent": "数据表智能体", "phase": "observation", "label": "已返回查询结果", "patch": patch})
            return {
                **state,
                "operation_spec": spec,
                "extracted_data": extracted,
                "final_response": (
                    f"已查询单元格：表「{spec.get('table') or active_table}」中 {spec.get('where') or {}} 的 "
                    f"「{spec.get('column') or ''}」= {result.get('value')}"
                ),
                "intent": "query",
                "operation_type": "cell_get",
                "target_level": "cell",
                "react_steps": react_steps,
                "ui_patches": list(state.get("ui_patches") or []) + [patch],
                "step_agent": "数据表智能体",
                "step_phase": "observation",
                "step_patch": patch,
                "source_agent": "table_agent",
            }
        except Exception as e:
            return {
                **state,
                "operation_spec": spec,
                "extracted_data": extracted,
                "error": str(e),
                "final_response": f"查询失败：{e}",
                "step_agent": "数据表智能体",
                "step_phase": "observation",
                "source_agent": "table_agent",
            }

    if spec.get("requires_confirmation"):
        preview = f"即将执行操作 {operation_type}，目标表「{spec.get('table') or active_table}」。\n请确认是否执行。"
        react_steps.append({"agent": "数据表智能体", "phase": "action", "label": "已生成待确认操作预览"})
        return {
            **state,
            "operation_spec": spec,
            "extracted_data": extracted,
            "needs_confirmation": True,
            "confirmation_preview": preview,
            "final_response": preview,
            "intent": operation_type,
            "operation_type": operation_type,
            "target_level": state.get("target_level") or "table",
            "react_steps": react_steps,
            "step_agent": "数据表智能体",
            "step_phase": "action",
            "source_agent": "table_agent",
        }

    return {
        **state,
        "operation_spec": spec,
        "extracted_data": extracted,
        "step_agent": "数据表智能体",
        "step_phase": "observation",
        "source_agent": "table_agent",
    }
