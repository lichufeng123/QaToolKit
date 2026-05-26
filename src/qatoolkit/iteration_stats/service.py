from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import html
import json
from pathlib import Path
from typing import Any

import requests

from ..shared.environment import load_dotenv_file
from ..shared.paths import project_root as find_project_root


DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d")
DEFAULT_ZENTAO_PRODUCT_ID = 8

_CHINESE_PINYIN_MAP = {
    "赖": "lai",
    "石": "shi",
    "李": "li",
    "庞": "pang",
    "陈": "chen",
    "田": "tian",
    "王": "wang",
    "杨": "yang",
    "杜": "du",
    "建": "jian",
    "彦": "yan",
    "浩": "hao",
    "栋": "dong",
    "锦": "jin",
    "健": "jian",
    "豪": "hao",
    "晓": "xiao",
    "光": "guang",
    "龙": "long",
    "彰": "zhang",
    "恒": "heng",
    "皓": "hao",
    "庆": "qing",
    "志": "zhi",
    "蒙": "meng",
    "楚": "chu",
    "逢": "feng",
    "伟": "wei",
    "谢": "xie",
}


@dataclass(frozen=True)
class Iteration:
    name: str
    start_date: date
    zentao_project_id: str | None = None
    description: str = ""


def project_root() -> Path:
    return find_project_root(Path(__file__))


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned in {"0000-00-00", "0000-00-00 00:00:00"}:
        return None
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt)
            if fmt in {"%Y-%m-%d", "%Y/%m/%d"}:
                return datetime.combine(parsed.date(), time.min)
            return parsed
        except ValueError:
            continue
    return None


def load_iterations(path: str | Path | None = None) -> dict[str, Iteration]:
    config_path = Path(path) if path else project_root() / "data" / "iterations.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    result: dict[str, Iteration] = {}
    for item in payload.get("iterations", []):
        start_dt = parse_datetime(item.get("start_date"))
        if not start_dt:
            continue
        iteration = Iteration(
            name=item["name"],
            start_date=start_dt.date(),
            zentao_project_id=item.get("zentao_project_id"),
            description=item.get("description", ""),
        )
        result[iteration.name] = iteration
    return result


class ZentaoBugSource:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        account: str | None = None,
        password: str | None = None,
        token: str | None = None,
        product_id: int = DEFAULT_ZENTAO_PRODUCT_ID,
        timeout: int = 30,
        allow_sample_fallback: bool = False,
        user_name_map_file: str | Path | None = None,
        sample_file: str | Path | None = None,
    ):
        load_dotenv_file()
        self.base_url = base_url.rstrip("/") if base_url else None
        self.account = account
        self.password = password
        self.token = token
        self.product_id = product_id or DEFAULT_ZENTAO_PRODUCT_ID
        self.timeout = timeout
        self.allow_sample_fallback = allow_sample_fallback
        self.user_name_map = _load_user_name_map(user_name_map_file)
        self.user_name_roster = _load_user_name_roster(user_name_map_file)
        self.sample_file = Path(sample_file) if sample_file else project_root() / "data" / "sample_zentao_bugs.json"

    def fetch_bugs(self, iteration: Iteration, start_date: date, end_date: date) -> list[dict[str, Any]]:
        if self.base_url:
            return self._fetch_from_api(iteration, start_date, end_date)
        if self.allow_sample_fallback:
            return self._fetch_from_sample()
        raise RuntimeError(
            "未配置 ZenTao BASE_URL，且未显式启用样例回退；请配置 ZENTAO_BASE_URL 后再运行真实统计。"
        )

    def _fetch_from_sample(self) -> list[dict[str, Any]]:
        payload = json.loads(self.sample_file.read_text(encoding="utf-8"))
        return list(payload.get("bugs", []))

    def _fetch_from_api(self, iteration: Iteration, start_date: date, end_date: date) -> list[dict[str, Any]]:
        if not self.base_url:
            raise RuntimeError("ZenTao base_url is required for API mode")

        session = requests.Session()
        session.headers.update({"Accept": "application/json"})
        if self.account and self.password:
            token, login_user = self._login_context(session)
            if isinstance(login_user, dict):
                login_account = str(login_user.get("account") or self.account or "").strip()
                login_realname = str(login_user.get("realname") or "").strip()
                if login_account and login_realname:
                    self.user_name_map.setdefault(login_account, login_realname)
        elif self.token:
            token = self.token
        else:
            raise RuntimeError(
                "未配置 ZenTao 登录账号或可用 token，请设置 ZENTAO_ACCOUNT / ZENTAO_PASSWORD，或提供 ZENTAO_TOKEN"
            )
        endpoint = f"{self.base_url}/products/{self.product_id}/bugs"
        page_size = 1000
        all_bugs: list[dict[str, Any]] = []

        collected: list[dict[str, Any]] = []
        for page_id in range(1, 10_000):
            params = {
                "browseType": "all",
                "orderBy": "id_asc",
                "recPerPage": page_size,
                "pageID": page_id,
            }
            response = session.get(
                endpoint,
                params=params,
                headers={"token": token},
                timeout=self.timeout,
            )
            if response.status_code in {401, 403}:
                raise RuntimeError(
                    "ZenTao 获取 Bug 列表被拒绝，请确认 token 请求头、账号权限和产品 ID 是否正确。"
                )
            response.raise_for_status()
            payload = response.json()
            page_bugs = _extract_bug_list(payload)
            collected.extend(page_bugs)
            if len(page_bugs) < page_size:
                break
        all_bugs = collected
        if all_bugs:
            return all_bugs
        raise RuntimeError(
            f"无法从 ZenTao API 获取 Bug 列表，请检查登录方式、token 传递方式或产品 ID：{self.product_id}"
        )

    def _login_context(self, session: requests.Session) -> tuple[str, dict[str, Any] | None]:
        if not self.account or not self.password:
            raise RuntimeError(
                "未配置 ZenTao 登录账号或密码，请设置 ZENTAO_ACCOUNT 和 ZENTAO_PASSWORD"
            )

        response = session.post(
            f"{self.base_url}/users/login",
            json={"account": self.account, "password": self.password},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("status", "")).lower() != "success" or not payload.get("token"):
            raise RuntimeError(f"ZenTao 登录失败，返回内容：{payload}")
        return str(payload["token"]), payload.get("user") if isinstance(payload.get("user"), dict) else None

