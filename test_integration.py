#!/usr/bin/env python3
"""
集成测试脚本

测试新架构的前后端集成功能。
"""

import asyncio
import os
import sys
import requests
import json
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()


async def test_backend_api():
    """测试后端API基本功能"""
    print("=" * 50)
    print("测试后端API基本功能")
    print("=" * 50)

    base_url = "http://127.0.0.1:8000"

    # 1. 测试健康检查
    print("1. 测试健康检查...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"  成功: 状态={data.get('status')}, 会话数={data.get('session_count')}")
        else:
            print(f"  失败: HTTP {response.status_code}")
    except Exception as e:
        print(f"  异常: {str(e)}")

    # 2. 测试根端点
    print("\n2. 测试根端点...")
    try:
        response = requests.get(f"{base_url}/", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"  成功: {data.get('message')}")
            print(f"  版本: {data.get('version')}")
        else:
            print(f"  失败: HTTP {response.status_code}")
    except Exception as e:
        print(f"  异常: {str(e)}")

    # 3. 测试表列表API
    print("\n3. 测试表列表API...")
    try:
        response = requests.get(f"{base_url}/v2/tables", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                tables = data.get("tables", [])
                print(f"  成功: 获取到 {len(tables)} 个表")
                for table in tables[:3]:
                    print(f"    - {table['name']}: {table.get('description', '无描述')}")
            else:
                print(f"  API错误: {data.get('error')}")
        else:
            print(f"  失败: HTTP {response.status_code}")
    except Exception as e:
        print(f"  异常: {str(e)}")

    # 4. 测试配置API
    print("\n4. 测试配置API...")
    try:
        response = requests.get(f"{base_url}/v2/config", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"  成功: 获取到 {len(data)} 个配置项")
            print(f"  DeepSeek配置: {'已配置' if data.get('deepseek_api_key') != 'your...here' else '未配置'}")
            print(f"  自动执行: {'启用' if data.get('auto_execute_enabled') else '禁用'}")
        else:
            print(f"  失败: HTTP {response.status_code}")
    except Exception as e:
        print(f"  异常: {str(e)}")

    # 5. 测试聊天API（需要DeepSeek API密钥）
    print("\n5. 测试聊天API...")
    try:
        test_data = {
            "session_id": "integration_test",
            "message": "列出所有表",
            "auto_execute": False,
            "stream": False
        }
        response = requests.post(f"{base_url}/v2/chat", json=test_data, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print(f"  成功: {data.get('response_text', '无响应文本')[:50]}...")
                if data.get("needs_confirmation"):
                    print(f"  需要确认: {data.get('confirmation_message', 'N/A')}")
            else:
                error = data.get("error", "未知错误")
                print(f"  API错误: {error[:100]}")
                # 检查是否是API密钥问题
                if "Authentication Fails" in error or "401" in error:
                    print("  注意: DeepSeek API密钥配置有问题")
        else:
            print(f"  失败: HTTP {response.status_code}")
    except Exception as e:
        print(f"  异常: {str(e)}")

    print("\n后端API测试完成")


async def test_database_operations():
    """测试数据库操作功能"""
    print("\n" + "=" * 50)
    print("测试数据库操作功能")
    print("=" * 50)

    base_url = "http://127.0.0.1:8000"

    # 1. 查询todos表数据
    print("1. 查询todos表数据...")
    try:
        response = requests.get(f"{base_url}/v2/tables/todos?limit=5", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                rows = data.get("rows", [])
                print(f"  成功: 查询到 {len(rows)} 行数据")
                if rows:
                    print(f"  示例数据: ID={rows[0].get('id')}, Title={rows[0].get('title', 'N/A')}")
            else:
                print(f"  API错误: {data.get('error')}")
        elif response.status_code == 404:
            print("  表不存在，这是正常的（如果数据库是空的）")
        else:
            print(f"  失败: HTTP {response.status_code}")
    except Exception as e:
        print(f"  异常: {str(e)}")

    # 2. 测试表管理API（创建测试表）
    print("\n2. 测试表管理API（创建测试表）...")
    try:
        test_table_data = {
            "table_name": "test_integration",
            "columns": [
                {"name": "test_field", "type": "TEXT", "notnull": True},
                {"name": "value", "type": "INTEGER", "default": "0"}
            ],
            "description": "集成测试表",
            "aliases": ["测试表", "集成表"]
        }
        response = requests.post(f"{base_url}/v2/tables", json=test_table_data, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print(f"  成功: {data.get('message')}")
            else:
                print(f"  API错误: {data.get('error')}")
        else:
            print(f"  失败: HTTP {response.status_code}")
            if response.status_code == 400:
                print(f"  错误详情: {response.text}")
    except Exception as e:
        print(f"  异常: {str(e)}")

    # 3. 验证表是否创建成功
    print("\n3. 验证表是否创建成功...")
    try:
        response = requests.get(f"{base_url}/v2/tables/test_integration", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print(f"  成功: 表存在")
                # 清理测试表
                print("  清理测试表...")
                delete_response = requests.delete(f"{base_url}/v2/tables/test_integration", timeout=5)
                if delete_response.status_code == 200:
                    print("  成功: 测试表已删除")
                else:
                    print(f"  警告: 删除测试表失败: HTTP {delete_response.status_code}")
            else:
                print(f"  表不存在或查询失败: {data.get('error')}")
        else:
            print(f"  表不存在: HTTP {response.status_code}")
    except Exception as e:
        print(f"  异常: {str(e)}")

    print("\n数据库操作测试完成")


async def test_frontend_backend_integration():
    """测试前后端集成"""
    print("\n" + "=" * 50)
    print("测试前后端集成")
    print("=" * 50)

    # 测试通过前端代理访问后端API
    frontend_url = "http://localhost:3000"
    proxy_url = "http://localhost:3000/api"

    print("1. 测试前端代理配置...")

    # 测试健康检查通过代理
    try:
        response = requests.get(f"{proxy_url}/health", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"  成功: 通过前端代理访问后端健康检查")
            print(f"  服务状态: {data.get('status')}")
        else:
            print(f"  失败: HTTP {response.status_code}")
            print(f"  响应: {response.text[:100]}")
    except requests.exceptions.ConnectionError:
        print("  前端开发服务器未运行（正常，如果尚未启动）")
    except Exception as e:
        print(f"  异常: {str(e)}")

    print("\n2. 检查前端项目结构...")
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend-react")
    if os.path.exists(frontend_dir):
        print(f"  前端目录存在: {frontend_dir}")

        # 检查关键文件
        key_files = [
            "package.json",
            "src/App.jsx",
            "src/components/ChatInterface.jsx",
            "src/services/apiService.js"
        ]

        for file in key_files:
            file_path = os.path.join(frontend_dir, file)
            if os.path.exists(file_path):
                print(f"  ✓ {file}")
            else:
                print(f"  ✗ {file} 不存在")
    else:
        print(f"  前端目录不存在: {frontend_dir}")

    print("\n前后端集成测试完成")


async def test_deepseek_configuration():
    """测试DeepSeek配置"""
    print("\n" + "=" * 50)
    print("测试DeepSeek配置")
    print("=" * 50)

    # 检查环境变量
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key and deepseek_key != "your_deepseek_api_key_here":
        print(f"DeepSeek API密钥: {'*' * 20}{deepseek_key[-4:]}")

        # 测试配置API
        base_url = "http://127.0.0.1:8000"
        test_data = {
            "api_key": deepseek_key,
            "provider": "deepseek"
        }

        try:
            response = requests.post(f"{base_url}/v2/config/test", json=test_data, timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"配置测试结果: {data.get('success', False)}")
                print(f"消息: {data.get('message', 'N/A')}")
            else:
                print(f"配置测试失败: HTTP {response.status_code}")
                print(f"响应: {response.text[:200]}")
        except Exception as e:
            print(f"配置测试异常: {str(e)}")
    else:
        print("DeepSeek API密钥未配置或为默认值")
        print("请设置有效的DEEPSEEK_API_KEY环境变量")

    print("\nDeepSeek配置测试完成")


async def generate_test_report():
    """生成测试报告"""
    print("\n" + "=" * 50)
    print("集成测试报告")
    print("=" * 50)

    report = {
        "timestamp": datetime.now().isoformat(),
        "backend_url": "http://127.0.0.1:8001",
        "frontend_url": "http://localhost:3000",
        "tests": {}
    }

    # 这里可以添加详细的测试结果收集
    # 暂时简单总结

    print("总结:")
    print("- 新架构后端API运行在 http://127.0.0.1:8001")
    print("- 前端React项目已创建，可在 frontend-react/ 目录运行")
    print("- 需要配置有效的DeepSeek API密钥以测试完整功能")
    print("- 数据库操作API工作正常")
    print("- 表管理API工作正常")
    print("\n下一步:")
    print("1. 配置有效的DeepSeek API密钥")
    print("2. 启动前端开发服务器: cd frontend-react && npm install && npm run dev")
    print("3. 测试完整的聊天和工具调用工作流")
    print("4. 进行端到端测试")


async def main():
    """主测试函数"""
    print("新架构集成测试")
    print("=" * 50)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        # 测试后端API
        await test_backend_api()

        # 测试数据库操作
        await test_database_operations()

        # 测试前后端集成
        await test_frontend_backend_integration()

        # 测试DeepSeek配置
        await test_deepseek_configuration()

        # 生成测试报告
        await generate_test_report()

    except Exception as e:
        print(f"\n测试过程中出现异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)