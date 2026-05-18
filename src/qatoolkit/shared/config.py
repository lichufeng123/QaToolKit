from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from .environment import load_dotenv_file
from .paths import project_root


DEFAULT_API_TESTER_MCP_SOURCE = r"E:\个人文件\MCP\api_tester_mcp-1.5.3"
LOCAL_SETTINGS_RELATIVE_PATH = Path("artifacts") / "config" / "settings.local.json"


@dataclass(frozen=True)
class Settings:
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str | None
    llm_timeout: int
    swagger_ui_url: str | None
    spec_url: str
    output_dir: str
    smoke_max_endpoints: int
    default_api_mode: str
    api_tester_mcp_source: str | None
    default_language: str
    default_framework: str
    zentao_base_url: str | None
    zentao_account: str | None
    zentao_password: str | None
    zentao_token: str | None
    zentao_product_id: int
    zentao_timeout: int
    zentao_allow_sample_fallback: bool


def _project_root() -> Path:
    return project_root(Path(__file__))


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def local_settings_path() -> Path:
    return (_project_root() / LOCAL_SETTINGS_RELATIVE_PATH).resolve()


def load_local_settings() -> dict[str, Any]:
    path = local_settings_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_local_settings(updates: dict[str, Any], *, clear_fields: list[str] | None = None) -> dict[str, Any]:
    path = local_settings_path()
    payload = load_local_settings()
    for field in clear_fields or []:
        payload.pop(field, None)
    for key, value in updates.items():
        if value is None:
            continue
        payload[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _first_config(local_settings: dict[str, Any], key: str, *env_names: str, default: str | None = None) -> str | None:
    value = local_settings.get(key)
    if value not in (None, ""):
        return str(value)
    return _first_env(*env_names) or default


def _config_int(local_settings: dict[str, Any], key: str, *env_names: str, default: int) -> int:
    value = _first_config(local_settings, key, *env_names, default=str(default))
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _config_bool(local_settings: dict[str, Any], key: str, *env_names: str, default: bool = False) -> bool:
    value = _first_config(local_settings, key, *env_names, default="1" if default else "0")
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    load_dotenv_file()
    local_settings = load_local_settings()
    raw_output_dir = _first_config(local_settings, "output_dir", "OUTPUT_DIR")
    output_dir = (
        str(Path(raw_output_dir).expanduser())
        if raw_output_dir and Path(raw_output_dir).is_absolute()
        else str((_project_root() / (raw_output_dir or "artifacts")).resolve())
    )

    return Settings(
        llm_base_url=_first_config(local_settings, "llm_base_url", "QWEN_BASE_URL", "LLM_BASE_URL", "LOCAL_LLM_BASE_URL"),
        llm_api_key=_first_config(local_settings, "llm_api_key", "QWEN_API_KEY", "LLM_API_KEY", "LOCAL_LLM_API_KEY"),
        llm_model=_first_config(local_settings, "llm_model", "QWEN_MODEL", "LLM_MODEL", "LOCAL_LLM_MODEL"),
        llm_timeout=_config_int(local_settings, "llm_timeout", "QWEN_TIMEOUT", "LLM_TIMEOUT", "LOCAL_LLM_TIMEOUT", default=60),
        swagger_ui_url=_first_config(local_settings, "swagger_ui_url", "SWAGGER_UI_URL", "PETSTORE_SWAGGER_UI_URL"),
        spec_url=_first_config(local_settings, "spec_url", "SPEC_URL", "PETSTORE_SPEC_URL", default="https://petstore.swagger.io/v2/swagger.json") or "https://petstore.swagger.io/v2/swagger.json",
        output_dir=output_dir,
        smoke_max_endpoints=_config_int(local_settings, "smoke_max_endpoints", "SMOKE_MAX_ENDPOINTS", default=10),
        default_api_mode=_first_config(local_settings, "default_api_mode", "DEFAULT_API_MODE", default="smoke") or "smoke",
        api_tester_mcp_source=_first_config(
            local_settings,
            "api_tester_mcp_source",
            "API_TESTER_MCP_SOURCE",
            "API_TESTER_MCP_PATH",
        ) or DEFAULT_API_TESTER_MCP_SOURCE,
        default_language=_first_config(local_settings, "default_language", "DEFAULT_LANGUAGE", default="python") or "python",
        default_framework=_first_config(local_settings, "default_framework", "DEFAULT_FRAMEWORK", default="requests") or "requests",
        zentao_base_url=_first_config(local_settings, "zentao_base_url", "ZENTAO_BASE_URL"),
        zentao_account=_first_config(local_settings, "zentao_account", "ZENTAO_ACCOUNT", "ZENTAO_USER", "ZENTAO_USERNAME"),
        zentao_password=_first_config(local_settings, "zentao_password", "ZENTAO_PASSWORD", "ZENTAO_PASS"),
        zentao_token=_first_config(local_settings, "zentao_token", "ZENTAO_TOKEN"),
        zentao_product_id=_config_int(local_settings, "zentao_product_id", "ZENTAO_PRODUCT_ID", default=8),
        zentao_timeout=_config_int(local_settings, "zentao_timeout", "ZENTAO_TIMEOUT", "ZENTAO_API_TIMEOUT", default=30),
        zentao_allow_sample_fallback=_config_bool(local_settings, "zentao_allow_sample_fallback", "ZENTAO_ALLOW_SAMPLE_FALLBACK", default=False),
    )
