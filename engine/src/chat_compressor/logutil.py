"""Stage logger: [PASS]/[FAIL] lines into timestamped .log.txt files."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


class StageLogger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def line(self, text: str) -> str:
        record = text.rstrip() + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record)
        print(record, end="")
        return text.rstrip()

    def stage(
        self,
        ok: bool,
        stage: int | str,
        **fields: Any,
    ) -> str:
        tag = "PASS" if ok else "FAIL"
        parts = [f"[{tag}] stage={stage}"]
        for key, value in fields.items():
            if isinstance(value, float):
                parts.append(f"{key}={value:.6g}")
            else:
                parts.append(f"{key}={value}")
        return self.line(" ".join(parts))
