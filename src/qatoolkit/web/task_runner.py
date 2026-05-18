from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import traceback
from typing import Any, Callable

from .task_store import TaskRecord, TaskStore


TaskFunction = Callable[[str, TaskStore], tuple[dict[str, Any], str | None]]


class TaskRunner:
    def __init__(self, store: TaskStore, *, max_workers: int = 3):
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qatoolkit-task")

    def submit(
        self,
        *,
        task_type: str,
        title: str,
        task_input: dict[str, Any],
        task_fn: TaskFunction,
    ) -> TaskRecord:
        task = self.store.create(task_type=task_type, title=title, task_input=task_input)
        self.executor.submit(self._run, task.id, task_fn)
        return task

    def _run(self, task_id: str, task_fn: TaskFunction) -> None:
        self.store.mark_running(task_id)
        self.store.append_log(task_id, "任务开始执行。")
        try:
            output, report_path = task_fn(task_id, self.store)
            self.store.mark_success(task_id, output, report_path)
            self.store.append_log(task_id, "任务执行成功。")
        except Exception as exc:
            self.store.append_log(task_id, traceback.format_exc())
            self.store.mark_failed(task_id, str(exc))

