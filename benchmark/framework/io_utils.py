from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class FrameworkError(RuntimeError):
    """User-visible framework failure."""


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise FrameworkError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FrameworkError(
            f"invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def _serialized_json(value: Any) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")

    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, _serialized_json(value))


def write_immutable_json(path: Path, value: Any) -> None:
    """Create an immutable JSON artifact, or accept an identical existing one."""
    expected = _serialized_json(value)

    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current != expected:
            raise FrameworkError(
                f"immutable artifact already exists with different content: {path}"
            )
        return

    atomic_write_text(path, expected)


def append_log(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line.rstrip("\n") + "\n")
        handle.flush()
