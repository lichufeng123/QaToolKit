from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
import requests

from ..iteration_stats import load_iterations
from ..shared.config import load_settings, local_settings_path, save_local_settings
from ..shared.paths import project_root
from .models import ApiTestingRunRequest, IterationStatsRequest, SettingsUpdateRequest, TaskCreatedResponse, TaskView
from .services import (
    run_api_testing_task,
    run_iteration_stats_task,
    run_testcase_import_task,
    save_upload,
)
from .task_runner import TaskRunner
from .task_store import TaskStore


store = TaskStore()
runner = TaskRunner(store)
app = FastAPI(title="QAToolKit Web", version="0.1.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _task_view(task_id: str) -> TaskView:
    try:
        return TaskView.model_validate(store.get(task_id).to_dict())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, object]:
    settings = load_settings()
    return {
        "status": "ok",
        "zentao_configured": bool(settings.zentao_base_url and (settings.zentao_token or settings.zentao_account)),
        "llm_configured": bool(settings.llm_base_url and settings.llm_model),
        "api_tester_mcp_configured": bool(settings.api_tester_mcp_source),
    }


@app.get("/api/config")
def config() -> dict[str, object]:
    settings = load_settings()
    return {
        "api_tester_mcp_source": settings.api_tester_mcp_source or "",
        "zentao_product_id": settings.zentao_product_id,
        "zentao_base_url": settings.zentao_base_url or "",
        "llm_model": settings.llm_model or "",
    }


@app.get("/api/settings")
def get_settings() -> dict[str, object]:
    settings = load_settings()
    return {
        "config_path": str(local_settings_path()),
        "llm_base_url": settings.llm_base_url or "",
        "llm_model": settings.llm_model or "",
        "llm_timeout": settings.llm_timeout,
        "has_llm_api_key": bool(settings.llm_api_key),
        "llm_api_key_masked": _mask_secret(settings.llm_api_key),
        "swagger_ui_url": settings.swagger_ui_url or "",
        "spec_url": settings.spec_url or "",
        "output_dir": settings.output_dir,
        "smoke_max_endpoints": settings.smoke_max_endpoints,
        "default_api_mode": settings.default_api_mode,
        "api_tester_mcp_source": settings.api_tester_mcp_source or "",
        "default_language": settings.default_language,
        "default_framework": settings.default_framework,
        "zentao_base_url": settings.zentao_base_url or "",
        "zentao_account": settings.zentao_account or "",
        "has_zentao_password": bool(settings.zentao_password),
        "zentao_password_masked": _mask_secret(settings.zentao_password),
        "has_zentao_token": bool(settings.zentao_token),
        "zentao_token_masked": _mask_secret(settings.zentao_token),
        "zentao_product_id": settings.zentao_product_id,
        "zentao_timeout": settings.zentao_timeout,
        "zentao_allow_sample_fallback": settings.zentao_allow_sample_fallback,
    }


@app.put("/api/settings")
def update_settings(request: SettingsUpdateRequest) -> dict[str, object]:
    updates = request.model_dump(exclude={"clear_fields"}, exclude_none=True)
    for secret_key in ("llm_api_key", "zentao_password", "zentao_token"):
        if updates.get(secret_key) == "":
            updates.pop(secret_key)
    save_local_settings(updates, clear_fields=request.clear_fields)
    return {"saved": True, "settings": get_settings()}


@app.post("/api/settings/verify/api-tester-mcp")
def verify_api_tester_mcp() -> dict[str, object]:
    settings = load_settings()
    if not settings.api_tester_mcp_source:
        raise HTTPException(status_code=400, detail="未配置 api_tester_mcp 路径")
    source_path = Path(settings.api_tester_mcp_source).expanduser()
    if not source_path.exists():
        raise HTTPException(status_code=400, detail=f"路径不存在：{source_path}")
    if not source_path.is_dir():
        raise HTTPException(status_code=400, detail=f"路径不是目录：{source_path}")
    return {"ok": True, "path": str(source_path)}


@app.post("/api/settings/verify/zentao")
def verify_zentao() -> dict[str, object]:
    settings = load_settings()
    if not settings.zentao_base_url:
        raise HTTPException(status_code=400, detail="未配置 ZenTao BASE_URL")
    if not (settings.zentao_token or (settings.zentao_account and settings.zentao_password)):
        raise HTTPException(status_code=400, detail="未配置 ZenTao token 或账号密码")
    base_url = settings.zentao_base_url.rstrip("/")
    token = settings.zentao_token
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    if not token:
        try:
            response = session.post(
                f"{base_url}/users/login",
                json={"account": settings.zentao_account, "password": settings.zentao_password},
                timeout=settings.zentao_timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HTTPException(status_code=400, detail=f"ZenTao 登录请求失败：{exc}") from exc
        payload = response.json()
        if str(payload.get("status", "")).lower() != "success" or not payload.get("token"):
            raise HTTPException(status_code=400, detail=f"ZenTao 登录失败：{payload}")
        token = str(payload["token"])
    try:
        response = session.get(
            f"{base_url}/products/{settings.zentao_product_id}/bugs",
            params={"browseType": "all", "recPerPage": 1, "pageID": 1},
            headers={"token": token},
            timeout=settings.zentao_timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail=f"ZenTao Bug 列表请求失败：{exc}") from exc
    payload = response.json()
    if str(payload.get("status", "")).lower() != "success":
        raise HTTPException(status_code=400, detail=f"ZenTao Bug 列表校验失败：{payload}")
    return {"ok": True, "product_id": settings.zentao_product_id, "base_url": base_url}


@app.post("/api/settings/verify/qwen")
def verify_qwen() -> dict[str, object]:
    settings = load_settings()
    if not settings.llm_base_url or not settings.llm_model:
        raise HTTPException(status_code=400, detail="未配置 Qwen BASE_URL 或 MODEL")
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    try:
        response = requests.post(
            url,
            headers=headers,
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": "只回复 ok"}],
                "temperature": 0,
                "max_tokens": 8,
            },
            timeout=settings.llm_timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail=f"Qwen 校验请求失败：{exc}") from exc
    return {"ok": True, "model": settings.llm_model, "base_url": settings.llm_base_url}


