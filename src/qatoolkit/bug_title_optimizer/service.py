from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import html
import json
from pathlib import Path
import re
from typing import Any

from ..iteration_stats import Iteration, ZentaoBugSource, load_iterations
from ..iteration_stats.service import _bug_opened_date, _is_closed_at_end_date
from ..shared.config import Settings
from ..shared.llm import build_chat_client
from ..shared.paths import project_root as find_project_root


HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")
JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


@dataclass
class BugTitleSuggestion:
    bug_id: str
    status: str
    old_title: str
    suggested_title: str
    reason: str
    confidence: float
    opened_date: str
    assigned_to: str
    resolved_by: str
    severity: str
    priority: str


@dataclass
class BugTitleOptimizationResult:
    iteration: dict[str, Any]
    source: dict[str, Any]
    generated_at: str
    status_filter: str
    analyzed_count: int
    changed_count: int
    suggestions: list[BugTitleSuggestion]
    json_report_path: str
    html_report_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "source": self.source,
            "generated_at": self.generated_at,
            "status_filter": self.status_filter,
            "analyzed_count": self.analyzed_count,
            "changed_count": self.changed_count,
            "suggestions": [asdict(item) for item in self.suggestions],
            "json_report_path": self.json_report_path,
            "html_report_path": self.html_report_path,
        }


def project_root() -> Path:
    return find_project_root(Path(__file__))


