"""
工具初始化模块

注册所有可用工具到全局工具注册器
"""

from backend.tools.registry import tool_registry, ToolConfidence
from backend.tools.db_tools import (
    insert_row, update_row, delete_row, query_data,
    get_cell_value, update_cell_value,
    INSERT_ROW_SCHEMA, UPDATE_ROW_SCHEMA, DELETE_ROW_SCHEMA,
    QUERY_DATA_SCHEMA, GET_CELL_SCHEMA, UPDATE_CELL_SCHEMA
)
from backend.tools.schema_tools import (
    get_schema, list_tables, add_column, drop_column, rename_column,
    create_table, drop_table, save_table_metadata,
    GET_SCHEMA_SCHEMA, LIST_TABLES_SCHEMA, ADD_COLUMN_SCHEMA,
    DROP_COLUMN_SCHEMA, RENAME_COLUMN_SCHEMA, CREATE_TABLE_SCHEMA,
    DROP_TABLE_SCHEMA, SAVE_METADATA_SCHEMA
)


def register_all_tools():
    """注册所有工具到全局注册器"""

    # ================ 数据操作工具 ================

    tool_registry.register(
        name="insert_row",
        func=insert_row,
        description="向数据库表插入一行数据",
        schema=INSERT_ROW_SCHEMA,
        requires_confirmation=True,
        confidence_level=ToolConfidence.RISKY,
        allowed_in_auto_mode=False
    )

    tool_registry.register(
        name="update_row",
        func=update_row,
        description="更新数据库表中满足条件的行",
        schema=UPDATE_ROW_SCHEMA,
        requires_confirmation=True,
        confidence_level=ToolConfidence.RISKY,
        allowed_in_auto_mode=False
    )

    tool_registry.register(
        name="delete_row",
        func=delete_row,
        description="删除数据库表中满足条件的行",
        schema=DELETE_ROW_SCHEMA,
        requires_confirmation=True,
        confidence_level=ToolConfidence.DESTRUCTIVE,
        allowed_in_auto_mode=False
    )

    tool_registry.register(
        name="query_data",
        func=query_data,
        description="查询数据库表中的数据",
        schema=QUERY_DATA_SCHEMA,
        requires_confirmation=False,
        confidence_level=ToolConfidence.SAFE,
        allowed_in_auto_mode=True
    )

    tool_registry.register(
        name="get_cell_value",
        func=get_cell_value,
        description="获取表中特定单元格的值",
        schema=GET_CELL_SCHEMA,
        requires_confirmation=False,
        confidence_level=ToolConfidence.SAFE,
        allowed_in_auto_mode=True
    )

    tool_registry.register(
        name="update_cell_value",
        func=update_cell_value,
        description="更新表中特定单元格的值",
        schema=UPDATE_CELL_SCHEMA,
        requires_confirmation=True,
        confidence_level=ToolConfidence.RISKY,
        allowed_in_auto_mode=False
    )

    # ================ 表结构工具 ================

    tool_registry.register(
        name="get_schema",
        func=get_schema,
        description="获取数据库表结构信息",
        schema=GET_SCHEMA_SCHEMA,
        requires_confirmation=False,
        confidence_level=ToolConfidence.SAFE,
        allowed_in_auto_mode=True
    )

    tool_registry.register(
        name="list_tables",
        func=list_tables,
        description="列出数据库中所有用户表",
        schema=LIST_TABLES_SCHEMA,
        requires_confirmation=False,
        confidence_level=ToolConfidence.SAFE,
        allowed_in_auto_mode=True
    )

    tool_registry.register(
        name="add_column",
        func=add_column,
        description="向表中添加新字段",
        schema=ADD_COLUMN_SCHEMA,
        requires_confirmation=True,
        confidence_level=ToolConfidence.RISKY,
        allowed_in_auto_mode=False
    )

    tool_registry.register(
        name="drop_column",
        func=drop_column,
        description="从表中删除字段",
        schema=DROP_COLUMN_SCHEMA,
        requires_confirmation=True,
        confidence_level=ToolConfidence.DESTRUCTIVE,
        allowed_in_auto_mode=False
    )

    tool_registry.register(
        name="rename_column",
        func=rename_column,
        description="重命名字段",
        schema=RENAME_COLUMN_SCHEMA,
        requires_confirmation=True,
        confidence_level=ToolConfidence.RISKY,
        allowed_in_auto_mode=False
    )

    tool_registry.register(
        name="create_table",
        func=create_table,
        description="创建新表",
        schema=CREATE_TABLE_SCHEMA,
        requires_confirmation=True,
        confidence_level=ToolConfidence.RISKY,
        allowed_in_auto_mode=False
    )

    tool_registry.register(
        name="drop_table",
        func=drop_table,
        description="删除表",
        schema=DROP_TABLE_SCHEMA,
        requires_confirmation=True,
        confidence_level=ToolConfidence.DESTRUCTIVE,
        allowed_in_auto_mode=False
    )

    tool_registry.register(
        name="save_table_metadata",
        func=save_table_metadata,
        description="保存表的描述和别名",
        schema=SAVE_METADATA_SCHEMA,
        requires_confirmation=False,
        confidence_level=ToolConfidence.SAFE,
        allowed_in_auto_mode=True
    )

    # ================ 自动执行配置 ================

    # 从配置管理器获取自动执行配置
    from backend.config import extended_config_manager
    auto_config = extended_config_manager.get_auto_execute_config()

    tool_registry.set_auto_execute_config(
        enabled=auto_config.get("enabled", False),
        threshold=auto_config.get("threshold", 0.8),
        allowed_operations=auto_config.get("allowed_operations", []),
        exclude_tables=auto_config.get("exclude_tables", [])
    )

    # 返回注册的工具数量
    return len(tool_registry.get_available_tools())


def get_tools_for_llm():
    """获取供LLM使用的工具schema列表"""
    return tool_registry.get_tools_schema()


# 自动注册工具
_registered_tools_count = register_all_tools()

if __name__ == "__main__":
    print(f"已注册 {_registered_tools_count} 个工具:")
    for tool_name in tool_registry.get_available_tools():
        tool = tool_registry.get_tool(tool_name)
        print(f"  - {tool_name}: {tool.description}")
        print(f"    需要确认: {tool.requires_confirmation}")
        print(f"    风险级别: {tool.confidence_level.value}")
        print(f"    允许自动执行: {tool.allowed_in_auto_mode}")