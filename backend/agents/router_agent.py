import json
import re
from typing import Dict, List

import openai
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from rich.console import Console
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.config import config_manager
from backend.state import DataSpeakState

load_dotenv()

console = Console()

ALLOWED_INTENTS = {
    "create_table",
    "drop_table",
    "alter_table",
    "insert",
    "update",
    "delete_data",
    "list_tables",
    "query",
    "chat",
}

SYSTEM_PROMPT_ROUTER = """你是一个意图分类器。用户会输入自然语言，你需要判断其意图并返回 JSON。

## 输入说明
你会收到：
1) 当前用户输入
2) 一个“相关历史片段”列表（如果有）

请优先理解当前输入；历史仅作为补充上下文。
当当前输入出现“第一个、刚才、上面、那个、改一下、删掉它”等指代时，必须结合历史判断。

## 可选意图（仅以下 9 种）
- create_table：创建/新建一张表
- drop_table：删除一张表
- alter_table：修改表结构（加/删/改字段、重命名表）
- insert：新增数据
- update：更新已有数据
- delete_data：删除数据行
- list_tables：列出数据库中的表
- query：查询/统计表数据
- chat：纯闲聊或与数据库无关

## 判断原则
1. 只要用户描述了具体可落库的数据（金额、事项、日期、名称等），优先判断为 insert。
2. “删表/移除表”是 drop_table；“删记录/删数据”是 delete_data。
3. 仅当与数据库操作无关时才判断为 chat。
4. 若有歧义，优先选择最可能执行数据库操作的意图。

只返回如下 JSON，不要有任何额外文字：
{"intent": "<create_table|drop_table|alter_table|insert|update|delete_data|list_tables|query|chat>"}
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


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    parts = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text.lower())
    tokens = set()
    for part in parts:
        if re.match(r"^[\u4e00-\u9fff]+$", part):
            if len(part) <= 4:
                tokens.add(part)
            else:
                for i in range(len(part) - 1):
                    tokens.add(part[i : i + 2])
        else:
            tokens.add(part)
    return tokens


def _score_message_relevance(content: str, current_tokens: set[str], index: int, total: int) -> float:
    if not content:
        return 0.0

    msg_tokens = _tokenize(content)
    overlap = len(current_tokens & msg_tokens)

    # 最近消息更重要
    recency_bonus = (index + 1) / max(total, 1)

    # 指代词提升权重
    reference_markers = ("第一个", "上面", "刚才", "那个", "它", "这条", "改", "删", "完成")
    marker_bonus = 1.5 if any(marker in content for marker in reference_markers) else 0.0

    return overlap * 2.0 + recency_bonus + marker_bonus


def _select_relevant_history(chat_history: List[Dict], user_input: str, max_pairs: int) -> List[Dict]:
    if not chat_history:
        return []

    max_pairs = max(1, min(max_pairs, 8))
    max_messages = max_pairs * 2

    # 始终保留最近 2 条，避免丢失短上下文引用
    tail = chat_history[-2:]

    current_tokens = _tokenize(user_input)
    scored = []
    total = len(chat_history)

    for idx, msg in enumerate(chat_history):
        role = msg.get("role")
        content = msg.get("content", "")
        if role not in {"user", "assistant"}:
            continue

        score = _score_message_relevance(content, current_tokens, idx, total)
        scored.append((idx, score, {"role": role, "content": content}))

    # 先取分数高的，再按原顺序重排
    scored.sort(key=lambda x: x[1], reverse=True)
    selected = {idx: msg for idx, _, msg in scored[:max_messages]}

    # 合并强制保留的最近消息
    for offset, msg in enumerate(tail, start=total - len(tail)):
        role = msg.get("role")
        if role in {"user", "assistant"}:
            selected[offset] = {"role": role, "content": msg.get("content", "")}

    ordered = [selected[i] for i in sorted(selected.keys())]
    return ordered[-max_messages:]


def _format_history_for_prompt(history: List[Dict]) -> str:
    if not history:
        return ""

    lines: List[str] = []
    for msg in history:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = (msg.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _parse_intent(content: str) -> str:
    raw = (content or "").strip()

    # 优先尝试纯 JSON
    try:
        parsed = json.loads(raw)
        intent = parsed.get("intent", "chat")
        if intent in ALLOWED_INTENTS:
            return intent
    except Exception:
        pass

    # 回退：提取第一个 JSON 块
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            intent = parsed.get("intent", "chat")
            if intent in ALLOWED_INTENTS:
                return intent
        except Exception:
            pass

    return "chat"


def _heuristic_intent(user_input: str) -> str:
    text = (user_input or "").strip().lower()
    if not text:
        return "chat"

    if any(k in text for k in ["列出表", "有哪些表", "所有表", "查看表", "list tables", "show tables"]):
        return "list_tables"

    if any(k in text for k in ["新建表", "创建表", "建表", "create table"]):
        return "create_table"

    if any(k in text for k in ["删除表", "删表", "drop table"]):
        return "drop_table"

    if any(k in text for k in ["加字段", "新增字段", "删除字段", "改字段", "重命名字段", "alter table", "修改表结构"]):
        return "alter_table"

    if any(k in text for k in ["删除记录", "删数据", "删除数据", "delete from"]):
        return "delete_data"

    if any(k in text for k in ["更新", "修改", "设为", "改成", "update "]):
        return "update"

    if any(k in text for k in ["查询", "统计", "多少", "查一下", "select ", "where "]):
        return "query"

    if any(k in text for k in ["添加", "新增", "记录", "记一笔", "插入", "insert "]):
        return "insert"

    db_markers = ["表", "字段", "数据", "数据库", "记录", "行", "列", "sql"]
    if any(k in text for k in db_markers):
        return "query"

    return "chat"


def router_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold green][ROUTER][/bold green] 开始意图分类...")

    llm_params = config_manager.get_llm_params()
    llm = ChatOpenAI(
        model=llm_params.get("model", "gpt-4o-mini"),
        temperature=0,
        api_key=llm_params.get("api_key"),
        base_url=llm_params.get("base_url"),
    )

    chat_history = state.get("chat_history") or []
    use_history = bool(config_manager.get("router_use_history", True))
    history_pairs = int(config_manager.get("router_history_pairs", 5) or 5)

    selected_history = []
    if use_history:
        selected_history = _select_relevant_history(chat_history, state.get("user_input", ""), history_pairs)

    console.print(
        f"[bold green][ROUTER][/bold green] 历史消息: {len(chat_history)}，参与判定: {len(selected_history)}"
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT_ROUTER}]

    formatted_history = _format_history_for_prompt(selected_history)
    if formatted_history:
        messages.append(
            {
                "role": "user",
                "content": f"相关历史片段（按时间顺序）：\n{formatted_history}",
            }
        )

    messages.append({"role": "user", "content": f"当前用户输入：{state['user_input']}"})

    try:
        content = _call_llm(llm, messages)
        intent = _parse_intent(content)
    except Exception as e:
        heuristic = _heuristic_intent(state.get("user_input", ""))
        console.print(f"[bold green][ROUTER][/bold green] 解析失败，使用规则回退: {e} -> {heuristic}")
        intent = heuristic

    if intent not in ALLOWED_INTENTS:
        intent = _heuristic_intent(state.get("user_input", ""))

    if intent == "chat":
        heuristic = _heuristic_intent(state.get("user_input", ""))
        if heuristic != "chat":
            intent = heuristic
        elif any(k in (state.get("user_input", "")).lower() for k in ["表", "字段", "数据", "数据库", "记录", "sql"]):
            intent = "query"

    if state.get("user_input") and len((state.get("user_input") or "").strip()) <= 2 and intent == "chat":
        intent = "query"

    console.print(f"[bold green][ROUTER][/bold green] 意图识别结果: [yellow]{intent}[/yellow]")
    return {**state, "intent": intent, "step_agent": "意图识别", "step_phase": "thought"}
