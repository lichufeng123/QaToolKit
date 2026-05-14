from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any
from urllib.parse import urljoin

import requests


HTTP_METHODS = ("get", "post", "put", "delete", "patch", "head", "options")


@dataclass
class Endpoint:
    method: str
    path: str
    summary: str = ""
    description: str = ""
    auth_required: bool = False
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] | None = None


def fetch_spec(spec_url: str, timeout: int = 30) -> dict[str, Any]:
    response = requests.get(spec_url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def extract_base_url(spec: dict[str, Any]) -> str:
    if spec.get("servers"):
        url = spec["servers"][0].get("url", "")
        return url.rstrip("/")

    host = spec.get("host")
    if host:
        scheme = (spec.get("schemes") or ["https"])[0]
        base_path = spec.get("basePath", "")
        return f"{scheme}://{host}{base_path}".rstrip("/")

    return ""


def normalize_endpoint_path(base_url: str, path: str) -> str:
    if not base_url:
        return path
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def parse_endpoints(spec: dict[str, Any]) -> list[Endpoint]:
    endpoints: list[Endpoint] = []
    global_security = spec.get("security", [])
    paths = spec.get("paths", {})

    for path, methods in paths.items():
        for method, operation in methods.items():
            if method.lower() not in HTTP_METHODS:
                continue

            auth_required = bool(global_security or operation.get("security"))
            endpoints.append(
                Endpoint(
                    method=method.upper(),
                    path=path,
                    summary=operation.get("summary", ""),
                    description=operation.get("description", ""),
                    auth_required=auth_required,
                    parameters=operation.get("parameters", []),
                    request_body=operation.get("requestBody"),
                )
            )

    return endpoints


def compact_spec_summary(spec: dict[str, Any]) -> dict[str, Any]:
    endpoints = parse_endpoints(spec)
    base_url = extract_base_url(spec)
    return {
        "title": spec.get("info", {}).get("title", ""),
        "version": spec.get("info", {}).get("version", ""),
        "base_url": base_url,
        "endpoint_count": len(endpoints),
        "endpoints": [
            {
                "method": ep.method,
                "path": ep.path,
                "summary": ep.summary,
                "auth_required": ep.auth_required,
            }
            for ep in endpoints
        ],
    }


def save_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def save_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
