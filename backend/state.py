from typing import Optional, List, TypedDict


class DataSpeakState(TypedDict):
    user_input: str
    intent: str  # "create_table" | "drop_table" | "alter_table" | "insert" | "update" | "delete_data" | "list_tables" | "query" | "chat"
    schema_info: Optional[dict]
    extraction_plan: Optional[str]
    extracted_data: Optional[dict]
    critic_result: Optional[str]
    retry_count: int  # Critic 重试计数，最多 2 次
    final_response: Optional[str]
    error: Optional[str]
    session_id: str
    chat_history: Optional[List[dict]]  # [{"role": "user"|"assistant", "content": "..."}]
    needs_confirmation: bool            # True 时等待用户确认后再执行
    confirmation_preview: Optional[str] # 给用户看的操作预览文本
    newly_created_table: Optional[str]  # 多步骤流程中自动建的表名
