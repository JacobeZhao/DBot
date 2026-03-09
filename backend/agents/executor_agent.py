import os
from rich.console import Console
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import openai
from dotenv import load_dotenv

from backend.state import DataSpeakState
from backend.tools.db_tools import DBInsertTool, DBUpdateTool
from backend.config import config_manager
from backend.tools.schema_tools import GetTableSchemaTool, INTERNAL_TABLES, quote_identifier

load_dotenv()

console = Console()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
    reraise=True,
)
def _call_llm(llm: ChatOpenAI, messages: list) -> str:
    response = llm.invoke(messages)
    return response.content


def executor_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold red][EXECUTOR][/bold red] 开始执行数据库操作...")

    extracted_data = state.get("extracted_data", {})
    intent = state.get("intent", "insert")

    if not extracted_data:
        return {**state, "error": "没有可执行的数据", "final_response": "抱歉，未能提取到有效数据。"}

    table = extracted_data.get("table")
    data = extracted_data.get("data", {})

    if not table or not data:
        return {**state, "error": "数据格式不正确", "final_response": "抱歉，数据格式有误，无法执行操作。"}

    try:
        if intent == "insert":
            tool = DBInsertTool()
            result = tool.run(table=table, data=data)
            final_response = f"已成功记录数据！表: {table}，数据ID: {result.get('rowid')}"
        elif intent == "update":
            # 对于 update，extracted_data 可能包含 where 条件
            where = extracted_data.get("where", {"id": data.pop("id", 1)})
            tool = DBUpdateTool()
            result = tool.run(table=table, data=data, where=where)
            final_response = f"已成功更新数据！表: {table}，影响行数: {result.get('rows_affected')}"
        else:
            return {**state, "error": "未知操作类型", "final_response": "不支持的操作类型。"}

        console.print(f"[bold red][EXECUTOR][/bold red] 执行结果: {result}")
        return {**state, "final_response": final_response}

    except Exception as e:
        error_msg = f"数据库操作失败: {e}"
        console.print(f"[bold red][EXECUTOR][/bold red] {error_msg}")
        return {**state, "error": error_msg, "final_response": f"抱歉，操作失败: {e}"}


def query_agent(state: DataSpeakState) -> DataSpeakState:
    """处理查询和聊天意图，直接用 LLM 回复"""
    console.print("[bold cyan][QUERY][/bold cyan] 处理查询/聊天请求...")

    import sqlite3

    db_path = os.getenv("DB_PATH", "./dataspeak.db")

    # 查询时附带最近数据作为上下文
    context = ""
    if state.get("intent") == "query":
        try:
            schema = GetTableSchemaTool().run()
            active_table = (state.get("active_table") or "").strip()
            user_tables = [t for t in schema.keys() if t not in INTERNAL_TABLES]

            table_for_query = ""
            if active_table in user_tables:
                table_for_query = active_table
            elif user_tables:
                table_for_query = user_tables[0]

            if table_for_query:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                quoted = quote_identifier(table_for_query)
                cursor.execute(f"SELECT * FROM {quoted} ORDER BY rowid DESC LIMIT 10")
                rows = cursor.fetchall()
                cursor.execute(f"PRAGMA table_info({quoted})")
                cols = [col[1] for col in cursor.fetchall()]
                conn.close()

                if rows:
                    context = f"最近表「{table_for_query}」记录：\n"
                    for row in rows:
                        context += str(dict(zip(cols, row))) + "\n"
        except Exception:
            pass

    # 从配置管理器获取LLM参数
    llm_params = config_manager.get_llm_params()

    llm = ChatOpenAI(
        model=llm_params.get("model", "gpt-4o-mini"),
        temperature=llm_params.get("temperature", 0.7),
        api_key=llm_params.get("api_key"),
        base_url=llm_params.get("base_url"),
    )

    system_msg = "你是 DataSpeak，一个智能数据助手。请用中文简洁友好地回答用户问题。"
    if context:
        system_msg += f"\n\n数据库上下文：\n{context}"

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": state["user_input"]},
    ]

    try:
        content = _call_llm(llm, messages)
        console.print("[bold cyan][QUERY][/bold cyan] 回复生成完成")
    except Exception as e:
        content = f"抱歉，处理您的请求时出现问题: {e}"

    return {**state, "final_response": content}
