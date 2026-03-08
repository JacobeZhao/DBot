import os
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv

from backend.state import DataSpeakState
from backend.agents.router_agent import router_agent
from backend.agents.planner_agent import planner_agent
from backend.agents.extractor_agent import extractor_agent
from backend.agents.critic_agent import critic_agent
from backend.agents.executor_agent import executor_agent, query_agent
from backend.agents.create_table_agent import create_table_agent
from backend.agents.drop_table_agent import drop_table_agent
from backend.agents.alter_table_agent import alter_table_agent
from backend.agents.delete_data_agent import delete_data_agent
from backend.agents.no_table_handler_agent import no_table_handler_agent
from backend.agents.list_tables_agent import list_tables_agent

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")


# ── 路由条件 ────────────────────────────────────────────────

def router_condition(state: DataSpeakState) -> str:
    intent = state.get("intent", "chat")
    if intent in ("insert", "update"):
        return "planner"
    elif intent == "create_table":
        return "create_table"
    elif intent == "drop_table":
        return "drop_table"
    elif intent == "alter_table":
        return "alter_table"
    elif intent == "delete_data":
        return "delete_data"
    elif intent == "list_tables":
        return "list_tables"
    else:
        return "query"


def planner_condition(state: DataSpeakState) -> str:
    """Planner 输出 NO_SUITABLE_TABLE → 触发自动建表流程，否则走正常提取"""
    plan = state.get("extraction_plan", "").strip()
    if plan.upper().startswith("NO_SUITABLE_TABLE"):
        return "no_table_handler"
    return "extractor"


def critic_condition(state: DataSpeakState) -> str:
    critic_result = state.get("critic_result", "")
    retry_count = state.get("retry_count", 0)
    if critic_result.upper().startswith("PASS"):
        return "confirm_preview"
    elif retry_count < 2:
        return "extractor"
    else:
        return "error_end"


def drop_table_condition(state: DataSpeakState) -> str:
    """drop_table_agent 如果解析失败会直接设 final_response，此时跳到 END"""
    if state.get("final_response") and not state.get("extracted_data"):
        return "end_direct"
    return "confirm_preview"


def simple_agent_condition(state: DataSpeakState) -> str:
    """alter_table / delete_data agent 解析失败时直接结束"""
    if state.get("final_response") and not state.get("extracted_data"):
        return "end_direct"
    return "confirm_preview"


# ── 预览节点 ─────────────────────────────────────────────────

def confirm_preview_node(state: DataSpeakState) -> DataSpeakState:
    intent = state.get("intent", "insert")
    extracted = state.get("extracted_data", {})
    newly_created = state.get("newly_created_table")

    if intent == "drop_table":
        table = extracted.get("table", "")
        preview = (
            f"⚠️ 即将永久删除表「{table}」及其所有数据！\n\n"
            f"此操作不可恢复，请确认！"
        )

    elif intent == "delete_data":
        table = extracted.get("table", "")
        desc = extracted.get("description", "")
        where = extracted.get("where_clause", "")
        batch_warn = "\n⚠️ 这将删除多条记录！" if extracted.get("is_batch") else ""
        preview = (
            f"即将从表「{table}」删除数据：\n"
            f"  条件：{where}\n"
            f"  描述：{desc}"
            f"{batch_warn}\n\n请确认是否执行？"
        )

    elif intent == "alter_table":
        desc = extracted.get("description", "")
        sqls = extracted.get("sqls", [])
        sql_list = "\n".join([f"  · {s}" for s in sqls])
        preview = f"即将修改表结构：\n{desc}\n\nSQL：\n{sql_list}\n\n请确认是否执行？"

    else:  # insert / update
        table = extracted.get("table", "")
        data = extracted.get("data", {})
        action = "插入" if intent == "insert" else "更新"
        lines = []
        if newly_created:
            lines.append(f"✨ 已自动创建新表「{newly_created}」\n")
        lines.append(f"即将向表「{table}」{action}以下数据：\n")
        for k, v in data.items():
            lines.append(f"  · {k}: {v}")
        lines.append("\n请确认是否执行？")
        preview = "\n".join(lines)

    return {
        **state,
        "needs_confirmation": True,
        "confirmation_preview": preview,
        "final_response": preview,
    }


def error_end_node(state: DataSpeakState) -> DataSpeakState:
    return {
        **state,
        "needs_confirmation": False,
        "final_response": (
            f"抱歉，经过多次尝试仍无法提取有效数据。请尝试更清晰地描述您的需求。\n"
            f"最后的检查意见：{state.get('critic_result', '')}"
        ),
    }


# ── 图构建 ───────────────────────────────────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(DataSpeakState)

    # 注册节点
    graph.add_node("router", router_agent)
    graph.add_node("planner", planner_agent)
    graph.add_node("no_table_handler", no_table_handler_agent)
    graph.add_node("extractor", extractor_agent)
    graph.add_node("critic", critic_agent)
    graph.add_node("confirm_preview", confirm_preview_node)
    graph.add_node("executor", executor_agent)
    graph.add_node("query", query_agent)
    graph.add_node("create_table", create_table_agent)
    graph.add_node("drop_table", drop_table_agent)
    graph.add_node("alter_table", alter_table_agent)
    graph.add_node("delete_data", delete_data_agent)
    graph.add_node("list_tables", list_tables_agent)
    graph.add_node("error_end", error_end_node)

    graph.set_entry_point("router")

    # Router → 各分支
    graph.add_conditional_edges(
        "router",
        router_condition,
        {
            "planner": "planner",
            "query": "query",
            "create_table": "create_table",
            "drop_table": "drop_table",
            "alter_table": "alter_table",
            "delete_data": "delete_data",
            "list_tables": "list_tables",
        },
    )

    # insert/update 主流程
    graph.add_conditional_edges(
        "planner",
        planner_condition,
        {"no_table_handler": "no_table_handler", "extractor": "extractor"},
    )
    graph.add_edge("no_table_handler", "extractor")  # 建完表继续提取数据
    graph.add_edge("extractor", "critic")
    graph.add_conditional_edges(
        "critic",
        critic_condition,
        {"confirm_preview": "confirm_preview", "extractor": "extractor", "error_end": "error_end"},
    )

    # 简单操作 → 确认预览（或直接结束）
    graph.add_conditional_edges(
        "drop_table",
        drop_table_condition,
        {"confirm_preview": "confirm_preview", "end_direct": END},
    )
    graph.add_conditional_edges(
        "alter_table",
        simple_agent_condition,
        {"confirm_preview": "confirm_preview", "end_direct": END},
    )
    graph.add_conditional_edges(
        "delete_data",
        simple_agent_condition,
        {"confirm_preview": "confirm_preview", "end_direct": END},
    )

    # 终止边
    graph.add_edge("confirm_preview", END)
    graph.add_edge("executor", END)
    graph.add_edge("query", END)
    graph.add_edge("create_table", END)
    graph.add_edge("list_tables", END)
    graph.add_edge("error_end", END)

    return graph


async def create_app_async():
    checkpointer = InMemorySaver()
    return build_graph().compile(checkpointer=checkpointer)


_app = None


async def get_app():
    global _app
    if _app is None:
        _app = await create_app_async()
    return _app
