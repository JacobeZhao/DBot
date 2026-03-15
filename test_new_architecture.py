#!/usr/bin/env python3
"""
新架构测试脚本

测试工具注册系统和DeepSeek集成的基本功能。
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载环境变量
load_dotenv()


async def test_tool_registry():
    """测试工具注册系统"""
    print("=" * 50)
    print("测试工具注册系统")
    print("=" * 50)

    # 导入工具初始化模块（会自动注册工具）
    from backend.tools.init_tools import tool_registry, _registered_tools_count

    print(f"已注册工具数量: {_registered_tools_count}")
    print("\n可用工具列表:")
    for tool_name in tool_registry.get_available_tools():
        tool = tool_registry.get_tool(tool_name)
        print(f"  - {tool_name}: {tool.description}")
        print(f"    需要确认: {tool.requires_confirmation}")
        print(f"    风险级别: {tool.confidence_level.value}")

    # 测试工具schema生成
    tools_schema = tool_registry.get_tools_schema()
    print(f"\n生成的工具schema数量: {len(tools_schema)}")

    # 测试查询数据工具（安全操作）
    query_tool = tool_registry.get_tool("query_data")
    if query_tool:
        print(f"\n测试工具 'query_data':")
        print(f"  需要确认: {tool_registry.requires_confirmation('query_data')}")
        print(f"  允许自动执行: {query_tool.allowed_in_auto_mode}")

    # 测试插入数据工具（风险操作）
    insert_tool = tool_registry.get_tool("insert_row")
    if insert_tool:
        print(f"\n测试工具 'insert_row':")
        print(f"  需要确认: {tool_registry.requires_confirmation('insert_row')}")
        print(f"  允许自动执行: {insert_tool.allowed_in_auto_mode}")

    print("\n工具注册系统测试完成 [OK]")


async def test_config_manager():
    """测试配置管理器"""
    print("\n" + "=" * 50)
    print("测试配置管理器")
    print("=" * 50)

    from backend.config_new import extended_config_manager, LLMProvider

    # 测试获取配置
    config = extended_config_manager.get_all()
    print(f"配置项数量: {len(config)}")

    # 测试DeepSeek配置
    deepseek_params = extended_config_manager.get_llm_params(LLMProvider.DEEPSEEK)
    print(f"\nDeepSeek配置:")
    print(f"  API密钥配置: {'是' if deepseek_params.get('api_key') else '否'}")
    print(f"  基础URL: {deepseek_params.get('base_url')}")
    print(f"  模型: {deepseek_params.get('model')}")
    print(f"  温度: {deepseek_params.get('temperature')}")

    # 测试OpenAI配置
    openai_params = extended_config_manager.get_llm_params(LLMProvider.OPENAI)
    print(f"\nOpenAI配置:")
    print(f"  API密钥配置: {'是' if openai_params.get('api_key') else '否'}")
    print(f"  基础URL: {openai_params.get('base_url')}")
    print(f"  模型: {openai_params.get('model')}")

    # 测试自动执行配置
    auto_config = extended_config_manager.get_auto_execute_config()
    print(f"\n自动执行配置:")
    print(f"  启用: {auto_config.get('enabled')}")
    print(f"  阈值: {auto_config.get('threshold')}")
    print(f"  允许的操作: {auto_config.get('allowed_operations')}")
    print(f"  排除的表: {auto_config.get('exclude_tables')}")

    print("\n配置管理器测试完成 [OK]")


async def test_deepseek_service():
    """测试DeepSeek服务"""
    print("\n" + "=" * 50)
    print("测试DeepSeek服务")
    print("=" * 50)

    from backend.config_new import LLMProvider
    from backend.services.deepseek_service import deepseek_service

    # 测试连接（需要配置有效的API密钥）
    deepseek_params = deepseek_service.config_manager.get_llm_params(LLMProvider.DEEPSEEK)
    if not deepseek_params.get("api_key"):
        print("DeepSeek API密钥未配置，跳过连接测试")
        return

    print("测试DeepSeek API连接...")
    try:
        result = await deepseek_service.test_connection(LLMProvider.DEEPSEEK)
        print(f"  成功: {result.get('success')}")
        print(f"  消息: {result.get('message')}")
        if result.get("success"):
            print("  DeepSeek连接测试完成 [OK]")
        else:
            print(f"  错误: {result.get('message')}")
    except Exception as e:
        print(f"  连接测试异常: {str(e)}")

    # 测试简单的聊天（不带工具）
    print("\n测试简单聊天（不带工具）...")
    try:
        messages = [
            {"role": "user", "content": "你好，请回复'测试成功'"}
        ]

        response = await deepseek_service.chat_completion(
            messages=messages,
            provider=LLMProvider.DEEPSEEK,
            stream=False,
            max_tokens=10
        )

        if response and "choices" in response:
            content = response["choices"][0]["message"].get("content", "")
            print(f"  响应: {content}")
            if "测试成功" in content:
                print("  简单聊天测试完成 [OK]")
            else:
                print("  响应内容不符合预期")
        else:
            print("  未收到有效响应")
    except Exception as e:
        print(f"  聊天测试异常: {str(e)}")

    print("\nDeepSeek服务测试完成 [OK]")


async def test_database_tools():
    """测试数据库工具"""
    print("\n" + "=" * 50)
    print("测试数据库工具")
    print("=" * 50)

    # 初始化数据库
    from backend.database import init_db
    init_db()

    from backend.tools.db_tools_new import query_data
    from backend.tools.schema_tools_new import get_schema, list_tables

    # 测试列出表
    print("测试列出表...")
    tables_result = list_tables()
    if tables_result.get("success"):
        tables = tables_result.get("tables", [])
        print(f"  找到 {len(tables)} 个表")
        for table in tables[:3]:  # 显示前3个表
            print(f"    - {table['name']}: {table.get('description', '无描述')}")
    else:
        print(f"  失败: {tables_result.get('error')}")

    # 测试获取schema
    print("\n测试获取schema...")
    schema_result = get_schema()
    if schema_result.get("success"):
        schema = schema_result.get("schema", {})
        print(f"  找到 {len(schema)} 个表的schema")
    else:
        print(f"  失败: {schema_result.get('error')}")

    # 测试查询数据（默认的todos表应该存在）
    print("\n测试查询数据...")
    query_result = query_data(table="todos", limit=5)
    if query_result.get("success"):
        rows = query_result.get("rows", [])
        count = query_result.get("count", 0)
        print(f"  查询到 {count} 行数据")
        if rows:
            print(f"  第一行数据: {rows[0]}")
    else:
        print(f"  失败: {query_result.get('error')}")

    print("\n数据库工具测试完成 [OK]")


async def main():
    """主测试函数"""
    print("新架构集成测试")
    print("=" * 50)

    try:
        # 测试工具注册系统
        await test_tool_registry()

        # 测试配置管理器
        await test_config_manager()

        # 测试DeepSeek服务（需要API密钥）
        await test_deepseek_service()

        # 测试数据库工具
        await test_database_tools()

        print("\n" + "=" * 50)
        print("所有测试完成！")
        print("=" * 50)

    except Exception as e:
        print(f"\n测试过程中出现异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)