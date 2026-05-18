from __future__ import annotations

from datetime import date
import os
from pathlib import Path
from typing import Any

from ..api_testing.agent import ApiTesterAgent
from ..iteration_stats import ZentaoBugSource, generate_report_html, summarize_iteration
from ..shared.config import Settings, load_settings
from ..testcase_import import import_testcases_from_excel
from .models import ApiTestingRunRequest, IterationStatsRequest
from .task_store import TaskStore


def _settings_with(settings: Settings, **overrides: Any) -> Settings:
    return settings.__class__(**{**settings.__dict__, **overrides})


def run_api_testing_task(
    *,
    request: ApiTestingRunRequest,
) -> tuple[dict[str, Any], str | None]:
    settings = load_settings()
    overrides: dict[str, Any] = {}
    if request.api_tester_mcp_source:
        overrides["api_tester_mcp_source"] = request.api_tester_mcp_source
    if overrides:
        settings = _settings_with(settings, **overrides)
    agent = ApiTesterAgent(settings)
    output = agent.run(
        spec_url=request.spec_url,
        swagger_ui_url=request.swagger_ui_url,
        mode=request.mode,
        language=request.language,
        framework=request.framework,
        include_negative_tests=request.include_negative_tests,
        include_edge_cases=request.include_edge_cases,
        max_concurrent=request.max_concurrent,
        base_url_override=request.base_url,
        auth_bearer=request.auth_bearer,
        auth_apikey=request.auth_apikey,
        auth_basic=request.auth_basic,
    )
    if not output.get("success", False):
        raise RuntimeError(str(output.get("error") or "接口测试执行失败"))
    report_path = (output.get("artifacts") or {}).get("report")
    return output, report_path


def run_testcase_import_task(
    *,
    workbook_path: str,
    dry_run: bool,
    sheets: list[str] | None = None,
) -> tuple[dict[str, Any], str | None]:
    settings = load_settings()
    result = import_testcases_from_excel(
        workbook_path=workbook_path,
        base_url=settings.zentao_base_url or "",
        account=settings.zentao_account,
        password=settings.zentao_password,
        token=settings.zentao_token,
        product_id=settings.zentao_product_id,
        timeout=settings.zentao_timeout,
        dry_run=dry_run,
        sheet_names=sheets,
    )
    return result.to_dict(), result.report_path


def _build_bug_source(request: IterationStatsRequest) -> ZentaoBugSource:
    settings = load_settings()
    return ZentaoBugSource(
        base_url=request.zentao_base_url or settings.zentao_base_url,
        account=request.zentao_account or settings.zentao_account,
        password=request.zentao_password or settings.zentao_password,
        token=request.zentao_token or settings.zentao_token,
        product_id=request.zentao_product_id or settings.zentao_product_id,
        timeout=request.zentao_timeout or settings.zentao_timeout,
        allow_sample_fallback=request.allow_sample_fallback or settings.zentao_allow_sample_fallback,
        user_name_map_file=request.zentao_user_map_file or os.getenv("ZENTAO_USER_MAP_FILE"),
        sample_file=request.sample_bugs_file,
    )


def run_iteration_stats_task(
    *,
    request: IterationStatsRequest,
    generate_report: bool,
) -> tuple[dict[str, Any], str | None]:
    start_date = date.fromisoformat(request.start_date) if request.start_date else None
    end_date = date.fromisoformat(request.end_date) if request.end_date else None
    stats = summarize_iteration(
        iteration_name=request.iteration,
        start_date=start_date,
        end_date=end_date,
        iterations_file=request.iterations_file,
        bug_source=_build_bug_source(request),
    )
    report_path = generate_report_html(stats, request.output_path) if generate_report else None
    output: dict[str, Any] = {"stats": stats}
    if report_path:
        output["report_path"] = report_path
    return output, report_path


def save_upload(*, task_id: str, store: TaskStore, filename: str, content: bytes) -> Path:
    artifact_dir = Path(store.get(task_id).artifact_dir)
    upload_dir = artifact_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    upload_path = upload_dir / safe_name
    upload_path.write_bytes(content)
    return upload_path
