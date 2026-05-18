from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qatoolkit.web.task_store import TaskStore


class TaskStoreTests(unittest.TestCase):
    def test_delete_by_status_only_removes_matching_tasks(self) -> None:
        with TemporaryDirectory() as tmp:
            store = TaskStore(db_path=Path(tmp) / "tasks.db")
            failed = store.create(task_type="api_test", title="失败任务", task_input={})
            success = store.create(task_type="api_test", title="成功任务", task_input={})
            running = store.create(task_type="api_test", title="运行任务", task_input={})
            store.mark_failed(failed.id, "boom")
            store.mark_success(success.id, {"ok": True})
            store.mark_running(running.id)

            deleted = store.delete_by_status("failed", delete_artifacts=True)
            remaining = {task.id: task.status for task in store.list(limit=10)}

            self.assertEqual(deleted, [failed.id])
            self.assertEqual(remaining, {running.id: "running", success.id: "success"})


if __name__ == "__main__":
    unittest.main()