def summarize_iteration(
    *,
    iteration_name: str,
    start_date: date | None = None,
    end_date: date | None = None,
    iterations_file: str | Path | None = None,
    bug_source: ZentaoBugSource | None = None,
) -> dict[str, Any]:
    iterations = load_iterations(iterations_file)
    if iteration_name not in iterations:
        if not start_date:
            raise ValueError(f"Unknown iteration: {iteration_name}")
        iteration = Iteration(name=iteration_name, start_date=start_date)
    else:
        configured_iteration = iterations[iteration_name]
        iteration = (
            Iteration(
                name=configured_iteration.name,
                start_date=start_date,
                zentao_project_id=configured_iteration.zentao_project_id,
                description=configured_iteration.description,
            )
            if start_date
            else configured_iteration
        )

    today = date.today()
    actual_end_date = end_date or today
    warnings: list[str] = []
    if iteration.start_date > actual_end_date:
        warnings.append(
            f"迭代开始日期 {iteration.start_date.isoformat()} 晚于统计截止日期 {actual_end_date.isoformat()}，统计结果可能为空。"
        )

    source = bug_source or ZentaoBugSource()
    raw_bugs = source.fetch_bugs(iteration, iteration.start_date, actual_end_date)
    bugs = _filter_bugs(raw_bugs, iteration.start_date, actual_end_date)
    display_name_map = _build_display_name_map(raw_bugs, source.user_name_map, source.user_name_roster)

    submitted_total = len(bugs)
    submitted_yesterday = sum(1 for bug in bugs if _opened_on(bug, actual_end_date - timedelta(days=1)))
    closed_total = sum(1 for bug in bugs if _closed_in_range(bug, iteration.start_date, actual_end_date))
    closed_today = sum(1 for bug in raw_bugs if _closed_on(bug, actual_end_date))
    resolved_yesterday = sum(1 for bug in bugs if _resolved_on(bug, actual_end_date - timedelta(days=1)))
    active_bugs = [bug for bug in bugs if not _is_closed_at_end_date(bug, actual_end_date)]
    active_total = len(active_bugs)
    intermittent_active_bugs = [bug for bug in active_bugs if _is_intermittent_bug(bug)]

    developer_stats = _developer_stats(bugs, iteration.start_date, actual_end_date, display_name_map)
    developer_bug_groups = _developer_bug_groups(bugs, iteration.start_date, actual_end_date, display_name_map)
    developer_residual_bugs = _developer_residual_bugs(bugs, actual_end_date, display_name_map)
    daily_trend = _daily_trend(bugs, iteration.start_date, actual_end_date)
    daily_residual_bugs = _daily_residual_bugs(bugs, iteration.start_date, actual_end_date, display_name_map)
    avg_close_hours = _average_close_hours(bugs)

    severity_distribution = Counter(str(bug.get("severity") or "unknown") for bug in bugs)
    active_severity_distribution = Counter(str(bug.get("severity") or "unknown") for bug in active_bugs)
    opener_distribution = Counter(_display_name(str(bug.get("openedBy") or "unknown"), display_name_map) for bug in bugs)

    close_rate = round(closed_total / submitted_total * 100, 2) if submitted_total else 0.0

    return {
        "iteration": {
            "name": iteration.name,
            "start_date": iteration.start_date.isoformat(),
            "end_date": actual_end_date.isoformat(),
            "zentao_project_id": iteration.zentao_project_id,
            "description": iteration.description,
        },
        "source": {
            "type": "api" if source.base_url else "sample",
            "base_url": source.base_url,
            "product_id": source.product_id,
        },
        "warnings": warnings,
        "summary": {
            "submitted_total": submitted_total,
            "submitted_yesterday": submitted_yesterday,
            "closed_total": closed_total,
            "closed_today": closed_today,
            "resolved_yesterday": resolved_yesterday,
            "active_total": active_total,
            "actionable_active_total": active_total - len(intermittent_active_bugs),
            "intermittent_active_total": len(intermittent_active_bugs),
            "close_rate": close_rate,
            "average_close_hours": avg_close_hours,
        },
        "developer_stats": developer_stats,
        "developer_bug_groups": developer_bug_groups,
        "developer_residual_bugs": developer_residual_bugs,
        "daily_trend": daily_trend,
        "daily_residual_bugs": daily_residual_bugs,
        "severity_distribution": dict(severity_distribution),
        "active_severity_distribution": dict(active_severity_distribution),
        "opener_distribution": dict(opener_distribution),
        "display_name_map": display_name_map,
        "intermittent_active_bugs": intermittent_active_bugs,
        "risks": _quality_risks(
            active_total,
            close_rate,
            severity_distribution,
            developer_stats,
            intermittent_active_total=len(intermittent_active_bugs),
        ),
    }


