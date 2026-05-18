from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Any, Iterator
from uuid import uuid4

from ..shared.paths import project_root


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _json_load(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


@dataclass(frozen=True)
class TaskRecord:
    id: str
    type: str
    status: str
    title: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: str | None
    logs: str
    artifact_dir: str
    report_path: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "title": self.title,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "logs": self.logs,
            "artifact_dir": self.artifact_dir,
            "report_path": self.report_path,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class TaskStore:
    def __init__(self, db_path: str | Path | None = None):
        root = project_root(Path(__file__))
        self.base_dir = root / "artifacts" / "tasks"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else self.base_dir / "tasks.db"
        self._lock = threading.RLock()
        self._init_db()

    def create(self, *, task_type: str, title: str, task_input: dict[str, Any]) -> TaskRecord:
        task_id = uuid4().hex
        artifact_dir = self.base_dir / task_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        created_at = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into tasks (
                    id, type, status, title, input_json, output_json, error, logs,
                    artifact_dir, report_path, created_at, started_at, finished_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    task_type,
                    "pending",
                    title,
                    _json_dump(task_input),
                    None,
                    None,
                    "",
                    str(artifact_dir),
                    None,
                    created_at,
                    None,
                    None,
                ),
            )
        return self.get(task_id)

    def list(self, *, limit: int = 50) -> list[TaskRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "select * from tasks order by created_at desc limit ?",
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, task_id: str) -> TaskRecord:
        with self._lock, self._connect() as conn:
            row = conn.execute("select * from tasks where id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._row_to_record(row)

    def mark_running(self, task_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "update tasks set status = ?, started_at = ? where id = ?",
                ("running", _now(), task_id),
            )

    def mark_success(self, task_id: str, output: dict[str, Any], report_path: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                update tasks
                set status = ?, output_json = ?, report_path = ?, finished_at = ?
                where id = ?
                """,
                ("success", _json_dump(output), report_path, _now(), task_id),
            )

    def mark_failed(self, task_id: str, error: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "update tasks set status = ?, error = ?, finished_at = ? where id = ?",
                ("failed", error, _now(), task_id),
            )

    def append_log(self, task_id: str, message: str) -> None:
        line = f"[{_now()}] {message.rstrip()}\n"
        with self._lock, self._connect() as conn:
            row = conn.execute("select logs from tasks where id = ?", (task_id,)).fetchone()
            logs = (row["logs"] if row else "") + line
            conn.execute("update tasks set logs = ? where id = ?", (logs, task_id))

    def delete(self, task_id: str, *, delete_artifacts: bool = False) -> None:
        record = self.get(task_id)
        with self._lock, self._connect() as conn:
            conn.execute("delete from tasks where id = ?", (task_id,))
        if delete_artifacts:
            artifact_dir = Path(record.artifact_dir).resolve()
            base_dir = self.base_dir.resolve()
            if base_dir in [artifact_dir, *artifact_dir.parents] and artifact_dir.exists():
                shutil.rmtree(artifact_dir)

    def delete_by_status(self, status: str, *, delete_artifacts: bool = False) -> list[str]:
        with self._lock:
            records = [record for record in self.list(limit=100_000) if record.status == status]
            for record in records:
                with self._connect() as conn:
                    conn.execute("delete from tasks where id = ?", (record.id,))
                if delete_artifacts:
                    artifact_dir = Path(record.artifact_dir).resolve()
                    base_dir = self.base_dir.resolve()
                    if base_dir in [artifact_dir, *artifact_dir.parents] and artifact_dir.exists():
                        shutil.rmtree(artifact_dir)
        return [record.id for record in records]

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                create table if not exists tasks (
                    id text primary key,
                    type text not null,
                    status text not null,
                    title text not null,
                    input_json text not null,
                    output_json text,
                    error text,
                    logs text not null default '',
                    artifact_dir text not null,
                    report_path text,
                    created_at text not null,
                    started_at text,
                    finished_at text
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _row_to_record(self, row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=str(row["id"]),
            type=str(row["type"]),
            status=str(row["status"]),
            title=str(row["title"]),
            input=_json_load(row["input_json"]) or {},
            output=_json_load(row["output_json"]),
            error=row["error"],
            logs=str(row["logs"] or ""),
            artifact_dir=str(row["artifact_dir"]),
            report_path=row["report_path"],
            created_at=str(row["created_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
