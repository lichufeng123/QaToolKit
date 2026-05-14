from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from ..shared.config import Settings
from ..shared.llm import build_chat_client, fallback_test_plan
from .mcp_bridge import ApiTesterBridge, ApiTesterBridgeError


class ApiTesterAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.output_dir = Path(settings.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        spec_url: str | None = None,
        swagger_ui_url: str | None = None,
        mode: str = "smoke",
        language: str | None = None,
        framework: str | None = None,
        include_negative_tests: bool = True,
        include_edge_cases: bool = True,
        max_concurrent: int = 10,
        base_url_override: str | None = None,
        auth_bearer: str | None = None,
        auth_apikey: str | None = None,
        auth_basic: str | None = None,
    ) -> dict[str, Any]:
        if spec_url is not None:
            resolved_spec_url = spec_url
        elif swagger_ui_url is not None:
            resolved_spec_url = ""
        else:
            resolved_spec_url = self.settings.spec_url

        resolved_swagger_ui_url = swagger_ui_url or self.settings.swagger_ui_url
        resolved_language = language or self.settings.default_language
        resolved_framework = framework or self.settings.default_framework

        bridge = ApiTesterBridge(self.settings.api_tester_mcp_source or "")

        plan = self._build_llm_plan(
            spec_url=resolved_spec_url,
            swagger_ui_url=resolved_swagger_ui_url,
            base_url_override=base_url_override,
        )

        try:
            result = self._run_bridge(
                bridge=bridge,
                spec_url=resolved_spec_url,
                swagger_ui_url=resolved_swagger_ui_url,
                mode=mode,
                language=resolved_language,
                framework=resolved_framework,
                include_negative_tests=include_negative_tests,
                include_edge_cases=include_edge_cases,
                max_concurrent=max_concurrent,
                base_url_override=base_url_override,
                auth_bearer=auth_bearer,
                auth_apikey=auth_apikey,
                auth_basic=auth_basic,
                plan=plan,
            )
        except ApiTesterBridgeError as exc:
            return {
                "success": False,
                "error": str(exc),
                "plan": plan,
            }

        run_result = result.get("run", {})
        summary = {
            "spec_url": result.get("spec_url"),
            "base_url": result.get("base_url"),
            "selected_scenarios": len(result.get("selected_scenario_ids", [])),
            "selected_test_cases": len(result.get("selected_test_case_ids", [])),
            "test_report": result.get("report_file"),
            "passed": run_result.get("summary", {}).get("passed_tests"),
            "failed": run_result.get("summary", {}).get("failed_tests"),
        }

        summary_path = self.output_dir / "run-summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "success": True,
            "settings": {
                "mode": mode,
                "language": resolved_language,
                "framework": resolved_framework,
                "swagger_ui_url": resolved_swagger_ui_url,
                "spec_url": resolved_spec_url,
            },
            "plan": plan,
            "summary": summary,
            "artifacts": {
                "summary": str(summary_path),
                "report": result.get("report_file"),
            },
            "bridge": result,
        }

    def _build_llm_plan(
        self,
        *,
        spec_url: str,
        swagger_ui_url: str | None,
        base_url_override: str | None,
    ) -> dict[str, Any]:
        spec_text = self._fetch_spec_text(spec_url, swagger_ui_url)
        if not spec_text:
            return fallback_test_plan(
                {
                    "endpoints": [],
                }
            )

        try:
            spec = json.loads(spec_text)
        except Exception:
            return fallback_test_plan({"endpoints": []})

        endpoints = [
            {
                "method": method.upper(),
                "path": path,
                "summary": operation.get("summary", ""),
                "auth_required": bool(spec.get("security", []) or operation.get("security")),
            }
            for path, methods in spec.get("paths", {}).items()
            for method, operation in methods.items()
            if method.lower() in {"get", "post", "put", "delete", "patch", "head", "options"}
        ]
        summary = {
            "title": spec.get("info", {}).get("title", ""),
            "version": spec.get("info", {}).get("version", ""),
            "base_url": base_url_override or self._extract_base_url(spec) or spec_url,
            "endpoint_count": len(endpoints),
            "endpoints": endpoints,
        }

        client = build_chat_client(
            self.settings.llm_base_url,
            self.settings.llm_api_key,
            self.settings.llm_model,
            self.settings.llm_timeout,
        )
        if not client:
            return fallback_test_plan(summary)

        system = "你是接口测试策略助手。请只输出严格 JSON，不要输出解释。"
        user = json.dumps(
            {
                "task": "为 Swagger/OpenAPI 生成接口测试计划",
                "mode": "smoke" if len(endpoints) > 0 else "full",
                "spec_summary": summary,
                "output_schema": {
                    "mode": "string",
                    "focus": "string",
                    "priority_endpoints": [
                        {
                            "method": "string",
                            "path": "string",
                            "reason": "string",
                        }
                    ],
                    "negative_focus": ["string"],
                    "notes": ["string"],
                },
            },
            ensure_ascii=False,
            indent=2,
        )

        try:
            content = client.chat(system=system, user=user)
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        return fallback_test_plan(summary)

    def _run_bridge(
        self,
        *,
        bridge: ApiTesterBridge,
        spec_url: str,
        swagger_ui_url: str | None,
        mode: str,
        language: str,
        framework: str,
        include_negative_tests: bool,
        include_edge_cases: bool,
        max_concurrent: int,
        base_url_override: str | None,
        auth_bearer: str | None,
        auth_apikey: str | None,
        auth_basic: str | None,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        return asyncio_run(
            bridge.run_workflow(
                spec_url=spec_url,
                swagger_ui_url=swagger_ui_url,
                output_dir=self.settings.output_dir,
                llm_plan=plan,
                base_url_override=base_url_override,
                language=language,
                framework=framework,
                include_negative_tests=include_negative_tests,
                include_edge_cases=include_edge_cases,
                mode=mode,
                max_concurrent=max_concurrent,
                auth_bearer=auth_bearer,
                auth_apikey=auth_apikey,
                auth_basic=auth_basic,
            )
        )

    def _fetch_spec_text(self, spec_url: str, swagger_ui_url: str | None) -> str:
        candidate_urls = [spec_url]
        if swagger_ui_url:
            candidate_urls.extend(
                [
                    swagger_ui_url.rstrip("/") + "/swagger.json",
                    swagger_ui_url.rstrip("/") + "/v2/swagger.json",
                    swagger_ui_url.rstrip("/") + "/openapi.json",
                ]
            )

        for url in candidate_urls:
            if not url:
                continue
            try:
                response = requests.get(url, timeout=20)
                if response.ok:
                    return response.text
            except Exception:
                continue
        return ""

    def _extract_base_url(self, spec: dict[str, Any]) -> str:
        if spec.get("servers"):
            return spec["servers"][0].get("url", "").rstrip("/")
        if spec.get("host"):
            scheme = (spec.get("schemes") or ["https"])[0]
            base_path = spec.get("basePath", "")
            return f"{scheme}://{spec['host']}{base_path}".rstrip("/")
        return ""


def asyncio_run(coro):
    try:
        import asyncio

        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
