"""
新版主应用 - 基于DeepSeek函数调用的DBot API

特性:
1. 全新的RESTful API，JSON格式响应
2. 支持DeepSeek函数调用
3. 确认弹窗机制
4. 自动执行模式
5. 向后兼容部分原有API
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import extended_config_manager
from backend.handlers.chat_handler import chat_handler, session_manager
from backend.state import ChatRequest, ConfirmationRequest

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ================ 数据模型 ================

class ChatRequestModel(BaseModel):
    """聊天请求模型"""
    session_id: str = "default"
    message: str
    auto_execute: Optional[bool] = None
    stream: bool = False


class ConfirmationRequestModel(BaseModel):
    """确认请求模型"""
    session_id: str
    confirmation_id: str
    action: str  # "approve" 或 "reject"
    notes: Optional[str] = None


class AutoExecuteUpdateModel(BaseModel):
    """自动执行更新模型"""
    enabled: bool


class TableQueryModel(BaseModel):
    """表查询模型"""
    table: str
    where: Optional[Dict[str, Any]] = None
    limit: int = 100


class ColumnDefinitionModel(BaseModel):
    """字段定义模型"""
    name: str
    type: str = "TEXT"
    notnull: bool = False
    default: str = ""


class CreateTableModel(BaseModel):
    """创建表模型"""
    table_name: str
    columns: List[ColumnDefinitionModel]
    description: str = ""
    aliases: List[str] = []


# ================ 生命周期管理 ================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("DBot新版本启动...")

    # 清理旧会话（每小时一次）
    async def cleanup_sessions():
        while True:
            try:
                await session_manager.cleanup_expired_sessions(max_age_seconds=3600)
                logger.info(f"会话清理完成，当前会话数: {session_manager.get_session_count()}")
            except Exception as e:
                logger.error(f"会话清理失败: {str(e)}")
            await asyncio.sleep(3600)  # 每小时清理一次

    # 启动清理任务
    cleanup_task = asyncio.create_task(cleanup_sessions())

    yield

    # 关闭时
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("DBot新版本关闭")


# ================ 创建FastAPI应用 ================

app = FastAPI(
    title="DBot NL2CLI (新版本)",
    description="基于DeepSeek函数调用的数据库自然语言交互接口",
    version="2.0.0",
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载前端静态文件（如果有的话）
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")
    logger.info(f"已挂载前端静态文件: {frontend_path}")


# ================ 健康检查端点 ================

@app.get("/health")
async def health():
    """健康检查"""
    try:
        # 检查数据库连接
        import sqlite3
        db_path = extended_config_manager.get("db_path", "./dataspeak.db")
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()

        # 获取会话统计
        session_count = session_manager.get_session_count()

        return {
            "status": "healthy",
            "service": "DBot NL2CLI (新版本)",
            "version": "2.0.0",
            "session_count": session_count,
            "timestamp": time.time()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }


# ================ 聊天API端点 ================

@app.post("/v2/chat")
async def chat(request: ChatRequestModel):
    """
    新版聊天端点

    支持DeepSeek函数调用，自动执行模式和确认机制。
    """
    logger.info(f"处理聊天请求: session={request.session_id}, message_length={len(request.message)}")

    try:
        # 转换为内部请求对象
        internal_request = ChatRequest(
            session_id=request.session_id,
            message=request.message,
            auto_execute=request.auto_execute,
            stream=request.stream
        )

        if request.stream:
            # 流式响应
            return StreamingResponse(
                stream_chat_response(internal_request),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )
        else:
            # 非流式响应
            response = await chat_handler.handle_chat(internal_request)
            return JSONResponse(content=response.to_dict())

    except Exception as e:
        logger.error(f"聊天请求处理失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


async def stream_chat_response(request: ChatRequest):
    """流式聊天响应生成器"""
    # TODO: 实现流式响应
    # 目前先返回非流式响应的包装
    response = await chat_handler.handle_chat(request)
    yield f"data: {json.dumps(response.to_dict(), ensure_ascii=False)}\n\n"


@app.post("/v2/confirm")
async def confirm_execution(request: ConfirmationRequestModel):
    """
    确认执行操作

    用于用户确认或拒绝待执行的操作。
    """
    logger.info(f"处理确认请求: session={request.session_id}, action={request.action}")

    if request.action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="action必须是'approve'或'reject'")

    try:
        # 处理确认
        response = await chat_handler.handle_confirmation(
            session_id=request.session_id,
            confirmation_id=request.confirmation_id,
            action=request.action
        )

        if not response.success:
            raise HTTPException(status_code=400, detail=response.error or "确认处理失败")

        return JSONResponse(content=response.to_dict())

    except Exception as e:
        logger.error(f"确认请求处理失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@app.get("/v2/sessions/{session_id}")
async def get_session_info(session_id: str):
    """获取会话信息"""
    try:
        session_info = await chat_handler.get_session_info(session_id)
        if not session_info:
            raise HTTPException(status_code=404, detail="会话不存在")
        return session_info
    except Exception as e:
        logger.error(f"获取会话信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.put("/v2/sessions/{session_id}/auto-execute")
async def update_auto_execute(session_id: str, update: AutoExecuteUpdateModel):
    """更新会话的自动执行设置"""
    try:
        success = await chat_handler.update_auto_execute(session_id, update.enabled)
        if not success:
            raise HTTPException(status_code=400, detail="更新失败")
        return {"success": True, "enabled": update.enabled}
    except Exception as e:
        logger.error(f"更新自动执行设置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


# ================ 表管理API端点（向后兼容） ================

@app.get("/v2/tables")
async def list_tables():
    """列出所有用户表"""
    try:
        # 内联实现，避免导入问题
        import sqlite3
        import os
        DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 获取所有用户表
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        all_tables = [row[0] for row in cursor.fetchall()]

        # 过滤掉内部表
        internal_tables = {"checkpoints", "writes", "checkpoint_blobs",
                          "checkpoint_migrations", "_table_metadata", "_app_config"}
        user_tables = [t for t in all_tables if t not in internal_tables]

        # 获取表元数据
        metadata = {}
        try:
            cursor.execute("SELECT table_name, description, aliases FROM _table_metadata")
            for row in cursor.fetchall():
                metadata[row[0]] = {
                    "description": row[1] or "",
                    "aliases": row[2].split(",") if row[2] else []
                }
        except Exception as e:
            logger.warning(f"获取表元数据失败，可能表不存在: {e}")

        tables = []
        for table_name in user_tables:
            table_meta = metadata.get(table_name, {})

            # 获取表的列信息
            columns = []
            try:
                cursor.execute(f"PRAGMA table_info({table_name})")
                for row in cursor.fetchall():
                    columns.append({
                        "cid": row[0],
                        "name": row[1],
                        "type": row[2],
                        "notnull": bool(row[3]),
                        "default": row[4],
                        "pk": bool(row[5]),
                    })
            except Exception as e:
                logger.warning(f"获取表 {table_name} 的列信息失败: {e}")
                columns = []

            tables.append({
                "name": table_name,
                "description": table_meta.get("description", ""),
                "aliases": table_meta.get("aliases", []),
                "column_count": len(columns),
                "columns": columns
            })

        conn.close()

        return {
            "success": True,
            "tables": tables,
            "count": len(tables)
        }
    except Exception as e:
        logger.error(f"获取表列表失败: {type(e)}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {type(e)}: {str(e)}")


@app.get("/v2/tables/{table_name}")
async def get_table_data(table_name: str, limit: int = Query(100, ge=1, le=1000)):
    """获取表数据"""
    try:
        from backend.tools.db_tools import query_data
        result = query_data(table=table_name, limit=limit)
        if not result.get("success"):
            # 尝试从错误消息判断是否是表不存在
            if "表不存在" in str(result.get("error", "")):
                raise HTTPException(status_code=404, detail=f"表 '{table_name}' 不存在")
            raise HTTPException(status_code=500, detail=result.get("error", "查询数据失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取表数据失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.post("/v2/tables")
async def create_table_endpoint(request: CreateTableModel):
    """创建新表"""
    try:
        from backend.tools.schema_tools import create_table as create_table_func

        # 转换列定义
        columns = []
        for col in request.columns:
            columns.append({
                "name": col.name,
                "type": col.type,
                "notnull": col.notnull,
                "default": col.default
            })

        result = create_table_func(
            table_name=request.table_name,
            columns=columns,
            description=request.description,
            aliases=request.aliases
        )

        if not result.get("success"):
            error_msg = result.get("error", "创建表失败")
            # 根据错误类型返回不同的状态码
            if "非法表名" in error_msg or "系统保留名" in error_msg:
                raise HTTPException(status_code=400, detail=error_msg)
            raise HTTPException(status_code=500, detail=error_msg)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@app.delete("/v2/tables/{table_name}")
async def delete_table_endpoint(table_name: str):
    """删除表"""
    try:
        from backend.tools.schema_tools import drop_table as drop_table_func
        result = drop_table_func(table_name)
        if not result.get("success"):
            error_msg = result.get("error", "删除表失败")
            if "不允许删除系统内部表" in error_msg:
                raise HTTPException(status_code=403, detail=error_msg)
            if "表不存在" in error_msg:
                raise HTTPException(status_code=404, detail=error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# ================ 配置管理API端点 ================

@app.get("/v2/config")
async def get_config():
    """获取所有配置（敏感值已掩码）"""
    try:
        config = extended_config_manager.get_all()
        return config
    except Exception as e:
        logger.error(f"获取配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


class ConfigUpdateModel(BaseModel):
    """配置更新模型"""
    key: str
    value: Any
    description: str = ""


@app.put("/v2/config")
async def update_config(update: ConfigUpdateModel):
    """更新配置"""
    try:
        success = extended_config_manager.update(
            update.key, update.value, update.description
        )
        if not success:
            raise HTTPException(status_code=400, detail="配置更新失败，请检查参数类型和取值范围")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


class ConfigTestRequestModel(BaseModel):
    """配置测试请求模型"""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    provider: str = "deepseek"  # "openai" 或 "deepseek"


@app.post("/v2/config/test")
async def test_config(test_request: ConfigTestRequestModel):
    """测试LLM连接"""
    try:
        provider = test_request.provider.lower()
        if provider not in ["openai", "deepseek"]:
            raise HTTPException(status_code=400, detail="provider必须是'openai'或'deepseek'")

        # 构建测试配置
        config = {}
        if test_request.api_key is not None:
            config["api_key"] = test_request.api_key
        if test_request.base_url is not None:
            config["base_url"] = test_request.base_url
        if test_request.model is not None:
            config["model"] = test_request.model
        if test_request.temperature is not None:
            config["temperature"] = test_request.temperature

        # 测试连接
        from backend.config import LLMProvider
        provider_enum = LLMProvider.OPENAI if provider == "openai" else LLMProvider.DEEPSEEK
        result = extended_config_manager.test_connection(provider_enum, config)

        return result
    except Exception as e:
        logger.error(f"测试配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")


# ================ 根端点 ================

@app.get("/")
async def root():
    """根端点"""
    return {
        "message": "DBot NL2CLI API (新版本) 正在运行",
        "version": "2.0.0",
        "endpoints": {
            "chat": "/v2/chat",
            "confirm": "/v2/confirm",
            "tables": "/v2/tables",
            "config": "/v2/config",
            "health": "/health",
            "docs": "/docs"
        }
    }


# ================ 错误处理 ================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """HTTP异常处理器"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.detail,
            "status_code": exc.status_code
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """通用异常处理器"""
    logger.error(f"未处理的异常: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "服务器内部错误",
            "detail": str(exc) if os.getenv("DEBUG", "false").lower() == "true" else None
        }
    )


# ================ 启动检查 ================

if __name__ == "__main__":
    import uvicorn

    # 启动前检查
    logger.info("=" * 50)
    logger.info("DBot新版本启动检查")
    logger.info("=" * 50)

    # 检查DeepSeek配置
    deepseek_config = extended_config_manager.get_llm_params()
    if not deepseek_config.get("api_key"):
        logger.warning("DeepSeek API密钥未配置，请设置DEEPSEEK_API_KEY环境变量")

    # 检查数据库
    db_path = extended_config_manager.get("db_path", "./dataspeak.db")
    if not os.path.exists(db_path):
        logger.warning(f"数据库文件不存在: {db_path}，将在首次连接时创建")

    logger.info("启动完成，监听 http://127.0.0.1:8000")

    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    )