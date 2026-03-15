import json
import re
from typing import Any, Dict, List

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

## 输出要求
只返回 JSON，不要有额外文本，格式：
{
  "intent": "<create_table|drop_table|alter_table|insert|update|delete_data|list_tables|query|chat>",
  "confidence": 0.0,
  "candidates": [
    {"intent": "query", "confidence": 0.81},
    {"intent": "list_tables", "confidence": 0.14}
  ],
  "reason": "简短中文原因"
}

其中：
1) confidence 范围 0~1。
2) candidates 为按置信度降序的 top-k（建议 2~3）。
3) 若不确定，也必须给出最可能 intent 和候选。
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

    recency_bonus = (index + 1) / max(total, 1)

    reference_markers = ("第一个", "上面", "刚才", "那个", "它", "这条", "改", "删", "完成")
    marker_bonus = 1.5 if any(marker in content for marker in reference_markers) else 0.0

    return overlap * 2.0 + recency_bonus + marker_bonus


def _select_relevant_history(chat_history: List[Dict], user_input: str, max_pairs: int) -> List[Dict]:
    if not chat_history:
        return []

    max_pairs = max(1, min(max_pairs, 8))
    max_messages = max_pairs * 2

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

    scored.sort(key=lambda x: x[1], reverse=True)
    selected = {idx: msg for idx, _, msg in scored[:max_messages]}

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


def _normalize_confidence(value: Any, default: float = 0.0) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        conf = default
    if conf < 0:
        return 0.0
    if conf > 1:
        return 1.0
    return conf


def _normalize_candidates(candidates: Any, fallback_intent: str, fallback_conf: float) -> list[dict]:
    normalized: list[dict] = []
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, dict):
                intent = (item.get("intent") or "").strip()
                if intent not in ALLOWED_INTENTS:
                    continue
                normalized.append(
                    {
                        "intent": intent,
                        "confidence": _normalize_confidence(item.get("confidence"), default=0.0),
                    }
                )
            elif isinstance(item, str):
                intent = item.strip()
                if intent in ALLOWED_INTENTS:
                    normalized.append({"intent": intent, "confidence": 0.0})

    if fallback_intent in ALLOWED_INTENTS and not any(c["intent"] == fallback_intent for c in normalized):
        normalized.append({"intent": fallback_intent, "confidence": fallback_conf})

    if not normalized:
        normalized = [{"intent": fallback_intent if fallback_intent in ALLOWED_INTENTS else "chat", "confidence": fallback_conf}]

    normalized.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
    return normalized[:3]


def _parse_router_output(content: str) -> dict:
    raw = (content or "").strip()
    parsed = {}

    try:
        parsed = json.loads(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))

    intent = (parsed.get("intent") or "").strip()
    if intent not in ALLOWED_INTENTS:
        intent = "chat"

    confidence = _normalize_confidence(parsed.get("confidence"), default=0.0)
    candidates = _normalize_candidates(parsed.get("candidates"), intent, confidence)
    reason = (parsed.get("reason") or "").strip()

    return {
        "intent": intent,
        "confidence": confidence,
        "candidates": candidates,
        "reason": reason,
    }


def _heuristic_intent(user_input: str) -> dict:
    text = (user_input or "").strip().lower()
    if not text:
        return {
            "intent": "chat",
            "confidence": 0.35,
            "candidates": [{"intent": "chat", "confidence": 0.35}],
            "reason": "空输入，回退为 chat",
        }

    score = {intent: 0.0 for intent in ALLOWED_INTENTS}

    def bump(intent: str, value: float):
        score[intent] = score.get(intent, 0.0) + value

    if any(k in text for k in ["列出表", "有哪些表", "所有表", "查看表", "list tables", "show tables"]):
        bump("list_tables", 5.0)

    if any(k in text for k in ["新建表", "创建表", "建表", "create table"]):
        bump("create_table", 5.0)

    if any(k in text for k in ["删除表", "删表", "drop table"]):
        bump("drop_table", 5.0)

    if any(k in text for k in ["加字段", "新增字段", "删除字段", "改字段", "重命名字段", "alter table", "修改表结构"]):
        bump("alter_table", 4.5)

    if any(k in text for k in ["删除记录", "删数据", "删除数据", "delete from"]):
        bump("delete_data", 4.0)

    if any(k in text for k in ["更新", "修改", "设为", "改成", "update "]):
        bump("update", 3.8)

    if any(k in text for k in ["添加", "新增", "记一笔", "插入", "insert "]):
        bump("insert", 3.6)

    if any(k in text for k in ["查询", "统计", "多少", "查一下", "select ", "where "]):
        bump("query", 3.2)

    db_markers = ["表", "字段", "数据", "数据库", "记录", "行", "列", "sql"]
    if any(k in text for k in db_markers):
        bump("query", 1.2)

    if max(score.values()) <= 0:
        bump("chat", 2.0)

    ranked = sorted(score.items(), key=lambda kv: kv[1], reverse=True)
    top_score = ranked[0][1]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = max(0.0, top_score - second_score)

    if top_score >= 5.0 and margin >= 1.0:
        confidence = 0.92
    elif top_score >= 3.5 and margin >= 0.8:
        confidence = 0.82
    elif top_score >= 2.0:
        confidence = 0.68
    else:
        confidence = 0.55

    candidates = []
    for intent, intent_score in ranked[:3]:
        if intent_score <= 0:
            continue
        c = min(0.98, max(0.05, intent_score / max(top_score, 1e-6) * confidence))
        candidates.append({"intent": intent, "confidence": round(c, 3)})

    if not candidates:
        candidates = [{"intent": "chat", "confidence": confidence}]

    return {
        "intent": ranked[0][0],
        "confidence": round(confidence, 3),
        "candidates": candidates,
        "reason": "规则回退判定",
    }


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

    heuristic_result = _heuristic_intent(state.get("user_input", ""))

    try:
        content = _call_llm(llm, messages)
        parsed = _parse_router_output(content)

        intent = parsed["intent"]
        confidence = parsed["confidence"]
        candidates = parsed["candidates"]
        reason = parsed["reason"] or "LLM 判定"

        if intent not in ALLOWED_INTENTS:
            intent = heuristic_result["intent"]
            confidence = heuristic_result["confidence"]
            candidates = heuristic_result["candidates"]
            reason = "LLM 意图无效，回退规则"

        if confidence <= 0:
            confidence = heuristic_result["confidence"]
        if not candidates:
            candidates = heuristic_result["candidates"]

    except Exception as e:
        console.print(f"[bold green][ROUTER][/bold green] 解析失败，使用规则回退: {e}")
        intent = heuristic_result["intent"]
        confidence = heuristic_result["confidence"]
        candidates = heuristic_result["candidates"]
        reason = heuristic_result["reason"]

    confidence = _normalize_confidence(confidence, default=heuristic_result["confidence"])
    candidates = _normalize_candidates(candidates, intent, confidence)

    if confidence < 0.7:
        top = candidates[0]["intent"] if candidates else intent
        intent = top if top in ALLOWED_INTENTS else intent

    step_label = f"意图={intent} 置信={confidence:.2f}"
    console.print(f"[bold green][ROUTER][/bold green] {step_label}")

    return {
        **state,
        "intent": intent,
        "intent_confidence": confidence,
        "intent_candidates": candidates,
        "routing_reason": reason,
        "step_agent": "意图识别",
        "step_phase": "thought",
    }
