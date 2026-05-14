from __future__ import annotations

from pathlib import Path


def project_root(start: Path | None = None) -> Path:
    """Find the repository root from a source file location."""
    current = (start or Path(__file__)).resolve()
    for candidate in [current.parent, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current.parents[3]