def _report_output_path(stats: dict[str, Any], output_path: str | Path | None = None) -> Path:
    if output_path:
        output = Path(output_path)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = project_root() / "artifacts" / "iteration_reports" / f"{stats['iteration']['name']}_test_stats_{stats['iteration']['end_date']}_{timestamp}.html"

    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        return output

    stem = output.stem
    suffix = output.suffix
    for index in range(2, 10_000):
        candidate = output.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重名的报告文件名：{output}")


def _summary_card_output_path(stats: dict[str, Any], output_path: str | Path | None = None) -> Path:
    if output_path:
        output = Path(output_path)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = project_root() / "artifacts" / "iteration_reports" / f"{stats['iteration']['name']}_leader_card_{stats['iteration']['end_date']}_{timestamp}.svg"

    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        return output

    stem = output.stem
    suffix = output.suffix
    for index in range(2, 10_000):
        candidate = output.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重名的汇报卡片文件名：{output}")


def generate_report_html(stats: dict[str, Any], output_path: str | Path | None = None) -> str:
    output = _report_output_path(stats, output_path)

    summary = stats["summary"]
    severity_rows = _counter_rows(stats["severity_distribution"])
    active_severity_rows = _counter_rows(stats.get("active_severity_distribution", {}))
    display_name_map = stats.get("display_name_map", {})
    developer_blocks = _render_developer_sections(
        rows=stats["developer_stats"],
        bug_groups=stats.get("developer_bug_groups", {}),
        name_map=display_name_map,
    )
    trend_blocks = _render_expandable_day_sections(stats["daily_trend"], stats.get("daily_residual_bugs", {}), display_name_map)
    intermittent_rows = _bug_details_table(
        stats.get("intermittent_active_bugs", []),
        display_name_map,
        "暂无偶发待复现 Bug。",
    )
    risk_items = "".join(f"<li>{risk}</li>" for risk in stats["risks"]) or "<li>暂无明显风险。</li>"

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{stats['iteration']['name']} 测试统计报告</title>
  <style>
    body {{ margin: 0; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; background: #f5f7fb; color: #1f2937; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    header {{ display: flex; justify-content: space-between; align-items: end; gap: 24px; margin-bottom: 24px; }}
    h1 {{ margin: 0; font-size: 30px; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    .muted {{ color: #64748b; }}
    .grid {{ display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; box-shadow: 0 10px 24px rgba(15, 23, 42, .05); }}
    .metric {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
    .band {{ display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(320px, 0.95fr); gap: 16px; margin-top: 16px; align-items: start; }}
    .band--dev {{ grid-template-columns: 1fr; }}
    .wide {{ grid-column: 1 / -1; }}
    .dev-layout {{ display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.55fr); gap: 16px; align-items: start; }}
    .dev-list {{ min-width: 0; }}
    .side-panel {{ background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; }}
    .side-panel h3 {{ margin: 0 0 12px; font-size: 16px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ text-align: left; border-bottom: 1px solid #e5e7eb; padding: 9px 8px; }}
    th {{ color: #475569; background: #f8fafc; }}
    .bar {{ height: 10px; background: #e2e8f0; border-radius: 999px; overflow: hidden; }}
    .bar span {{ display: block; height: 100%; background: #2563eb; }}
    .risk li {{ margin: 8px 0; }}
    .notice {{ border-left: 4px solid #f59e0b; background: #fffbeb; }}
    .expandable {{ border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; margin-top: 12px; overflow: hidden; }}
    .expandable summary {{ list-style: none; cursor: pointer; padding: 14px 16px; display: grid; grid-template-columns: 144px minmax(0, 1fr); gap: 12px; align-items: start; }}
    .expandable summary::-webkit-details-marker {{ display: none; }}
    .expand-title {{ font-weight: 700; white-space: nowrap; line-height: 1.35; }}
    .expand-meta {{ color: #64748b; font-size: 13px; line-height: 1.45; }}
    .expand-body {{ padding: 0 16px 14px; }}
    .bug-table {{ margin-top: 12px; min-width: 920px; table-layout: auto; }}
    .bug-table th, .bug-table td {{ font-size: 13px; vertical-align: top; }}
    .bug-table th:nth-child(2), .bug-table td:nth-child(2) {{ min-width: 260px; line-height: 1.45; }}
    .bug-table th:nth-child(4), .bug-table td:nth-child(4),
    .bug-table th:nth-child(5), .bug-table td:nth-child(5),
    .bug-table th:nth-child(6), .bug-table td:nth-child(6) {{ min-width: 72px; white-space: nowrap; }}
    .bug-pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #eff6ff; color: #1d4ed8; font-size: 12px; }}
    .metric-links {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }}
    .metric-links details {{ border: 1px solid #e5e7eb; border-radius: 8px; background: #f8fafc; overflow: hidden; }}
    .metric-links details[open] {{ grid-column: 1 / -1; background: #fff; }}
    .metric-links summary {{ cursor: pointer; list-style: none; padding: 10px; display: block; }}
    .metric-links summary::-webkit-details-marker {{ display: none; }}
    .metric-links details[open] summary {{ border-bottom: 1px solid #e5e7eb; }}
    .metric-label {{ color: #64748b; font-size: 12px; }}
    .metric-value {{ display: block; color: #0f172a; font-size: 20px; font-weight: 700; margin-top: 4px; }}
    .metric-detail {{ padding: 0 10px 10px; overflow-x: auto; }}
    @media (max-width: 900px) {{ .grid, .band, .dev-layout {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 900px) {{ .metric-links {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>{stats['iteration']['name']} 测试统计报告</h1>
      <div class="muted">统计周期：{stats['iteration']['start_date']} 至 {stats['iteration']['end_date']}</div>
      <div class="muted">数据来源：{stats.get('source', {}).get('type', 'unknown')} | 产品ID：{stats.get('source', {}).get('product_id', '-') }</div>
    </div>
    <div class="muted">项目：{stats['iteration'].get('zentao_project_id') or '-'}</div>
  </header>

  <section class="grid">
    <div class="card"><div class="muted">累计提交 Bug</div><div class="metric">{summary['submitted_total']}</div></div>
    <div class="card"><div class="muted">昨日提交 Bug</div><div class="metric">{summary.get('submitted_yesterday', 0)}</div></div>
    <div class="card"><div class="muted">累计关闭 Bug</div><div class="metric">{summary['closed_total']}</div></div>
    <div class="card"><div class="muted">昨日解决 Bug</div><div class="metric">{summary.get('resolved_yesterday', 0)}</div></div>
    <div class="card"><div class="muted">遗留 Bug</div><div class="metric">{summary['active_total']}</div></div>
    <div class="card"><div class="muted">偶发待复现</div><div class="metric">{summary.get('intermittent_active_total', 0)}</div></div>
    <div class="card"><div class="muted">关闭率</div><div class="metric">{summary['close_rate']}%</div></div>
  </section>

  <section class="band band--dev">
    <div class="card">
      <h2>研发处理分布</h2>
      <div class="dev-layout">
        <div class="dev-list">{developer_blocks}</div>
        <div class="side-panel">
          <h3>全部缺陷严重度分布</h3>
          {severity_rows}
          <h3 style="margin-top:18px">遗留缺陷严重度分布</h3>
          {active_severity_rows}
        </div>
      </div>
    </div>
  </section>

  <section class="band">
    <div class="card">
      <h2>每日趋势</h2>
      {trend_blocks}
    </div>
    <div class="card risk">
      <h2>风险提示</h2>
      <ul>{risk_items}</ul>
    </div>
  </section>

  <section class="band band--dev">
    <div class="card notice">
      <h2>偶发待复现 Bug</h2>
      <div class="muted">标题以 [] 标记的 Bug 单独归类，通常为测试侧继续定位复现路径，不计入研发待处理分布。</div>
      {intermittent_rows}
    </div>
  </section>
</main>
</body>
</html>
"""
    output.write_text(html, encoding="utf-8")
    return str(output)


def generate_summary_card_svg(stats: dict[str, Any], output_path: str | Path | None = None) -> str:
    output = _summary_card_output_path(stats, output_path)
    summary = stats["summary"]
    active = int(summary.get("active_total") or 0)
    intermittent = int(summary.get("intermittent_active_total") or 0)
    actionable = int(summary.get("actionable_active_total") or max(active - intermittent, 0))
    risks = stats.get("risks") or ["暂无明显风险。"]
    active_severity = stats.get("active_severity_distribution", {})
    total_active_severity = sum(int(value) for value in active_severity.values()) or 1
    serious_active = int(active_severity.get("1", 0)) + int(active_severity.get("2", 0))
    serious_percent = round(serious_active / total_active_severity * 100, 1) if active else 0

    title = f"{stats['iteration']['name']} 测试状态汇报"
    period = f"{stats['iteration']['start_date']} 至 {stats['iteration']['end_date']}"
    metrics = [
        ("累计提交", summary["submitted_total"], "#2563eb"),
        ("累计关闭", summary["closed_total"], "#16a34a"),
        ("遗留 Bug", active, "#dc2626"),
        ("待研发处理", actionable, "#f97316"),
        ("偶发待复现", intermittent, "#ca8a04"),
        ("关闭率", f"{summary['close_rate']}%", "#0f766e"),
    ]
    metric_cards = []
    for index, (label, value, color) in enumerate(metrics):
        x = 48 + (index % 3) * 352
        y = 142 + (index // 3) * 126
        metric_cards.append(
            f"""
  <rect x="{x}" y="{y}" width="320" height="94" rx="14" fill="#ffffff" stroke="#dbe4f0"/>
  <text x="{x + 22}" y="{y + 34}" font-size="24" fill="#64748b">{_svg_text(label)}</text>
  <text x="{x + 22}" y="{y + 72}" font-size="38" font-weight="700" fill="{color}">{_svg_text(str(value))}</text>"""
        )

    risk_lines = [_svg_text(str(item)) for item in risks[:3]]
    while len(risk_lines) < 3:
        risk_lines.append("暂无补充风险。")
    severity_bar_width = 440
    serious_width = int(severity_bar_width * min(serious_percent, 100) / 100)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#f4f7fb"/>
  <rect x="28" y="28" width="1144" height="619" rx="24" fill="#ffffff" stroke="#dbe4f0"/>
  <text x="54" y="82" font-size="36" font-weight="700" fill="#0f172a">{_svg_text(title)}</text>
  <text x="54" y="120" font-size="22" fill="#64748b">统计周期：{_svg_text(period)} ｜ 产品ID：{_svg_text(str(stats.get('source', {}).get('product_id', '-')))}</text>
  {''.join(metric_cards)}

  <rect x="48" y="410" width="512" height="176" rx="16" fill="#f8fafc" stroke="#dbe4f0"/>
  <text x="76" y="454" font-size="26" font-weight="700" fill="#0f172a">遗留结构</text>
  <text x="76" y="500" font-size="22" fill="#334155">严重等级 1/2：{serious_active} 个，占遗留严重度 {serious_percent}%</text>
  <rect x="76" y="526" width="{severity_bar_width}" height="18" rx="9" fill="#e2e8f0"/>
  <rect x="76" y="526" width="{serious_width}" height="18" rx="9" fill="#ef4444"/>
  <text x="76" y="570" font-size="20" fill="#64748b">偶发待复现 Bug 已从研发待处理口径中单独拆出。</text>

  <rect x="592" y="410" width="532" height="176" rx="16" fill="#fff7ed" stroke="#fed7aa"/>
  <text x="620" y="454" font-size="26" font-weight="700" fill="#9a3412">汇报关注点</text>
  <text x="644" y="500" font-size="21" fill="#431407">1. {risk_lines[0]}</text>
  <text x="644" y="536" font-size="21" fill="#431407">2. {risk_lines[1]}</text>
  <text x="644" y="572" font-size="21" fill="#431407">3. {risk_lines[2]}</text>

  <text x="54" y="622" font-size="18" fill="#94a3b8">QAToolKit 自动生成，适合复制到日报、周报或发送给管理侧。</text>
</svg>
"""
    output.write_text(svg, encoding="utf-8")
    return str(output)


def _extract_bug_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("bugs", "data", "items", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _bug_opened_date(bug: dict[str, Any]) -> datetime | None:
    return parse_datetime(
        bug.get("openedDate")
        or bug.get("opened_at")
        or bug.get("openeddate")
        or bug.get("createdDate")
    )


def _bug_resolved_date(bug: dict[str, Any]) -> datetime | None:
    return parse_datetime(bug.get("resolvedDate") or bug.get("resolved_at"))


def _bug_closed_date(bug: dict[str, Any]) -> datetime | None:
    return parse_datetime(bug.get("closedDate") or bug.get("closed_at"))


def _filter_bugs(bugs: list[dict[str, Any]], start_date: date, end_date: date) -> list[dict[str, Any]]:
    result = []
    for bug in bugs:
        opened = _bug_opened_date(bug)
        if opened and start_date <= opened.date() <= end_date:
            result.append(bug)
    return result


def _opened_on(bug: dict[str, Any], target_date: date) -> bool:
    opened = _bug_opened_date(bug)
    return bool(opened and opened.date() == target_date)


def _status_text(bug: dict[str, Any]) -> str:
    return str(bug.get("status") or "").strip().lower()


def _is_intermittent_bug(bug: dict[str, Any]) -> bool:
    title = str(bug.get("title") or "").strip()
    return title.startswith("[") and "]" in title


def _is_closed_at_end_date(bug: dict[str, Any], target_date: date) -> bool:
    closed = _bug_closed_date(bug)
    if closed and closed.date() <= target_date:
        return True
    resolved = _bug_resolved_date(bug)
    if resolved and resolved.date() <= target_date and _status_text(bug) in {"closed", "resolved", "done"}:
        return True
    return _status_text(bug) in {"closed", "resolved", "done"}


def _closed_in_range(bug: dict[str, Any], start_date: date, end_date: date) -> bool:
    closed = _bug_closed_date(bug)
    if closed and start_date <= closed.date() <= end_date:
        return True
    resolved = _bug_resolved_date(bug)
    return bool(resolved and start_date <= resolved.date() <= end_date and _status_text(bug) in {"closed", "resolved", "done"})


def _closed_on(bug: dict[str, Any], target_date: date) -> bool:
    closed = _bug_closed_date(bug)
    if closed and closed.date() == target_date:
        return True
    resolved = _bug_resolved_date(bug)
    return bool(resolved and resolved.date() == target_date and _status_text(bug) in {"closed", "resolved", "done"})


def _resolved_on(bug: dict[str, Any], target_date: date) -> bool:
    resolved = _bug_resolved_date(bug)
    return bool(resolved and resolved.date() == target_date)


def _developer_stats(
    bugs: list[dict[str, Any]],
    start_date: date,
    end_date: date,
    name_map: dict[str, str] | None = None,
) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {
        "resolved_total": 0,
        "resolved_today": 0,
        "resolved_yesterday": 0,
        "remaining_total": 0,
    })
    name_map = name_map or {}

    for bug in bugs:
        opened = _bug_opened_date(bug)
        resolved = _bug_resolved_date(bug)
        if opened and start_date <= opened.date() <= end_date and not _is_closed_at_end_date(bug, end_date):
            if _is_intermittent_bug(bug):
                continue
            owner = _display_name(str(bug.get("assignedTo") or bug.get("openedBy") or "未指派"), name_map)
            stats[owner]["remaining_total"] += 1
        if resolved and start_date <= resolved.date() <= end_date:
            owner = _display_name(str(bug.get("resolvedBy") or bug.get("assignedTo") or "未知"), name_map)
            stats[owner]["resolved_total"] += 1
            if resolved.date() == end_date:
                stats[owner]["resolved_today"] += 1
            if resolved.date() == end_date - timedelta(days=1):
                stats[owner]["resolved_yesterday"] += 1

    return dict(stats)


def _developer_bug_groups(
    bugs: list[dict[str, Any]],
    start_date: date,
    end_date: date,
    name_map: dict[str, str],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    groups: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {
        "resolved_total": [],
        "resolved_today": [],
        "resolved_yesterday": [],
        "remaining_total": [],
    })

    for bug in bugs:
        opened = _bug_opened_date(bug)
        resolved = _bug_resolved_date(bug)
        if opened and start_date <= opened.date() <= end_date and not _is_closed_at_end_date(bug, end_date):
            if _is_intermittent_bug(bug):
                continue
            owner = _display_name(str(bug.get("assignedTo") or bug.get("openedBy") or "未指派"), name_map)
            groups[owner]["remaining_total"].append(bug)
        if resolved and start_date <= resolved.date() <= end_date:
            owner = _display_name(str(bug.get("resolvedBy") or bug.get("assignedTo") or "未知"), name_map)
            groups[owner]["resolved_total"].append(bug)
            if resolved.date() == end_date:
                groups[owner]["resolved_today"].append(bug)
            if resolved.date() == end_date - timedelta(days=1):
                groups[owner]["resolved_yesterday"].append(bug)

    return {name: dict(items) for name, items in groups.items()}


def _daily_trend(bugs: list[dict[str, Any]], start_date: date, end_date: date) -> list[dict[str, Any]]:
    if start_date > end_date:
        return []

    days = (end_date - start_date).days
    rows = []
    for offset in range(days + 1):
        current = date.fromordinal(start_date.toordinal() + offset)
        submitted = sum(1 for bug in bugs if (opened := _bug_opened_date(bug)) and opened.date() == current)
        closed = sum(1 for bug in bugs if _closed_on(bug, current))
        active = 0
        for bug in bugs:
            opened = _bug_opened_date(bug)
            if not opened or opened.date() > current:
                continue
            if _is_closed_at_end_date(bug, current):
                continue
            active += 1
        rows.append({
            "date": current.isoformat(),
            "submitted": submitted,
            "closed": closed,
            "active_end_of_day": active,
        })
    return rows


def _average_close_hours(bugs: list[dict[str, Any]]) -> float:
    durations = []
    for bug in bugs:
        opened = _bug_opened_date(bug)
        closed = _bug_closed_date(bug) or _bug_resolved_date(bug)
        if opened and closed and closed >= opened:
            durations.append((closed - opened).total_seconds() / 3600)
    return round(sum(durations) / len(durations), 2) if durations else 0.0


def _quality_risks(
    active_total: int,
    close_rate: float,
    severity_distribution: Counter,
    developer_stats: dict[str, dict[str, int]],
    intermittent_active_total: int = 0,
) -> list[str]:
    risks = []
    serious = int(severity_distribution.get("1", 0)) + int(severity_distribution.get("2", 0))
    if active_total > 0:
        risks.append(f"当前仍有 {active_total} 个遗留 Bug，需要关注收敛节奏。")
    if close_rate < 80 and sum(severity_distribution.values()) > 0:
        risks.append(f"缺陷关闭率为 {close_rate}%，低于 80%，版本收口风险偏高。")
    if serious > 0:
        risks.append(f"严重等级 1/2 的 Bug 共 {serious} 个，需要优先复盘。")
    if intermittent_active_total > 0:
        risks.append(f"当前有 {intermittent_active_total} 个偶发待复现 Bug，建议单独跟踪复现路径和证据收集。")
    for developer, item in developer_stats.items():
        if item["remaining_total"] >= 3:
            risks.append(f"{developer} 名下遗留 {item['remaining_total']} 个 Bug，可能存在处理瓶颈。")
    return risks


def _display_name(raw_name: str, name_map: dict[str, str]) -> str:
    candidate = raw_name.strip()
    return name_map.get(candidate, candidate)


def _normalize_name_key(value: str) -> str:
    raw = value.strip().lower()
    if not raw:
        return ""
    pieces: list[str] = []
    for char in raw:
        if "a" <= char <= "z" or "0" <= char <= "9":
            pieces.append(char)
        elif "\u4e00" <= char <= "\u9fff":
            pieces.append(_CHINESE_PINYIN_MAP.get(char, char))
    return "".join(pieces)


def _load_user_name_map(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict):
        return {str(key): str(value) for key, value in payload.items() if str(key).strip() and str(value).strip()}
    return {}


def _load_user_name_roster(path: str | Path | None) -> list[str]:
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    return []


def _build_display_name_map(
    bugs: list[dict[str, Any]],
    explicit_map: dict[str, str],
    roster: list[str],
) -> dict[str, str]:
    result = dict(explicit_map)
    if not roster:
        return result

    roster_lookup: dict[str, str] = {}
    for display_name in roster:
        key = _normalize_name_key(display_name)
        if key and key not in roster_lookup:
            roster_lookup[key] = display_name

    seen: list[str] = []
    for bug in bugs:
        for candidate in (
            str(bug.get("resolvedBy") or "").strip(),
            str(bug.get("assignedTo") or "").strip(),
            str(bug.get("openedBy") or "").strip(),
            str(bug.get("closedBy") or "").strip(),
        ):
            if candidate and candidate not in seen:
                seen.append(candidate)

    for raw_name in seen:
        if raw_name in result:
            continue
        normalized = _normalize_name_key(raw_name)
        if normalized and normalized in roster_lookup:
            result.setdefault(raw_name, roster_lookup[normalized])
            continue
        for roster_key, display_name in roster_lookup.items():
            if normalized and (normalized in roster_key or roster_key in normalized):
                result.setdefault(raw_name, display_name)
                break
    return result


def _bug_detail(bug: dict[str, Any], name_map: dict[str, str]) -> dict[str, str]:
    return {
        "id": html.escape(str(bug.get("id") or "")),
        "title": html.escape(str(bug.get("title") or "")),
        "status": html.escape(str(bug.get("status") or "")),
        "severity": html.escape(str(bug.get("severity") or "")),
        "priority": html.escape(str(bug.get("pri") or "")),
        "opened_by": html.escape(_display_name(str(bug.get("openedBy") or "未知"), name_map)),
        "assigned_to": html.escape(_display_name(str(bug.get("assignedTo") or "未指派"), name_map)),
        "resolved_by": html.escape(_display_name(str(bug.get("resolvedBy") or "未知"), name_map)),
        "opened_date": html.escape(str(bug.get("openedDate") or "")),
        "closed_date": html.escape(str(bug.get("closedDate") or "")),
        "title_text": html.escape(str(bug.get("title") or "")),
    }


def _svg_text(value: str) -> str:
    return html.escape(value, quote=False)


def _bug_details_table(bugs: list[dict[str, Any]], name_map: dict[str, str], empty_text: str = "没有遗留 Bug。") -> str:
    if not bugs:
        return f"<div class='muted'>{html.escape(empty_text)}</div>"

    rows = []
    for bug in bugs:
        detail = _bug_detail(bug, name_map)
        rows.append(
            "<tr>"
            f"<td>{detail['id']}</td>"
            f"<td>{detail['title']}</td>"
            f"<td><span class='bug-pill'>{detail['status']}</span></td>"
            f"<td>{detail['opened_by']}</td>"
            f"<td>{detail['assigned_to']}</td>"
            f"<td>{detail['resolved_by']}</td>"
            f"<td>{detail['opened_date']}</td>"
            f"<td>{detail['closed_date']}</td>"
            f"<td>{detail['severity']}</td>"
            f"<td>{detail['priority']}</td>"
            "</tr>"
        )

    return """
<table class="bug-table">
  <thead>
    <tr>
      <th>ID</th><th>标题</th><th>状态</th><th>提交人</th><th>指派给</th><th>解决者</th><th>创建时间</th><th>关闭时间</th><th>严重度</th><th>优先级</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
""".format(rows="".join(rows))


def _render_expandable_bug_sections(
    *,
    title_key: str,
    rows: dict[str, dict[str, int]],
    bug_groups: dict[str, list[dict[str, Any]]],
    summary_fields: tuple[str, ...],
    summary_labels: tuple[str, ...],
    summary_suffix: str,
    name_map: dict[str, str],
) -> str:
    blocks = []
    for name, summary in rows.items():
        stats_text = " | ".join(
            f"{label} {summary[field]}"
            for field, label in zip(summary_fields, summary_labels)
        )
        bug_items = bug_groups.get(name, [])
        blocks.append(
            f"""<details class="expandable {title_key}-row">
  <summary><span class="expand-title">{html.escape(name)}</span><span class="expand-meta">{stats_text} | {summary_suffix} {len(bug_items)} 个，点开看详情</span></summary>
  <div class="expand-body">{_bug_details_table(bug_items, name_map)}</div>
</details>"""
        )
    if not blocks:
        return "<div class='muted'>暂无数据</div>"
    return "".join(blocks)


def _render_developer_sections(
    *,
    rows: dict[str, dict[str, int]],
    bug_groups: dict[str, dict[str, list[dict[str, Any]]]],
    name_map: dict[str, str],
) -> str:
    if not rows:
        return "<div class='muted'>暂无数据</div>"

    labels = {
        "resolved_total": "累计解决",
        "resolved_today": "今日解决",
        "resolved_yesterday": "昨日解决",
        "remaining_total": "累计遗留",
    }
    empty_texts = {
        "resolved_total": "没有累计解决 Bug。",
        "resolved_today": "没有今日解决 Bug。",
        "resolved_yesterday": "没有昨日解决 Bug。",
        "remaining_total": "没有累计遗留 Bug。",
    }
    blocks = []
    for name, summary in rows.items():
        groups = bug_groups.get(name, {})
        metrics = []
        for field, label in labels.items():
            bug_items = groups.get(field, [])
            metrics.append(
                f"""<details>
  <summary><span class="metric-label">{label}</span><span class="metric-value">{summary.get(field, 0)}</span></summary>
  <div class="metric-detail">{_bug_details_table(bug_items, name_map, empty_texts[field])}</div>
</details>"""
            )
        stats_text = " | ".join(f"{label} {summary.get(field, 0)}" for field, label in labels.items())
        blocks.append(
            f"""<details class="expandable developer-row">
  <summary><span class="expand-title">{html.escape(name)}</span><span class="expand-meta">{stats_text}，点对应指标看明细</span></summary>
  <div class="expand-body"><div class="metric-links">{''.join(metrics)}</div></div>
</details>"""
        )
    return "".join(blocks)


def _render_expandable_day_sections(days: list[dict[str, Any]], bug_groups: dict[str, list[dict[str, Any]]], name_map: dict[str, str]) -> str:
    blocks = []
    for item in days:
        date_key = item["date"]
        bug_items = bug_groups.get(date_key, [])
        blocks.append(
            f"""<details class="expandable day-row">
  <summary><span class="expand-title">{html.escape(date_key)}</span><span class="expand-meta">提交 {item['submitted']} | 关闭 {item['closed']} | 日末遗留 {item['active_end_of_day']} | 点开看遗留 Bug</span></summary>
  <div class="expand-body">{_bug_details_table(bug_items, name_map)}</div>
</details>"""
        )
    if not blocks:
        return "<div class='muted'>暂无数据</div>"
    return "".join(blocks)


def _developer_residual_bugs(
    bugs: list[dict[str, Any]],
    end_date: date,
    name_map: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bug in bugs:
        opened = _bug_opened_date(bug)
        if not opened or opened.date() > end_date:
            continue
        if _is_closed_at_end_date(bug, end_date):
            continue
        if _is_intermittent_bug(bug):
            continue
        owner = _display_name(str(bug.get("assignedTo") or bug.get("openedBy") or "未指派"), name_map)
        groups[owner].append(bug)
    return dict(groups)


def _daily_residual_bugs(
    bugs: list[dict[str, Any]],
    start_date: date,
    end_date: date,
    name_map: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    if start_date > end_date:
        return groups
    days = (end_date - start_date).days
    for offset in range(days + 1):
        current = date.fromordinal(start_date.toordinal() + offset)
        residual = []
        for bug in bugs:
            opened = _bug_opened_date(bug)
            if not opened or opened.date() > current:
                continue
            if _is_closed_at_end_date(bug, current):
                continue
            residual.append(bug)
        groups[current.isoformat()] = residual
    return groups


def _counter_rows(counter: dict[str, int]) -> str:
    total = sum(counter.values()) or 1
    rows = []
    for name, count in sorted(counter.items(), key=lambda item: item[1], reverse=True):
        percent = round(count / total * 100, 1)
        rows.append(
            f"<div style='margin: 10px 0'><div style='display:flex;justify-content:space-between'><span>{name}</span><span>{count} ({percent}%)</span></div><div class='bar'><span style='width:{percent}%'></span></div></div>"
        )
    return "\n".join(rows) or "<div class='muted'>暂无数据</div>"
