"""
配置管理器

统一的 LLM 配置，通过本地代理（LiteLLM）访问多种模型。
"""

import json
import os
import sqlite3
import threading
from typing import Any, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

# 可用模型列表
AVAILABLE_MODELS = [
    "claude-4.6-opus",
    "claude-4.6-sonnet",
    "claude-4.5-haiku",
]


class ExtendedConfigManager:
    """配置管理器"""

    SENSITIVE_KEYS = {"llm_api_key"}

    def __init__(self):
        self.db_path = os.getenv("DB_PATH", "./dataspeak.db")
        self._lock = threading.Lock()

        self.defaults = self._load_env_defaults()
        self._ensure_config_table()
        self.user_config = self._load_db_config()
        self.cache = self._merge_configs()

    def _load_env_defaults(self) -> Dict[str, Any]:
        """加载环境变量默认值"""
        def _safe_float(value: str, fallback: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return fallback

        def _safe_int(value: str, fallback: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        def _safe_bool(value: str) -> bool:
            return value.lower() in {"1", "true", "yes", "on"}

        defaults = {
            # LLM 配置
            "llm_api_key": os.getenv("LLM_API_KEY", "sk-local"),
            "llm_base_url": os.getenv("LLM_BASE_URL", "http://0.0.0.0:1234/v1"),
            "llm_model": os.getenv("LLM_MODEL", "claude-4.6-sonnet"),

            # 通用配置
            "temperature": _safe_float(os.getenv("TEMPERATURE", "0.0"), 0.0),
            "max_history_length": _safe_int(os.getenv("MAX_HISTORY_LENGTH", "20"), 20),
            "db_path": os.getenv("DB_PATH", "./dataspeak.db"),

            # 自动执行配置
            "auto_execute_enabled": _safe_bool(os.getenv("AUTO_EXECUTE_ENABLED", "false")),
            "auto_execute_threshold": _safe_float(os.getenv("AUTO_EXECUTE_THRESHOLD", "0.8"), 0.8),
        }

        # 解析自动执行允许的操作列表
        allowed_ops = os.getenv("AUTO_EXECUTE_ALLOWED_OPERATIONS", "query_data,get_schema,list_tables")
        defaults["auto_execute_allowed_operations"] = [
            op.strip() for op in allowed_ops.split(",") if op.strip()
        ]

        # 解析排除的表列表
        exclude_tables = os.getenv("AUTO_EXECUTE_EXCLUDE_TABLES", "_app_config,_table_metadata")
        defaults["auto_execute_exclude_tables"] = [
            table.strip() for table in exclude_tables.split(",") if table.strip()
        ]

        return defaults

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_config_table(self):
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _app_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    value_type TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _deserialize_value(self, value_str: str, value_type: str) -> Any:
        if value_type == "int":
            return int(value_str)
        if value_type == "float":
            return float(value_str)
        if value_type == "bool":
            return value_str.lower() == "true"
        if value_type == "json":
            return json.loads(value_str)
        return value_str

    def _serialize_value(self, value: Any) -> tuple[str, str]:
        if isinstance(value, bool):
            return str(value).lower(), "bool"
        if isinstance(value, int):
            return str(value), "int"
        if isinstance(value, float):
            return str(value), "float"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False), "json"
        return str(value), "str"

    def _load_db_config(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {}
        conn = self._connect()
        try:
            rows = conn.execute("SELECT key, value, value_type FROM _app_config").fetchall()
            for row in rows:
                try:
                    config[row["key"]] = self._deserialize_value(row["value"], row["value_type"])
                except (ValueError, json.JSONDecodeError):
                    continue
        except sqlite3.Error:
            return {}
        finally:
            conn.close()
        return config

    def _merge_configs(self) -> Dict[str, Any]:
        merged = self.defaults.copy()
        merged.update(self.user_config)
        return merged

    def get(self, key: str, default: Any = None) -> Any:
        return self.cache.get(key, default)

    def _mask_value(self, key: str, value: Any) -> Any:
        if key not in self.SENSITIVE_KEYS:
            return value
        if not value:
            return ""
        text = str(value)
        if len(text) <= 8:
            return "***"
        return f"{text[:4]}...{text[-4:]}"

    def get_all(self) -> Dict[str, Any]:
        return {k: self._mask_value(k, v) for k, v in self.cache.items()}

    def get_llm_params(self, provider=None) -> Dict[str, Any]:
        """获取 LLM 参数"""
        base_url = self.get("llm_base_url") or "http://0.0.0.0:1234/v1"
        model = self.get("llm_model") or "claude-4.6-sonnet"
        api_key = self.get("llm_api_key", "sk-local")

        try:
            temperature = float(self.get("temperature", 0.0))
        except (TypeError, ValueError):
            temperature = 0.0
        temperature = max(0.0, min(2.0, temperature))

        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "temperature": temperature,
            "provider": "litellm"
        }

    def get_auto_execute_config(self) -> Dict[str, Any]:
        return {
            "enabled": self.get("auto_execute_enabled", False),
            "threshold": self.get("auto_execute_threshold", 0.8),
            "allowed_operations": self.get("auto_execute_allowed_operations", []),
            "exclude_tables": self.get("auto_execute_exclude_tables", []),
        }

    def update(self, key: str, value: Any, description: str = "") -> bool:
        value_str, value_type = self._serialize_value(value)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO _app_config (key, value, value_type, description)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        value_type = excluded.value_type,
                        description = excluded.description,
                        updated_at = datetime('now', 'localtime')
                    """,
                    (key, value_str, value_type, description),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                return False
            finally:
                conn.close()

            self.user_config[key] = value
            self.cache[key] = value

        return True

    def test_connection(self, provider=None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """测试 LLM 连接"""
        import openai

        test_config = config if config else self.get_llm_params()
        api_key = test_config.get("api_key")
        base_url = test_config.get("base_url")
        model = test_config.get("model")

        if not api_key:
            return {"success": False, "message": "API 密钥为空"}

        try:
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=8,
            )
            content = ""
            if response.choices:
                content = response.choices[0].message.content or ""
            return {
                "success": True,
                "message": f"连接测试成功，模型: {model}",
                "response": content,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"连接测试失败: {str(e)}",
            }


# 兼容旧代码的导入
class LLMProvider:
    DEEPSEEK = "litellm"
    OPENAI = "litellm"


# 全局配置管理器实例
extended_config_manager = ExtendedConfigManager()
