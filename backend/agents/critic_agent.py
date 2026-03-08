import os
import re
from rich.console import Console
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import openai
from dotenv import load_dotenv

from backend.state import DataSpeakState
from backend.config import config_manager

load_dotenv()

console = Console()

SYSTEM_PROMPT_CRITIC = """你是一个数据质量检查员。

你会收到：今天日期、用户原始输入、数据库 Schema（含字段名和类型）、提取的结构化数据。

## 检查规则

1. **目标表**：必须是 Schema 中存在的表名。
2. **字段完整性**：
   - NOT NULL 且无默认值的字段必须有非空值。
   - 其他可选字段允许缺失或留空，不要因为“未提取出每个字段”而判 FAIL。
   - 自动字段（id、created_at）由数据库管理，不在提取数据中出现是正常的。
3. **类型匹配**：
   - INTEGER/REAL 字段：值必须是数字，不能是纯文字字符串。
   - TEXT 字段：任何文字都合法，包括"中"、"高"、"未完成"等中文描述。
4. **日期字段规则（重要）**：
   - 仅当字段名按“词级别”出现 `date`、`due`、`deadline`、`expire` 时，才按日期字段处理。
   - 例如 `candidate_name` 不是日期字段，不能按日期格式校验。
   - 日期字段默认只检查格式是否为 YYYY-MM-DD。
   - 不要默认施加“必须早于今天/晚于今天”的约束，除非用户明确表达了时间先后要求。
5. **金额**：amount 等金额字段应为正数。
6. **不要臆造约束**：不要因为业务习惯而拒绝合法值（如 priority="中"在 TEXT 字段完全合法）。
7. **避免自相矛盾**：不要输出逻辑冲突的结论（例如把合法日期同时判为不合法）。

如果数据通过检查，只返回：PASS
如果数据有问题，返回：FAIL: <具体且准确的问题描述>
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
    reraise=True,
)
def _call_llm(llm: ChatOpenAI, messages: list) -> str:
    response = llm.invoke(messages)
    return response.content


def _has_explicit_relative_time_requirement(user_input: str) -> bool:
    markers = [
        "之前", "以后", "之后", "不晚于", "不早于", "最晚", "最早", "截止", "到期", "晚于", "早于"
    ]
    return any(m in (user_input or "") for m in markers)


def _is_date_like_field(field_name: str) -> bool:
    if not isinstance(field_name, str) or not field_name:
        return False
    lower = field_name.lower()

    # 支持 snake_case / kebab-case / camelCase / PascalCase
    tokens = re.findall(r"[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", lower))
    return any(t in {"date", "due", "deadline", "expire"} for t in tokens)


def _validate_date_format_only(extracted_data: dict) -> str | None:
    data = extracted_data.get("data", {}) if isinstance(extracted_data, dict) else {}
    if not isinstance(data, dict):
        return None

    for field, value in data.items():
        if not isinstance(field, str):
            continue
        if not isinstance(value, str):
            continue
        if _is_date_like_field(field):
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                return f"FAIL: 字段 '{field}' 日期格式必须为 YYYY-MM-DD，当前值为 '{value}'"
    return None


def _should_ignore_optional_field_fail(content: str) -> bool:
    text = (content or "").strip()
    if not text.upper().startswith("FAIL"):
        return False

    optional_markers = ["可选", "非必填", "缺失字段", "未提取", "missing", "optional"]
    return any(m in text for m in optional_markers) and ("NOT NULL" not in text.upper())


def _should_ignore_false_date_field_fail(content: str) -> bool:
    text = (content or "").strip()
    if not text.upper().startswith("FAIL"):
        return False

    # 当 FAIL 声称某字段是日期字段，但字段名本身并非日期词级命中时，忽略该误判
    m = re.search(r"字段\s*['\"]([^'\"]+)['\"]", text)
    if not m:
        return False
    field = m.group(1)

    has_date_context = any(k in text.lower() for k in ["日期", "yyyy-mm-dd", "date", "due", "deadline", "expire"])
    return has_date_context and (not _is_date_like_field(field)) and ("candidate_name" in field or "name" in field.lower())


def _normalize_critic_fail(content: str, user_input: str) -> str:
    if _should_ignore_relative_today_fail(content, user_input):
        return "PASS"
    if _should_ignore_optional_field_fail(content):
        return "PASS"
    if _should_ignore_false_date_field_fail(content):
        return "PASS"
    return content


def _check_required_fields_only(schema_info: dict, extracted_data: dict) -> str | None:
    if not isinstance(extracted_data, dict):
        return None

    table = extracted_data.get("table")
    data = extracted_data.get("data", {})
    if not table or not isinstance(data, dict):
        return None

    columns = (schema_info or {}).get(table, [])
    if not isinstance(columns, list):
        return None

    auto_fields = {"id", "created_at"}
    for c in columns:
        name = c.get("name")
        if not isinstance(name, str) or name in auto_fields:
            continue
        notnull = bool(c.get("notnull"))
        has_default = c.get("default") is not None
        if notnull and not has_default:
            if name not in data or data.get(name) in (None, ""):
                return f"FAIL: 必填字段 '{name}' 缺失或为空"

    return None


def _check_amount_positive(extracted_data: dict) -> str | None:
    data = extracted_data.get("data", {}) if isinstance(extracted_data, dict) else {}
    if not isinstance(data, dict):
        return None

    for field, value in data.items():
        if not isinstance(field, str):
            continue
        if "amount" not in field.lower():
            continue

        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return f"FAIL: 字段 '{field}' 必须为数字，当前值为 '{value}'"

        if numeric <= 0:
            return f"FAIL: 字段 '{field}' 金额应为正数，当前值为 '{value}'"

    return None


def _run_deterministic_checks(schema_info: dict, extracted_data: dict) -> str | None:
    for check in (
        lambda: _check_required_fields_only(schema_info, extracted_data),
        lambda: _check_amount_positive(extracted_data),
        lambda: _validate_date_format_only(extracted_data),
    ):
        fail = check()
        if fail:
            return fail
    return None


def _is_non_required_field_missing_fail(content: str, schema_info: dict, extracted_data: dict) -> bool:
    text = (content or "").strip()
    if not text.upper().startswith("FAIL"):
        return False

    m = re.search(r"字段\s*['\"]([^'\"]+)['\"]", text)
    if not m:
        return False

    field = m.group(1)
    table = extracted_data.get("table") if isinstance(extracted_data, dict) else None
    data = extracted_data.get("data", {}) if isinstance(extracted_data, dict) else {}
    if not table or not isinstance(data, dict):
        return False

    columns = (schema_info or {}).get(table, [])
    for c in columns:
        if c.get("name") != field:
            continue
        if field in {"id", "created_at"}:
            return True
        notnull = bool(c.get("notnull"))
        has_default = c.get("default") is not None
        return (not notnull) or has_default

    return False


def _post_process_critic_result(content: str, user_input: str, schema_info: dict, extracted_data: dict) -> str:
    normalized = _normalize_critic_fail(content, user_input)
    if normalized.upper().startswith("PASS"):
        return normalized

    if _is_non_required_field_missing_fail(normalized, schema_info, extracted_data):
        return "PASS"

    return normalized


def _should_ignore_relative_today_fail(content: str, user_input: str) -> bool:
    if _has_explicit_relative_time_requirement(user_input):
        return False

    relative_markers = ["今天", "早于", "晚于", "之前", "之后", "<=", ">=", "≤", "≥"]
    date_markers = ["date", "due", "deadline", "expire", "日期"]

    text = content or ""
    return (
        text.upper().startswith("FAIL")
        and any(m in text for m in relative_markers)
        and any(m in text for m in date_markers)
    )


def critic_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold magenta][CRITIC][/bold magenta] 开始质量检查...")

    from datetime import date
    today = date.today().isoformat()

    schema_info = state.get("schema_info", {})
    extracted_data = state.get("extracted_data", {})

    from backend.tools.schema_tools import INTERNAL_TABLES, get_table_metadata
    metadata = get_table_metadata()
    schema_str = ""
    for table, columns in schema_info.items():
        if table in INTERNAL_TABLES:
            continue
        col_desc = ", ".join(
            [f"{c['name']}({c['type']}, {'NOT NULL' if c['notnull'] else 'nullable'})" for c in columns]
        )
        meta = metadata.get(table, {})
        label = f"【{meta['description']}】" if meta.get("description") else ""
        schema_str += f"表 {table}{label}: {col_desc}\n"

    # 从配置管理器获取LLM参数
    llm_params = config_manager.get_llm_params()

    llm = ChatOpenAI(
        model=llm_params.get("model", "gpt-4o-mini"),
        temperature=llm_params.get("temperature", 0.0),
        api_key=llm_params.get("api_key"),
        base_url=llm_params.get("base_url"),
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_CRITIC + f"\n\n今天的日期是 {today}，请以此为基准判断日期合理性。"},
        {
            "role": "user",
            "content": (
                f"今天日期: {today}\n\n"
                f"用户原始输入: {state['user_input']}\n\n"
                f"数据库 Schema:\n{schema_str}\n\n"
                f"提取的数据: {extracted_data}"
            ),
        },
    ]

    user_input = state.get("user_input", "")

    # 先做确定性检查（必填字段/金额/日期格式），尽量减少 LLM 误判
    deterministic_fail = _run_deterministic_checks(schema_info, extracted_data)
    if deterministic_fail:
        content = deterministic_fail
        console.print(f"[bold magenta][CRITIC][/bold magenta] 确定性检查结果: {content}")
    else:
        try:
            content = _call_llm(llm, messages).strip()
            content = _post_process_critic_result(content, user_input, schema_info, extracted_data)
            console.print(f"[bold magenta][CRITIC][/bold magenta] 检查结果: {content}")
        except Exception as e:
            console.print(f"[bold magenta][CRITIC][/bold magenta] 检查失败: {e}")
            content = f"FAIL: Critic 调用异常 - {e}"

    retry_count = state.get("retry_count", 0)

    if content.upper().startswith("PASS"):
        console.print("[bold magenta][CRITIC][/bold magenta] [green]质量检查通过[/green]")
    else:
        retry_count += 1
        console.print(
            f"[bold magenta][CRITIC][/bold magenta] [red]质量检查失败 (第 {retry_count} 次)[/red]: {content}"
        )

    return {**state, "critic_result": content, "retry_count": retry_count}
