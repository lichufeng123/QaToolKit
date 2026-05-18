from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TaskStatus = Literal["pending", "running", "success", "failed"]


class TaskView(BaseModel):
    id: str
    type: str
    status: TaskStatus
    title: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    error: str | None = None
    logs: str = ""
    artifact_dir: str
    report_path: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class ApiTestingRunRequest(BaseModel):
    spec_url: str | None = None
    swagger_ui_url: str | None = None
    mode: Literal["smoke", "full"] = "smoke"
    language: str | None = None
    framework: str | None = None
    include_negative_tests: bool = True
    include_edge_cases: bool = True
    max_concurrent: int = Field(default=10, ge=1, le=100)
    base_url: str | None = None
    auth_bearer: str | None = None
    auth_apikey: str | None = None
    auth_basic: str | None = None
    api_tester_mcp_source: str | None = None


class IterationStatsRequest(BaseModel):
    iteration: str
    start_date: str | None = None
    end_date: str | None = None
    iterations_file: str | None = None
    zentao_base_url: str | None = None
    zentao_account: str | None = None
    zentao_password: str | None = None
    zentao_token: str | None = None
    zentao_product_id: int | None = None
    zentao_timeout: int | None = None
    allow_sample_fallback: bool = False
    zentao_user_map_file: str | None = None
    sample_bugs_file: str | None = None
    output_path: str | None = None


class TaskCreatedResponse(BaseModel):
    task_id: str
    task: TaskView


class SettingsUpdateRequest(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout: int | None = Field(default=None, ge=1, le=600)
    swagger_ui_url: str | None = None
    spec_url: str | None = None
    output_dir: str | None = None
    smoke_max_endpoints: int | None = Field(default=None, ge=1, le=500)
    default_api_mode: Literal["smoke", "full"] | None = None
    api_tester_mcp_source: str | None = None
    default_language: str | None = None
    default_framework: str | None = None
    zentao_base_url: str | None = None
    zentao_account: str | None = None
    zentao_password: str | None = None
    zentao_token: str | None = None
    zentao_product_id: int | None = Field(default=None, ge=1)
    zentao_timeout: int | None = Field(default=None, ge=1, le=600)
    zentao_allow_sample_fallback: bool | None = None
    clear_fields: list[str] = Field(default_factory=list)
