from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .environment import load_dotenv_file
from .paths import project_root


DEFAULT_API_TESTER_MCP_SOURCE = r"E:\个人文件\MCP\api_tester_mcp-1.5.3"


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


def load_settings() -> Settings:
    load_dotenv_file()
    raw_output_dir = os.getenv("OUTPUT_DIR")
    output_dir = (
        str(Path(raw_output_dir).expanduser())
        if raw_output_dir and Path(raw_output_dir).is_absolute()
        else str((_project_root() / (raw_output_dir or "artifacts")).resolve())
    )

    return Settings(
        llm_base_url=_first_env("QWEN_BASE_URL", "LLM_BASE_URL", "LOCAL_LLM_BASE_URL"),
        llm_api_key=_first_env("QWEN_API_KEY", "LLM_API_KEY", "LOCAL_LLM_API_KEY"),
        llm_model=_first_env("QWEN_MODEL", "LLM_MODEL", "LOCAL_LLM_MODEL"),
        llm_timeout=int(_first_env("QWEN_TIMEOUT", "LLM_TIMEOUT", "LOCAL_LLM_TIMEOUT") or "60"),
        swagger_ui_url=_first_env("SWAGGER_UI_URL", "PETSTORE_SWAGGER_UI_URL"),
        spec_url=os.getenv("SPEC_URL", os.getenv("PETSTORE_SPEC_URL", "https://petstore.swagger.io/v2/swagger.json")),
        output_dir=output_dir,
        smoke_max_endpoints=int(os.getenv("SMOKE_MAX_ENDPOINTS", "10")),
        api_tester_mcp_source=_first_env(
            "API_TESTER_MCP_SOURCE",
            "API_TESTER_MCP_PATH",
        ) or DEFAULT_API_TESTER_MCP_SOURCE,
        default_language=os.getenv("DEFAULT_LANGUAGE", "python"),
        default_framework=os.getenv("DEFAULT_FRAMEWORK", "requests"),
        zentao_base_url=_first_env("ZENTAO_BASE_URL"),
        zentao_account=_first_env("ZENTAO_ACCOUNT", "ZENTAO_USER", "ZENTAO_USERNAME"),
        zentao_password=_first_env("ZENTAO_PASSWORD", "ZENTAO_PASS"),
        zentao_token=_first_env("ZENTAO_TOKEN"),
        zentao_product_id=int(os.getenv("ZENTAO_PRODUCT_ID", "8")),
        zentao_timeout=int(_first_env("ZENTAO_TIMEOUT", "ZENTAO_API_TIMEOUT") or "30"),
        zentao_allow_sample_fallback=os.getenv("ZENTAO_ALLOW_SAMPLE_FALLBACK", "0").strip().lower() in {"1", "true", "yes"},
    )
