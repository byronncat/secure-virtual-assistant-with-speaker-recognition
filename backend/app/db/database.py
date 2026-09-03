"""
Database and file storage utilities.
"""

from __future__ import annotations

import json
from pathlib import Path


def read_json_file(path: Path, default: dict | list | None = None) -> dict | list:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
