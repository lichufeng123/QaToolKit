from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    try:
        from fastmcp import FastMCP
    except Exception:
        class FastMCP:
            def __init__(self, name: str):
                self.name = name

            def tool(self):
                def decorator(func):
                    return func

                return decorator

            def run(self):
                raise RuntimeError("请先安装 MCP SDK 后再启动 MCP Server：pip install mcp")

from ..iteration_stats import (
    ZentaoBugSource,
    generate_report_html,
    load_iterations,
    summarize_iteration,
)


mcp = FastMCP("QAToolKit ZenTao Stats")


def _bug_source() -> ZentaoBugSource:
    return ZentaoBugSource(
        base_url=os.getenv("ZENTAO_BASE_URL"),
        account=os.getenv("ZENTAO_ACCOUNT") or os.getenv("ZENTAO_USER") or os.getenv("ZENTAO_USERNAME"),
        password=os.getenv("ZENTAO_PASSWORD") or os.getenv("ZENTAO_PASS"),
        token=os.getenv("ZENTAO_TOKEN"),
        product_id=int(os.getenv("ZENTAO_PRODUCT_ID", "8")),
        timeout=int(os.getenv("ZENTAO_TIMEOUT", "30")),
        allow_sample_fallback=os.getenv("ZENTAO_ALLOW_SAMPLE_FALLBACK", "0").strip().lower() in {"1", "true", "yes"},
        user_name_map_file=os.getenv("ZENTAO_USER_MAP_FILE"),
        sample_file=os.getenv("ZENTAO_SAMPLE_BUGS_FILE"),
    )


@mcp.tool()
def list_iterations() -> str:
    """列出当前已配置的测试迭代，包括迭代名称、起测日期和禅道项目标识。"""
    iterations = load_iterations(os.getenv("ITERATIONS_FILE"))
    payload = [
        {
            "name": item.name,
            "start_date": item.start_date.isoformat(),
            "zentao_project_id": item.zentao_project_id,
            "description": item.description,
        }
        for item in iterations.values()
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def get_iteration_test_stats(iteration: str, end_date: str | None = None) -> str:
    """获取指定版本迭代的测试缺陷统计，包括提交、关闭、遗留、研发分布、模块分布和每日趋势。"""
    parsed_end_date = date.fromisoformat(end_date) if end_date else None
    stats = summarize_iteration(
        iteration_name=iteration,
        end_date=parsed_end_date,
        iterations_file=os.getenv("ITERATIONS_FILE"),
        bug_source=_bug_source(),
    )
    return json.dumps(stats, ensure_ascii=False, indent=2)


@mcp.tool()
def generate_iteration_report(iteration: str, end_date: str | None = None, output_path: str | None = None) -> str:
    """生成指定版本迭代的 HTML 测试统计报告，返回报告文件路径。"""
    parsed_end_date = date.fromisoformat(end_date) if end_date else None
    stats = summarize_iteration(
        iteration_name=iteration,
        end_date=parsed_end_date,
        iterations_file=os.getenv("ITERATIONS_FILE"),
        bug_source=_bug_source(),
    )
    report_path = generate_report_html(stats, Path(output_path) if output_path else None)
    return report_path


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
