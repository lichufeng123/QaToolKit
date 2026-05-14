from __future__ import annotations

import asyncio
from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urljoin

import requests


class ApiTesterBridgeError(RuntimeError):
    pass


@contextmanager
def _prepend_sys_path(path: str):
    sys.path.insert(0, path)
    try:
        yield
    finally:
        try:
            sys.path.remove(path)
        except ValueError:
            pass


def _find_spec_url_from_swagger_ui(swagger_ui_url: str) -> str | None:
    candidates = [
        urljoin(swagger_ui_url.rstrip("/") + "/", "swagger.json"),
        urljoin(swagger_ui_url.rstrip("/") + "/", "v2/swagger.json"),
        urljoin(swagger_ui_url.rstrip("/") + "/", "openapi.json"),
        urljoin(swagger_ui_url.rstrip("/") + "/", "v1/swagger.json"),
    ]
    for candidate in candidates:
        try:
            response = requests.get(candidate, timeout=20)
            if response.ok and "json" in response.headers.get("content-type", "").lower():
                return candidate
        except Exception:
            continue

    try:
        response = requests.get(swagger_ui_url, timeout=20)
        if response.ok and "html" in response.headers.get("content-type", "").lower():
            text = response.text
            patterns = [
                r'url:\s*"([^"]+)"',
                r"url:\s*'([^']+)'",
                r'configUrl:\s*"([^"]+)"',
                r"configUrl:\s*'([^']+)'",
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    raw = match.group(1)
                    return urljoin(swagger_ui_url, raw)
    except Exception:
        pass

    return None


def _default_path_value(name: str) -> str:
    lowered = name.lower()
    if "id" in lowered:
        return "1"
    if "name" in lowered or "username" in lowered:
        return "demo"
    if "status" in lowered:
        return "available"
    if "tag" in lowered:
        return "tag1"
    return "demo"


def _derive_env_vars(endpoints: list[Any], base_url: str | None) -> dict[str, str]:
    env_vars: dict[str, str] = {}
    if base_url:
        env_vars["baseUrl"] = base_url.rstrip("/")

    for endpoint in endpoints:
        path = endpoint.get("path") if isinstance(endpoint, dict) else getattr(endpoint, "path", "")
        for token in re.findall(r"\{([^}]+)\}", path):
            env_vars.setdefault(token, _default_path_value(token))

    return env_vars


class ApiTesterBridge:
    def __init__(self, source_path: str):
        self.source_path = source_path
        self.server = None

    def load(self) -> Any:
        if not self.source_path:
            raise ApiTesterBridgeError("api_tester_mcp source path is required")

        if not Path(self.source_path).exists():
            raise ApiTesterBridgeError(
                f"api_tester_mcp source path not found: {self.source_path}"
            )

        project_src = Path(__file__).resolve().parents[2]
        with _prepend_sys_path(str(project_src)), _prepend_sys_path(self.source_path):
            self.server = importlib.import_module("api_tester_mcp.server")
        return self.server

    async def run_workflow(
        self,
        *,
        spec_url: str,
        swagger_ui_url: str | None,
        output_dir: str,
        llm_plan: dict[str, Any] | None,
        base_url_override: str | None,
        language: str,
        framework: str,
        include_negative_tests: bool,
        include_edge_cases: bool,
        mode: str,
        max_concurrent: int,
        auth_bearer: str | None = None,
        auth_apikey: str | None = None,
        auth_basic: str | None = None,
    ) -> dict[str, Any]:
        if self.server is None:
            self.load()

        server = self.server

        resolved_spec_url = spec_url
        if not resolved_spec_url and swagger_ui_url:
            resolved_spec_url = _find_spec_url_from_swagger_ui(swagger_ui_url) or ""

        if not resolved_spec_url:
            raise ApiTesterBridgeError("Unable to resolve specification URL")

        spec_response = requests.get(resolved_spec_url, timeout=30)
        spec_response.raise_for_status()
        spec_content = spec_response.text

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        spec_file = output_path / "swagger-spec.json"
        spec_file.write_text(spec_content, encoding="utf-8")

        ingest_result = await server.ingest_spec(
            server.IngestSpecParams(
                spec_type="openapi",
                file_path=str(spec_file),
                preferred_language=language,
                preferred_framework=framework,
            )
        )
        if not ingest_result.get("success"):
            return {"success": False, "stage": "ingest_spec", "result": ingest_result}

        parsed_spec = ingest_result
        endpoints = parsed_spec.get("endpoints", [])
        base_url = base_url_override or parsed_spec.get("base_url") or ""
        if not base_url:
            base_url = _resolve_base_url_from_spec(spec_content)

        env_vars = _derive_env_vars(ingest_result.get("endpoints", []), base_url)
        env_vars.update(
            {
                "baseUrl": base_url.rstrip("/"),
            }
        )

        set_env_result = await server.set_env_vars(
            server.SetEnvVarsParams(
                variables=env_vars,
                baseUrl=base_url.rstrip("/") if base_url else None,
                auth_bearer=auth_bearer,
                auth_apikey=auth_apikey,
                auth_basic=auth_basic,
            )
        )
        if not set_env_result.get("success"):
            return {"success": False, "stage": "set_env_vars", "result": set_env_result}

        scenarios_result = await server.generate_scenarios(
            server.GenerateScenariosParams(
                include_negative_tests=include_negative_tests,
                include_edge_cases=include_edge_cases,
            )
        )
        if not scenarios_result.get("success"):
            return {
                "success": False,
                "stage": "generate_scenarios",
                "result": scenarios_result,
            }

        selected_scenario_ids = self._select_scenarios(
            server.current_session.scenarios,
            mode=mode,
            priority_plan=llm_plan or {},
        )

        test_cases_result = await server.generate_test_cases(
            server.GenerateTestCasesParams(scenario_ids=selected_scenario_ids)
        )
        if not test_cases_result.get("success"):
            return {
                "success": False,
                "stage": "generate_test_cases",
                "result": test_cases_result,
            }

        test_case_ids = [item["id"] for item in test_cases_result.get("test_cases", [])]
        run_result = await server.run_api_tests(
            server.RunApiTestsParams(
                test_case_ids=test_case_ids,
                max_concurrent=max_concurrent,
            )
        )
        if not run_result.get("success"):
            return {"success": False, "stage": "run_api_tests", "result": run_result}

        report_file = run_result.get("report_file")
        return {
            "success": True,
            "spec_url": resolved_spec_url,
            "base_url": base_url,
            "ingest": ingest_result,
            "set_env": set_env_result,
            "scenarios": scenarios_result,
            "test_cases": test_cases_result,
            "run": run_result,
            "report_file": report_file,
            "selected_scenario_ids": selected_scenario_ids,
            "selected_test_case_ids": test_case_ids,
        }

    def _select_scenarios(
        self,
        scenarios: list[Any],
        *,
        mode: str,
        priority_plan: dict[str, Any],
    ) -> list[str]:
        if not scenarios:
            return []

        if mode == "full":
            return [scenario.id for scenario in scenarios]

        priority_paths = {
            item.get("path")
            for item in priority_plan.get("priority_endpoints", [])
            if isinstance(item, dict) and item.get("path")
        }

        selected = []
        for scenario in scenarios:
            endpoint = getattr(scenario, "endpoint", None)
            if not endpoint:
                continue
            if endpoint.method != "GET":
                continue
            if priority_paths and endpoint.path not in priority_paths:
                continue
            if "Positive test for" not in scenario.name:
                continue
            selected.append(scenario.id)

        if selected:
            return selected

        # Fallback to all positive GET scenarios.
        return [
            scenario.id
            for scenario in scenarios
            if getattr(getattr(scenario, "endpoint", None), "method", "") == "GET"
            and "Positive test for" in scenario.name
        ]


def _resolve_base_url_from_spec(spec_text: str) -> str:
    try:
        spec = json.loads(spec_text)
    except Exception:
        return ""

    if spec.get("servers"):
        return spec["servers"][0].get("url", "").rstrip("/")

    if spec.get("host"):
        scheme = (spec.get("schemes") or ["https"])[0]
        base_path = spec.get("basePath", "")
        return f"{scheme}://{spec['host']}{base_path}".rstrip("/")

    return ""