def optimize_bug_titles(
    *,
    iteration_name: str,
    settings: Settings,
    bug_source: ZentaoBugSource,
    start_date: date | None = None,
    end_date: date | None = None,
    iterations_file: str | Path | None = None,
    status_filter: str = "active",
    limit: int = 50,
    batch_size: int = 10,
    output_dir: str | Path | None = None,
) -> BugTitleOptimizationResult:
    iteration = _resolve_iteration(iteration_name, start_date, iterations_file)
    actual_end_date = end_date or date.today()
    raw_bugs = bug_source.fetch_bugs(iteration, iteration.start_date, actual_end_date)
    bugs = _select_bugs(raw_bugs, iteration.start_date, actual_end_date, status_filter)
    if limit > 0:
        bugs = bugs[:limit]

    client = build_chat_client(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        settings.llm_timeout,
    )
    if not client:
        raise RuntimeError("未配置 Qwen BASE_URL 或 MODEL，无法执行 Bug 标题优化。")

    suggestions: list[BugTitleSuggestion] = []
    for batch in _chunks(bugs, max(batch_size, 1)):
        suggestions.extend(_optimize_batch(client, batch))

    output_base = _output_base_path(iteration.name, actual_end_date, output_dir)
    result = BugTitleOptimizationResult(
        iteration={
            "name": iteration.name,
            "start_date": iteration.start_date.isoformat(),
            "end_date": actual_end_date.isoformat(),
        },
        source={
            "type": "api" if bug_source.base_url else "sample",
            "base_url": bug_source.base_url,
            "product_id": bug_source.product_id,
            "llm_model": settings.llm_model,
        },
        generated_at=datetime.now().isoformat(timespec="seconds"),
        status_filter=status_filter,
        analyzed_count=len(suggestions),
        changed_count=sum(1 for item in suggestions if item.suggested_title and item.suggested_title != item.old_title),
        suggestions=suggestions,
        json_report_path=str(output_base.with_suffix(".json")),
        html_report_path=str(output_base.with_suffix(".html")),
    )
    output_base.with_suffix(".json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_base.with_suffix(".html").write_text(_render_html(result), encoding="utf-8")
    return result


def _resolve_iteration(iteration_name: str, start_date: date | None, iterations_file: str | Path | None) -> Iteration:
    iterations = load_iterations(iterations_file)
    if iteration_name in iterations:
        configured = iterations[iteration_name]
        if start_date:
            return Iteration(
                name=configured.name,
                start_date=start_date,
                zentao_project_id=configured.zentao_project_id,
                description=configured.description,
            )
        return configured
    if not start_date:
        raise ValueError(f"Unknown iteration: {iteration_name}")
    return Iteration(name=iteration_name, start_date=start_date)


def _select_bugs(
    bugs: list[dict[str, Any]],
    start_date: date,
    end_date: date,
    status_filter: str,
) -> list[dict[str, Any]]:
    selected = []
    for bug in bugs:
        opened = _bug_opened_date(bug)
        if not opened or not (start_date <= opened.date() <= end_date):
            continue
        if status_filter == "active" and _is_closed_at_end_date(bug, end_date):
            continue
        if status_filter == "closed" and not _is_closed_at_end_date(bug, end_date):
            continue
        selected.append(bug)
    return selected


def _optimize_batch(client: Any, bugs: list[dict[str, Any]]) -> list[BugTitleSuggestion]:
    system = (
        "你是资深测试负责人，擅长把禅道 Bug 标题改成准确、客观、可检索的中文标题。"
        "只能输出严格 JSON，不要输出解释，不要使用 Markdown。"
    )
    user = json.dumps(
        {
            "task": "根据当前 Bug 标题和重现步骤，为每个 Bug 生成更清晰的标题建议。",
            "rules": [
                "标题必须是中文，保留核心模块、触发动作、异常现象。",
                "不要夸大问题，不要编造步骤里没有的信息。",
                "长度建议 12 到 36 个中文字符。",
                "如果原标题已经清晰，可以返回原标题。",
                "偶发类标题如果原标题有 []，建议标题仍保留 [偶发] 前缀。",
            ],
            "output_schema": {
                "items": [
                    {
                        "bug_id": "string",
                        "suggested_title": "string",
                        "reason": "string",
                        "confidence": 0.0,
                    }
                ]
            },
            "bugs": [_bug_prompt_item(bug) for bug in bugs],
        },
        ensure_ascii=False,
        indent=2,
    )
    content = client.chat(system=system, user=user)
    payload = _parse_json_payload(content)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise RuntimeError(f"Qwen 返回格式不符合预期：{content[:300]}")

    suggestion_by_id = {
        str(item.get("bug_id")): item
        for item in items
        if isinstance(item, dict) and item.get("bug_id") is not None
    }
    result = []
    for bug in bugs:
        bug_id = str(bug.get("id") or "")
        item = suggestion_by_id.get(bug_id, {})
        old_title = str(bug.get("title") or "").strip()
        suggested = str(item.get("suggested_title") or old_title).strip() or old_title
        result.append(
            BugTitleSuggestion(
                bug_id=bug_id,
                status=str(bug.get("status") or ""),
                old_title=old_title,
                suggested_title=suggested,
                reason=str(item.get("reason") or "模型未返回原因。").strip(),
                confidence=_parse_confidence(item.get("confidence")),
                opened_date=str(bug.get("openedDate") or ""),
                assigned_to=str(bug.get("assignedTo") or ""),
                resolved_by=str(bug.get("resolvedBy") or ""),
                severity=str(bug.get("severity") or ""),
                priority=str(bug.get("pri") or ""),
            )
        )
    return result


def _bug_prompt_item(bug: dict[str, Any]) -> dict[str, str]:
    return {
        "bug_id": str(bug.get("id") or ""),
        "title": str(bug.get("title") or ""),
        "steps": _clean_steps(str(bug.get("steps") or ""))[:1200],
        "status": str(bug.get("status") or ""),
        "severity": str(bug.get("severity") or ""),
        "priority": str(bug.get("pri") or ""),
    }


def _clean_steps(value: str) -> str:
    text = HTML_TAG_PATTERN.sub("\n", html.unescape(value))
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def _parse_json_payload(content: str) -> Any:
    cleaned = content.strip()
    block_match = JSON_BLOCK_PATTERN.search(cleaned)
    if block_match:
        cleaned = block_match.group(1).strip()
    return json.loads(cleaned)


def _parse_confidence(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score > 1:
        score = score / 100
    return round(max(0.0, min(score, 1.0)), 2)


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _output_base_path(iteration_name: str, end_date: date, output_dir: str | Path | None) -> Path:
    root = Path(output_dir) if output_dir else project_root() / "artifacts" / "bug_title_optimizations"
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = root / f"{iteration_name}_bug_title_optimization_{end_date.isoformat()}_{timestamp}"
    if not base.with_suffix(".json").exists() and not base.with_suffix(".html").exists():
        return base
    for index in range(2, 10_000):
        candidate = root / f"{base.name}_{index}"
        if not candidate.with_suffix(".json").exists() and not candidate.with_suffix(".html").exists():
            return candidate
    raise RuntimeError(f"无法生成不重名的 Bug 标题优化报告文件名：{root}")


def _render_html(result: BugTitleOptimizationResult) -> str:
    rows = []
    for item in result.suggestions:
        changed = "是" if item.suggested_title != item.old_title else "否"
        rows.append(
            "<tr>"
            f"<td>{html.escape(item.bug_id)}</td>"
            f"<td>{html.escape(item.status)}</td>"
            f"<td>{html.escape(item.old_title)}</td>"
            f"<td><strong>{html.escape(item.suggested_title)}</strong></td>"
            f"<td>{html.escape(item.reason)}</td>"
            f"<td>{item.confidence}</td>"
            f"<td>{changed}</td>"
            f"<td>{html.escape(item.assigned_to)}</td>"
            f"<td>{html.escape(item.severity)}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{html.escape(result.iteration['name'])} Bug 标题优化建议</title>
  <style>
    body {{ margin: 0; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; background: #f5f7fb; color: #0f172a; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    .muted {{ color: #64748b; }}
    .cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 18px 0; }}
    .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; }}
    .metric {{ font-size: 30px; font-weight: 700; margin-top: 6px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; font-size: 14px; line-height: 1.45; }}
    th {{ background: #f8fafc; color: #475569; white-space: nowrap; }}
    td:nth-child(3), td:nth-child(4), td:nth-child(5) {{ min-width: 220px; }}
  </style>
</head>
<body>
<main>
  <h1>{html.escape(result.iteration['name'])} Bug 标题优化建议</h1>
  <div class="muted">统计周期：{result.iteration['start_date']} 至 {result.iteration['end_date']} ｜ 模型：{html.escape(str(result.source.get('llm_model') or ''))}</div>
  <section class="cards">
    <div class="card"><div class="muted">分析 Bug</div><div class="metric">{result.analyzed_count}</div></div>
    <div class="card"><div class="muted">建议改名</div><div class="metric">{result.changed_count}</div></div>
    <div class="card"><div class="muted">筛选范围</div><div class="metric">{html.escape(result.status_filter)}</div></div>
  </section>
  <table>
    <thead>
      <tr><th>ID</th><th>状态</th><th>原标题</th><th>建议标题</th><th>优化理由</th><th>置信度</th><th>改动</th><th>指派给</th><th>严重度</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</main>
</body>
</html>
"""
