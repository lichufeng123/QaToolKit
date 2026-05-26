from __future__ import annotations

from datetime import date
from typing import Any
import unittest

from qatoolkit.iteration_stats import Iteration, summarize_iteration


class FakeBugSource:
    base_url = "https://zentao.example/api.php/v2"
    product_id = 8
    user_name_map = {
        "laiyanzhang": "赖彦彰",
        "shihaodong": "石浩栋",
    }
    user_name_roster: list[str] = []

    def fetch_bugs(self, iteration: Iteration, start_date: date, end_date: date) -> list[dict[str, Any]]:
        return [
            {
                "id": "1",
                "title": "未关闭缺陷",
                "openedBy": "tester",
                "assignedTo": "laiyanzhang",
                "openedDate": "2026-05-10 09:00:00",
                "status": "active",
                "severity": "2",
                "pri": "2",
            },
            {
                "id": "2",
                "title": "已关闭缺陷",
                "openedBy": "tester",
                "assignedTo": "shihaodong",
                "resolvedBy": "shihaodong",
                "openedDate": "2026-05-11 09:00:00",
                "resolvedDate": "2026-05-12 10:00:00",
                "closedDate": "2026-05-12 11:00:00",
                "status": "closed",
                "severity": "3",
                "pri": "3",
            },
            {
                "id": "3",
                "title": "统计周期外缺陷",
                "openedBy": "tester",
                "assignedTo": "laiyanzhang",
                "openedDate": "2026-05-13 09:00:00",
                "status": "active",
                "severity": "1",
                "pri": "1",
            },
            {
                "id": "4",
                "title": "[偶发] 登录后偶现白屏",
                "openedBy": "tester",
                "assignedTo": "tester",
                "openedDate": "2026-05-12 09:00:00",
                "status": "active",
                "severity": "3",
                "pri": "3",
            },
            {
                "id": "5",
                "title": "昨日解决并已关闭缺陷",
                "openedBy": "tester",
                "assignedTo": "closed",
                "resolvedBy": "shihaodong",
                "openedDate": "2026-05-11 14:00:00",
                "resolvedDate": "2026-05-11 18:00:00",
                "closedDate": "2026-05-12 09:00:00",
                "status": "closed",
                "severity": "2",
                "pri": "2",
            },
            {
                "id": "6",
                "title": "昨日解决未关闭缺陷",
                "openedBy": "tester",
                "assignedTo": "shihaodong",
                "resolvedBy": "shihaodong",
                "openedDate": "2026-05-11 15:00:00",
                "resolvedDate": "2026-05-11 19:00:00",
                "closedDate": "",
                "status": "active",
                "severity": "3",
                "pri": "3",
            },
        ]


class IterationStatsTests(unittest.TestCase):
    def test_summarize_iteration_uses_real_bug_dates_and_display_names(self) -> None:
        stats = summarize_iteration(
            iteration_name="自定义统计",
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 12),
            bug_source=FakeBugSource(),
        )

        self.assertEqual(stats["summary"]["submitted_total"], 5)
        self.assertEqual(stats["summary"]["submitted_yesterday"], 3)
        self.assertEqual(stats["summary"]["closed_total"], 2)
        self.assertEqual(stats["summary"]["closed_today"], 2)
        self.assertEqual(stats["summary"]["resolved_yesterday"], 2)
        self.assertEqual(stats["summary"]["active_total"], 3)
        self.assertEqual(stats["summary"]["actionable_active_total"], 2)
        self.assertEqual(stats["summary"]["intermittent_active_total"], 1)
        self.assertEqual(stats["summary"]["close_rate"], 40.0)
        self.assertEqual(stats["severity_distribution"], {"2": 2, "3": 3})
        self.assertEqual(stats["active_severity_distribution"], {"2": 1, "3": 2})
        self.assertIn("赖彦彰", stats["developer_stats"])
        self.assertIn("石浩栋", stats["developer_stats"])
        self.assertNotIn("tester", stats["developer_stats"])
        self.assertEqual(stats["developer_stats"]["赖彦彰"]["remaining_total"], 1)
        self.assertEqual(stats["developer_stats"]["石浩栋"]["remaining_total"], 1)
        self.assertEqual(stats["developer_stats"]["石浩栋"]["resolved_total"], 3)
        self.assertEqual(stats["developer_stats"]["石浩栋"]["resolved_today"], 1)
        self.assertEqual(stats["developer_stats"]["石浩栋"]["resolved_yesterday"], 2)
        self.assertEqual([bug["id"] for bug in stats["developer_bug_groups"]["赖彦彰"]["remaining_total"]], ["1"])
        self.assertEqual([bug["id"] for bug in stats["developer_bug_groups"]["石浩栋"]["resolved_total"]], ["2", "5", "6"])
        self.assertEqual([bug["id"] for bug in stats["developer_bug_groups"]["石浩栋"]["resolved_today"]], ["2"])
        self.assertEqual(
            [bug["id"] for bug in stats["developer_bug_groups"]["石浩栋"]["resolved_yesterday"]],
            ["5", "6"],
        )
        self.assertEqual([bug["id"] for bug in stats["intermittent_active_bugs"]], ["4"])
        self.assertEqual(len(stats["daily_trend"]), 3)


if __name__ == "__main__":
    unittest.main()
