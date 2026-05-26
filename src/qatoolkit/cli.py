from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .api_testing.agent import ApiTesterAgent
from .bug_title_optimizer import optimize_bug_titles
from .iteration_stats import (
    ZentaoBugSource,
    generate_report_html,
    generate_summary_card_svg,
    load_iterations,
    summarize_iteration,
)
from .shared.config import load_settings
from .testcase_import import import_testcases_from_excel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QAToolKit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the API testing workflow")
    run_parser.add_argument("--spec-url", help="OpenAPI/Swagger JSON URL")
    run_parser.add_argument("--swagger-ui-url", help="Swagger UI page URL")
    run_parser.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    run_parser.add_argument("--language", choices=["python", "typescript", "javascript"])
    run_parser.add_argument("--framework", choices=["requests", "pytest", "playwright", "jest", "cypress", "supertest"])
    run_parser.add_argument("--output-dir", help="Output directory for generated artifacts")
    run_parser.add_argument("--api-tester-mcp-source", help="Path to api_tester_mcp source folder")
    run_parser.add_argument("--base-url", help="Override base URL used for requests")
    run_parser.add_argument("--auth-bearer", help="Bearer token")
    run_parser.add_argument("--auth-apikey", help="API key")
    run_parser.add_argument("--auth-basic", help="Base64 basic auth credentials")
    run_parser.add_argument("--max-concurrent", type=int, default=10)
    run_parser.add_argument("--no-negative", action="store_true", help="Skip negative scenarios")
    run_parser.add_argument("--no-edge", action="store_true", help="Skip edge scenarios")

    inspect_parser = subparsers.add_parser("inspect", help="Fetch and summarize a Swagger/OpenAPI spec")
    inspect_parser.add_argument("--spec-url", required=True, help="OpenAPI/Swagger JSON URL")
    inspect_parser.add_argument("--output-dir", help="Output directory for artifacts")

    iteration_list_parser = subparsers.add_parser("iteration-list", help="List configured test iterations")
    iteration_list_parser.add_argument("--iterations-file", help="Path to iterations.json")

    iteration_stats_parser = subparsers.add_parser("iteration-stats", help="Show test statistics for an iteration")
    iteration_stats_parser.add_argument("--iteration", required=True, help="Iteration name, for example V3.4")
    iteration_stats_parser.add_argument("--start-date", help="Statistics start date, yyyy-mm-dd")
    iteration_stats_parser.add_argument("--end-date", help="Statistics end date, yyyy-mm-dd")
    iteration_stats_parser.add_argument("--iterations-file", help="Path to iterations.json")
    iteration_stats_parser.add_argument("--sample-bugs-file", help="Path to sample ZenTao bugs JSON")
    iteration_stats_parser.add_argument("--zentao-base-url", help="ZenTao API base URL")
    iteration_stats_parser.add_argument("--zentao-account", help="ZenTao login account")
    iteration_stats_parser.add_argument("--zentao-password", help="ZenTao login password")
    iteration_stats_parser.add_argument("--zentao-token", help="ZenTao API token")
    iteration_stats_parser.add_argument("--zentao-product-id", type=int, help="ZenTao product ID")
    iteration_stats_parser.add_argument("--zentao-timeout", type=int, help="ZenTao API timeout")
    iteration_stats_parser.add_argument("--allow-sample-fallback", action="store_true", help="Allow local sample bugs as fallback")
    iteration_stats_parser.add_argument("--zentao-user-map-file", help="Path to account-to-Chinese-name map JSON")

    iteration_report_parser = subparsers.add_parser("iteration-report", help="Generate an HTML test statistics report")
    iteration_report_parser.add_argument("--iteration", required=True, help="Iteration name, for example V3.4")
    iteration_report_parser.add_argument("--start-date", help="Statistics start date, yyyy-mm-dd")
    iteration_report_parser.add_argument("--end-date", help="Statistics end date, yyyy-mm-dd")
    iteration_report_parser.add_argument("--iterations-file", help="Path to iterations.json")
    iteration_report_parser.add_argument("--sample-bugs-file", help="Path to sample ZenTao bugs JSON")
    iteration_report_parser.add_argument("--zentao-base-url", help="ZenTao API base URL")
    iteration_report_parser.add_argument("--zentao-account", help="ZenTao login account")
    iteration_report_parser.add_argument("--zentao-password", help="ZenTao login password")
    iteration_report_parser.add_argument("--zentao-token", help="ZenTao API token")
    iteration_report_parser.add_argument("--zentao-product-id", type=int, help="ZenTao product ID")
    iteration_report_parser.add_argument("--zentao-timeout", type=int, help="ZenTao API timeout")
    iteration_report_parser.add_argument("--allow-sample-fallback", action="store_true", help="Allow local sample bugs as fallback")
    iteration_report_parser.add_argument("--zentao-user-map-file", help="Path to account-to-Chinese-name map JSON")
    iteration_report_parser.add_argument("--output-path", help="Report output path")
    iteration_report_parser.add_argument("--summary-card-path", help="Leader summary SVG output path")
    iteration_report_parser.add_argument("--no-summary-card", action="store_true", help="Skip leader summary SVG generation")

    bug_title_parser = subparsers.add_parser("optimize-bug-titles", help="Generate Qwen-based ZenTao bug title suggestions")
    bug_title_parser.add_argument("--iteration", required=True, help="Iteration name, for example V3.4")
    bug_title_parser.add_argument("--start-date", help="Statistics start date, yyyy-mm-dd")
    bug_title_parser.add_argument("--end-date", help="Statistics end date, yyyy-mm-dd")
    bug_title_parser.add_argument("--iterations-file", help="Path to iterations.json")
    bug_title_parser.add_argument("--status", choices=["active", "closed", "all"], default="active", help="Bug status filter")
    bug_title_parser.add_argument("--limit", type=int, default=50, help="Max bugs to analyze; <=0 means no limit")
    bug_title_parser.add_argument("--batch-size", type=int, default=10, help="Bugs per Qwen request")
    bug_title_parser.add_argument("--output-dir", help="Report output directory")
    bug_title_parser.add_argument("--llm-base-url", help="Qwen/OpenAI-compatible base URL")
    bug_title_parser.add_argument("--llm-api-key", help="Qwen API key")
    bug_title_parser.add_argument("--llm-model", help="Qwen model name")
    bug_title_parser.add_argument("--llm-timeout", type=int, help="Qwen request timeout")
    bug_title_parser.add_argument("--zentao-base-url", help="ZenTao API base URL")
    bug_title_parser.add_argument("--zentao-account", help="ZenTao login account")
    bug_title_parser.add_argument("--zentao-password", help="ZenTao login password")
    bug_title_parser.add_argument("--zentao-token", help="ZenTao API token")
    bug_title_parser.add_argument("--zentao-product-id", type=int, help="ZenTao product ID")
    bug_title_parser.add_argument("--zentao-timeout", type=int, help="ZenTao API timeout")
    bug_title_parser.add_argument("--allow-sample-fallback", action="store_true", help="Allow local sample bugs as fallback")
    bug_title_parser.add_argument("--zentao-user-map-file", help="Path to account-to-Chinese-name map JSON")
    bug_title_parser.add_argument("--sample-bugs-file", help="Path to sample ZenTao bugs JSON")

    testcase_import_parser = subparsers.add_parser("import-testcases", help="Import Excel testcases into ZenTao")
    testcase_import_parser.add_argument("--excel-file", required=True, help="Path to the Excel testcase workbook")
    testcase_import_parser.add_argument("--sheet", action="append", dest="sheets", help="Only import the specified sheet name; can be repeated")
    testcase_import_parser.add_argument("--dry-run", action="store_true", help="Parse and validate Excel without creating testcases in ZenTao")
    testcase_import_parser.add_argument("--zentao-base-url", help="ZenTao API base URL")
    testcase_import_parser.add_argument("--zentao-account", help="ZenTao login account")
    testcase_import_parser.add_argument("--zentao-password", help="ZenTao login password")
    testcase_import_parser.add_argument("--zentao-token", help="ZenTao API token")
    testcase_import_parser.add_argument("--zentao-product-id", type=int, help="ZenTao product ID")
    testcase_import_parser.add_argument("--zentao-timeout", type=int, help="ZenTao API timeout")
    testcase_import_parser.add_argument("--output-path", help="Import result output path")

    web_parser = subparsers.add_parser("web", help="Start the QAToolKit web application")
    web_parser.add_argument("--host", default="127.0.0.1", help="Web server host")
    web_parser.add_argument("--port", type=int, default=8000, help="Web server port")
    web_parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")

    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()
    settings = load_settings()

    if getattr(args, "output_dir", None):
        settings = settings.__class__(
            **{**settings.__dict__, "output_dir": str(Path(args.output_dir).expanduser().resolve())}
        )

    if args.command == "inspect":
        agent = ApiTesterAgent(settings)
        result = agent._build_llm_plan(
            spec_url=args.spec_url,
            swagger_ui_url=None,
            base_url_override=None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "iteration-list":
        result = [
            {
                "name": item.name,
                "start_date": item.start_date.isoformat(),
                "zentao_project_id": item.zentao_project_id,
                "description": item.description,
            }
            for item in load_iterations(args.iterations_file or os.getenv("ITERATIONS_FILE")).values()
        ]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command in {"iteration-stats", "iteration-report"}:
        start_date = None
        end_date = None
        if args.start_date:
            from datetime import date

            start_date = date.fromisoformat(args.start_date)
        if args.end_date:
            from datetime import date

            end_date = date.fromisoformat(args.end_date)
        bug_source = ZentaoBugSource(
            base_url=args.zentao_base_url or os.getenv("ZENTAO_BASE_URL"),
            account=args.zentao_account or os.getenv("ZENTAO_ACCOUNT") or os.getenv("ZENTAO_USER") or os.getenv("ZENTAO_USERNAME"),
            password=args.zentao_password or os.getenv("ZENTAO_PASSWORD") or os.getenv("ZENTAO_PASS"),
            token=args.zentao_token or os.getenv("ZENTAO_TOKEN"),
            product_id=args.zentao_product_id or int(os.getenv("ZENTAO_PRODUCT_ID", "8")),
            timeout=args.zentao_timeout or int(os.getenv("ZENTAO_TIMEOUT", "30")),
            allow_sample_fallback=args.allow_sample_fallback
            or os.getenv("ZENTAO_ALLOW_SAMPLE_FALLBACK", "0").strip().lower() in {"1", "true", "yes"},
            user_name_map_file=args.zentao_user_map_file or os.getenv("ZENTAO_USER_MAP_FILE"),
            sample_file=args.sample_bugs_file or os.getenv("ZENTAO_SAMPLE_BUGS_FILE"),
        )
        stats = summarize_iteration(
            iteration_name=args.iteration,
            start_date=start_date,
            end_date=end_date,
            iterations_file=args.iterations_file or os.getenv("ITERATIONS_FILE"),
            bug_source=bug_source,
        )
        if args.command == "iteration-stats":
            print(json.dumps(stats, ensure_ascii=False, indent=2))
            return

        report_path = generate_report_html(stats, args.output_path)
        summary_card_path = None if args.no_summary_card else generate_summary_card_svg(stats, args.summary_card_path)
        print(
            json.dumps(
                {"report_path": report_path, "summary_card_path": summary_card_path, "stats": stats},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "optimize-bug-titles":
        from datetime import date

        start_date = date.fromisoformat(args.start_date) if args.start_date else None
        end_date = date.fromisoformat(args.end_date) if args.end_date else None
        bug_source = ZentaoBugSource(
            base_url=args.zentao_base_url or os.getenv("ZENTAO_BASE_URL"),
            account=args.zentao_account or os.getenv("ZENTAO_ACCOUNT") or os.getenv("ZENTAO_USER") or os.getenv("ZENTAO_USERNAME"),
            password=args.zentao_password or os.getenv("ZENTAO_PASSWORD") or os.getenv("ZENTAO_PASS"),
            token=args.zentao_token or os.getenv("ZENTAO_TOKEN"),
            product_id=args.zentao_product_id or int(os.getenv("ZENTAO_PRODUCT_ID", "8")),
            timeout=args.zentao_timeout or int(os.getenv("ZENTAO_TIMEOUT", "30")),
            allow_sample_fallback=args.allow_sample_fallback
            or os.getenv("ZENTAO_ALLOW_SAMPLE_FALLBACK", "0").strip().lower() in {"1", "true", "yes"},
            user_name_map_file=args.zentao_user_map_file or os.getenv("ZENTAO_USER_MAP_FILE"),
            sample_file=args.sample_bugs_file or os.getenv("ZENTAO_SAMPLE_BUGS_FILE"),
        )
        result = optimize_bug_titles(
            iteration_name=args.iteration,
            settings=settings.__class__(
                **{
                    **settings.__dict__,
                    "llm_base_url": args.llm_base_url or settings.llm_base_url,
                    "llm_api_key": args.llm_api_key or settings.llm_api_key,
                    "llm_model": args.llm_model or settings.llm_model,
                    "llm_timeout": args.llm_timeout or settings.llm_timeout,
                }
            ),
            bug_source=bug_source,
            start_date=start_date,
            end_date=end_date,
            iterations_file=args.iterations_file or os.getenv("ITERATIONS_FILE"),
            status_filter=args.status,
            limit=args.limit,
            batch_size=args.batch_size,
            output_dir=args.output_dir,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return

    if args.command == "import-testcases":
        result = import_testcases_from_excel(
            workbook_path=args.excel_file,
            base_url=args.zentao_base_url or os.getenv("ZENTAO_BASE_URL") or "",
            account=args.zentao_account or os.getenv("ZENTAO_ACCOUNT") or os.getenv("ZENTAO_USER") or os.getenv("ZENTAO_USERNAME"),
            password=args.zentao_password or os.getenv("ZENTAO_PASSWORD") or os.getenv("ZENTAO_PASS"),
            token=args.zentao_token or os.getenv("ZENTAO_TOKEN"),
            product_id=args.zentao_product_id or int(os.getenv("ZENTAO_PRODUCT_ID", "8")),
            timeout=args.zentao_timeout or int(os.getenv("ZENTAO_TIMEOUT", "30")),
            dry_run=args.dry_run,
            output_path=args.output_path,
            sheet_names=args.sheets,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return

    if args.command == "web":
        import uvicorn

        uvicorn.run("qatoolkit.web.app:app", host=args.host, port=args.port, reload=args.reload)
        return

    if args.command == "run":
        if getattr(args, "api_tester_mcp_source", None):
            settings = settings.__class__(
                **{**settings.__dict__, "api_tester_mcp_source": args.api_tester_mcp_source}
            )

        agent = ApiTesterAgent(settings)
        result = agent.run(
            spec_url=args.spec_url,
            swagger_ui_url=args.swagger_ui_url,
            mode=args.mode,
            language=args.language,
            framework=args.framework,
            include_negative_tests=not args.no_negative,
            include_edge_cases=not args.no_edge,
            max_concurrent=args.max_concurrent,
            base_url_override=args.base_url,
            auth_bearer=args.auth_bearer,
            auth_apikey=args.auth_apikey,
            auth_basic=args.auth_basic,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
