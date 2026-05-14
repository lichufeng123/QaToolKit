from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Resource:
    uri: str
    name: str = ""
    description: str = ""
    mimeType: str = "text/plain"
    text: str = ""
