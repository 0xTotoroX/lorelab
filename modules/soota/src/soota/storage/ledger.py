from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soota.models import RequestRecord
from soota.secrets import redact_any


class CostLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, source_id: str, records: list[RequestRecord], extra: dict[str, Any] | None = None) -> None:
        row = {
            "ts": datetime.now(UTC).isoformat(),
            "source_id": source_id,
            "requests": [r.model_dump() for r in records],
            **(extra or {}),
        }
        line = json.dumps(redact_any(row), ensure_ascii=False, default=str) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