@app.get("/api/iterations")
def list_iterations() -> dict[str, object]:
    iterations = load_iterations()
    return {
        "iterations": [
            {
                "name": item.name,
                "start_date": item.start_date.isoformat(),
                "zentao_project_id": item.zentao_project_id,
                "description": item.description,
            }
            for item in iterations.values()
        ]
    }


@app.get("/api/tasks", response_model=list[TaskView])
def list_tasks(limit: int = 50) -> list[TaskView]:
    return [TaskView.model_validate(item.to_dict()) for item in store.list(limit=limit)]


@app.get("/api/tasks/{task_id}", response_model=TaskView)
def get_task(task_id: str) -> TaskView:
    return _task_view(task_id)


@app.get("/api/tasks/{task_id}/logs")
def get_task_logs(task_id: str) -> dict[str, str]:
    return {"logs": _task_view(task_id).logs}


@app.delete("/api/tasks/failed")
def delete_failed_tasks(delete_artifacts: bool = True) -> dict[str, object]:
    deleted_ids = store.delete_by_status("failed", delete_artifacts=delete_artifacts)
    return {
        "deleted": True,
        "status": "failed",
        "count": len(deleted_ids),
        "task_ids": deleted_ids,
        "delete_artifacts": delete_artifacts,
    }


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, delete_artifacts: bool = False) -> dict[str, object]:
    try:
        store.delete(task_id, delete_artifacts=delete_artifacts)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return {"deleted": True, "task_id": task_id, "delete_artifacts": delete_artifacts}


@app.get("/api/files")
def get_file(path: str) -> FileResponse:
    root = project_root(Path(__file__)).resolve()
    file_path = Path(path).expanduser().resolve()
    if root not in [file_path, *file_path.parents]:
        raise HTTPException(status_code=403, detail="Only project files can be served")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@app.post("/api/api-testing/run", response_model=TaskCreatedResponse)
def run_api_testing(request: ApiTestingRunRequest) -> TaskCreatedResponse:
    task = runner.submit(
        task_type="api_test",
        title="接口测试",
        task_input=request.model_dump(),
        task_fn=lambda task_id, task_store: run_api_testing_task(request=request),
    )
    return TaskCreatedResponse(task_id=task.id, task=_task_view(task.id))


@app.post("/api/testcase-import/dry-run", response_model=TaskCreatedResponse)
async def testcase_import_dry_run(
    file: Annotated[UploadFile, File()],
    sheets: Annotated[str | None, Form()] = None,
) -> TaskCreatedResponse:
    return await _submit_testcase_import(file=file, sheets=sheets, dry_run=True)


@app.post("/api/testcase-import/run", response_model=TaskCreatedResponse)
async def testcase_import_run(
    file: Annotated[UploadFile, File()],
    sheets: Annotated[str | None, Form()] = None,
) -> TaskCreatedResponse:
    return await _submit_testcase_import(file=file, sheets=sheets, dry_run=False)


async def _submit_testcase_import(*, file: UploadFile, sheets: str | None, dry_run: bool) -> TaskCreatedResponse:
    sheet_names = _parse_sheet_names(sheets)
    raw_content = await file.read()
    task = store.create(
        task_type="testcase_import_dry_run" if dry_run else "testcase_import",
        title="Excel 用例导入预览" if dry_run else "Excel 用例正式导入",
        task_input={"filename": file.filename, "dry_run": dry_run, "sheets": sheet_names},
    )
    upload_path = save_upload(
        task_id=task.id,
        store=store,
        filename=file.filename or "testcases.xlsx",
        content=raw_content,
    )

    def task_fn(task_id: str, task_store: TaskStore):
        task_store.append_log(task_id, f"已保存上传文件：{upload_path}")
        return run_testcase_import_task(
            workbook_path=str(upload_path),
            dry_run=dry_run,
            sheets=sheet_names,
        )

    runner.executor.submit(runner._run, task.id, task_fn)
    return TaskCreatedResponse(task_id=task.id, task=_task_view(task.id))


@app.post("/api/iteration-stats/query", response_model=TaskCreatedResponse)
def iteration_stats(request: IterationStatsRequest) -> TaskCreatedResponse:
    task = runner.submit(
        task_type="iteration_stats",
        title=f"{request.iteration} 迭代统计",
        task_input=request.model_dump(),
        task_fn=lambda task_id, task_store: run_iteration_stats_task(request=request, generate_report=False),
    )
    return TaskCreatedResponse(task_id=task.id, task=_task_view(task.id))


@app.post("/api/iteration-stats/report", response_model=TaskCreatedResponse)
def iteration_report(request: IterationStatsRequest) -> TaskCreatedResponse:
    task = runner.submit(
        task_type="iteration_report",
        title=f"{request.iteration} 迭代报告",
        task_input=request.model_dump(),
        task_fn=lambda task_id, task_store: run_iteration_stats_task(request=request, generate_report=True),
    )
    return TaskCreatedResponse(task_id=task.id, task=_task_view(task.id))


def _parse_sheet_names(value: str | None) -> list[str] | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass
    names = [item.strip() for item in value.split(",") if item.strip()]
    return names or None


def _mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def main() -> None:
    import uvicorn

    uvicorn.run("qatoolkit.web.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
