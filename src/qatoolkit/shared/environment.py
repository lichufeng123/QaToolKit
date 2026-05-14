from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .paths import project_root


def load_dotenv_file(path: Path | None = None) -> None:
    target = path or (project_root(Path(__file__)) / ".env")
    if not target.exists():
        return

    for key, value in _parse_env_file(target.read_text(encoding="utf-8").splitlines()):
        os.environ.setdefault(key, value)


def _parse_env_file(lines: Iterable[str]) -> Iterable[tuple[str, str]]:
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        yield key, _strip_quotes(value.strip())


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
