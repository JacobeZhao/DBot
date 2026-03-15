from typing import List, Optional, TypedDict


class DataSpeakState(TypedDict):
    user_input: str
    intent: str  # create_table|drop_table|alter_table|insert|update|delete_data|list_tables|query|chat
    schema_info: Optional[dict]
    extraction_plan: Optional[str]
    extracted_data: Optional[dict]
    operation_spec: Optional[dict]
    critic_result: Optional[str]
    retry_count: int
    final_response: Optional[str]
    error: Optional[str]
    session_id: str
    chat_history: Optional[List[dict]]
    needs_confirmation: bool
    confirmation_preview: Optional[str]
    newly_created_table: Optional[str]

    # 意图置信与候选
    intent_confidence: Optional[float]
    intent_candidates: Optional[List[dict]]

    # 澄清态
    needs_clarification: bool
    clarification_question: Optional[str]
    clarification_options: Optional[List[str]]

    # 双智能体 + ReAct 流式扩展
    is_data_related: bool
    active_table: Optional[str]
    target_level: Optional[str]      # database|table|column|row|cell
    operation_type: Optional[str]    # list|switch|create|drop|add_col|drop_col|rename_col|row_insert|row_update|row_delete|cell_get|cell_update
    react_steps: Optional[List[dict]]
    ui_patches: Optional[List[dict]]

    # step 流式展示辅助字段
    step_agent: Optional[str]
    step_phase: Optional[str]        # thought|action|observation
    step_patch: Optional[dict]
