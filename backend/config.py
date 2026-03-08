import json
import os
import sqlite3
import threading
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv()


class ConfigManager:
    """运行时配置管理：.env 默认值 + 数据库覆盖值。"""

    SENSITIVE_KEYS = {"openai_api_key"}
    KEY_ALIASES = {
        "api_key": "openai_api_key",
        "base_url": "openai_base_url",
        "model": "openai_model",
    }

    def __init__(self):
        self.db_path = os.getenv("DB_PATH", "./dataspeak.db")
        self._lock = threading.Lock()

        self.defaults = self._load_env_defaults()
        self._ensure_config_table()
        self.user_config = self._load_db_config()
        self.cache = self._merge_configs()

    def _load_env_defaults(self) -> Dict[str, Any]:
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

        return {
            "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
            "openai_base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "openai_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "temperature": _safe_float(os.getenv("TEMPERATURE", "0.0"), 0.0),
            "max_history_length": _safe_int(os.getenv("MAX_HISTORY_LENGTH", "20"), 20),
            "router_use_history": os.getenv("ROUTER_USE_HISTORY", "true").lower() in {"1", "true", "yes", "on"},
            "router_history_pairs": _safe_int(os.getenv("ROUTER_HISTORY_PAIRS", "5"), 5),
            "db_path": os.getenv("DB_PATH", "./dataspeak.db"),
        }

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
                key = row["key"]
                try:
                    config[key] = self._deserialize_value(row["value"], row["value_type"])
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

    def _normalize_key(self, key: str) -> str:
        return self.KEY_ALIASES.get(key, key)

    def _validate(self, key: str, value: Any) -> tuple[bool, str]:
        if key in {"openai_api_key", "openai_model", "openai_base_url"}:
            if not isinstance(value, str):
                return False, f"{key} 必须是字符串"
            if key == "openai_model" and not value.strip():
                return False, "openai_model 不能为空"
            if key == "openai_base_url":
                trimmed = value.strip()
                if trimmed and not (trimmed.startswith("http://") or trimmed.startswith("https://")):
                    return False, "openai_base_url 必须以 http:// 或 https:// 开头"
        elif key == "temperature":
            try:
                num = float(value)
            except (TypeError, ValueError):
                return False, "temperature 必须是数字"
            if num < 0 or num > 2:
                return False, "temperature 必须在 0.0 到 2.0 之间"
        elif key == "max_history_length":
            try:
                num = int(value)
            except (TypeError, ValueError):
                return False, "max_history_length 必须是整数"
            if num < 1 or num > 200:
                return False, "max_history_length 必须在 1 到 200 之间"
        elif key == "router_history_pairs":
            try:
                num = int(value)
            except (TypeError, ValueError):
                return False, "router_history_pairs 必须是整数"
            if num < 1 or num > 8:
                return False, "router_history_pairs 必须在 1 到 8 之间"
        elif key == "router_use_history":
            if not isinstance(value, (bool, str, int)):
                return False, "router_use_history 必须是布尔值"

        return True, ""

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

    def get_llm_params(self) -> Dict[str, Any]:
        base_url = self.get("openai_base_url") or "https://api.openai.com/v1"
        model = self.get("openai_model") or "gpt-4o-mini"

        try:
            temperature = float(self.get("temperature", 0.0))
        except (TypeError, ValueError):
            temperature = 0.0

        if temperature < 0:
            temperature = 0.0
        if temperature > 2:
            temperature = 2.0

        return {
            "api_key": self.get("openai_api_key", ""),
            "base_url": base_url,
            "model": model,
            "temperature": temperature,
        }

    def update(self, key: str, value: Any, description: str = "") -> bool:
        normalized_key = self._normalize_key(key)
        ok, _ = self._validate(normalized_key, value)
        if not ok:
            return False

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
                    (normalized_key, value_str, value_type, description),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                return False
            finally:
                conn.close()

            self.user_config[normalized_key] = value
            self.cache[normalized_key] = value

        return True

    def batch_update(self, updates: Dict[str, Any]) -> bool:
        if not isinstance(updates, dict):
            return False

        normalized: Dict[str, Any] = {}
        for raw_key, value in updates.items():
            key = self._normalize_key(str(raw_key))
            ok, _ = self._validate(key, value)
            if not ok:
                return False
            normalized[key] = value

        with self._lock:
            conn = self._connect()
            try:
                for key, value in normalized.items():
                    value_str, value_type = self._serialize_value(value)
                    conn.execute(
                        """
                        INSERT INTO _app_config (key, value, value_type, description)
                        VALUES (?, ?, ?, '')
                        ON CONFLICT(key) DO UPDATE SET
                            value = excluded.value,
                            value_type = excluded.value_type,
                            updated_at = datetime('now', 'localtime')
                        """,
                        (key, value_str, value_type),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                return False
            finally:
                conn.close()

            self.user_config.update(normalized)
            self.cache.update(normalized)

        return True

    def reset_to_default(self, key: str) -> bool:
        normalized_key = self._normalize_key(key)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM _app_config WHERE key = ?", (normalized_key,))
                conn.commit()
            except Exception:
                conn.rollback()
                return False
            finally:
                conn.close()

            self.user_config.pop(normalized_key, None)
            if normalized_key in self.defaults:
                self.cache[normalized_key] = self.defaults[normalized_key]
            else:
                self.cache.pop(normalized_key, None)

        return True

    def _normalize_test_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not config:
            return self.get_llm_params()

        normalized = self.get_llm_params()

        mapped = {
            "api_key": config.get("api_key", config.get("openai_api_key", normalized.get("api_key"))),
            "base_url": config.get("base_url", config.get("openai_base_url", normalized.get("base_url"))),
            "model": config.get("model", config.get("openai_model", normalized.get("model"))),
            "temperature": config.get("temperature", normalized.get("temperature", 0.0)),
        }

        try:
            mapped["temperature"] = float(mapped.get("temperature", 0.0))
        except (TypeError, ValueError):
            mapped["temperature"] = 0.0

        return mapped

    def test_connection(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import openai

        test_config = self._normalize_test_config(config)
        api_key = test_config.get("api_key")
        base_url = test_config.get("base_url")
        model = test_config.get("model", "gpt-4o-mini")

        if not api_key:
            return {"success": False, "message": "API 密钥为空"}

        if not base_url:
            return {"success": False, "message": "API 端点为空"}

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
            return {"success": False, "message": f"连接测试失败: {str(e)}"}


config_manager = ConfigManager()
