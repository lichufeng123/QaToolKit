from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Prompt:
    name: str
    description: str = ""
    arguments: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
