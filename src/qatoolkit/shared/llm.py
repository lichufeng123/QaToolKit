from __future__ import annotations

import json
from typing import Any

import requests


class LocalModelError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str | None, model: str, timeout: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(self, system: str, user: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        if not response.ok:
            raise LocalModelError(
                f"local model request failed: {response.status_code} {response.text}"
            )

        data: dict[str, Any] = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LocalModelError(f"unexpected model response: {json.dumps(data)}") from exc


def build_chat_client(
    base_url: str | None,
    api_key: str | None,
    model: str | None,
    timeout: int,
) -> OpenAICompatibleClient | None:
    if not base_url or not model:
        return None
    return OpenAICompatibleClient(base_url, api_key, model, timeout)


def fallback_test_plan(summary: dict[str, Any]) -> dict[str, Any]:
    endpoints = summary["endpoints"]
    preferred_paths = [
        "/store/inventory",
        "/store/order/{orderId}",
        "/user/login",
        "/user/logout",
    ]
    smoke = [
        e
        for path in preferred_paths
        for e in endpoints
        if e["method"] == "GET" and e["path"] == path
    ][:10]
    return {
        "mode": "fallback",
        "focus": "只读接口 smoke 测试",
        "priority_endpoints": smoke,
        "negative_focus": [
            "对鉴权接口检查 401/403",
            "对分页接口检查非法参数",
            "对 path 参数检查不存在的资源",
        ],
    }
