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
        ]


class IterationStatsTests(unittest.TestCase):
    def test_summarize_iteration_uses_real_bug_dates_and_display_names(self) -> None:
        stats = summarize_iteration(
            iteration_name="自定义统计",
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 12),
            bug_source=FakeBugSource(),
        )

        self.assertEqual(stats["summary"]["submitted_total"], 2)
        self.assertEqual(stats["summary"]["closed_total"], 1)
        self.assertEqual(stats["summary"]["closed_today"], 1)
        self.assertEqual(stats["summary"]["active_total"], 1)
        self.assertEqual(stats["summary"]["close_rate"], 50.0)
        self.assertIn("赖彦彰", stats["developer_stats"])
        self.assertIn("石浩栋", stats["developer_stats"])
        self.assertEqual(stats["developer_stats"]["赖彦彰"]["remaining_total"], 1)
        self.assertEqual(stats["developer_stats"]["石浩栋"]["resolved_total"], 1)
        self.assertEqual(len(stats["daily_trend"]), 3)


if __name__ == "__main__":
    unittest.main()
