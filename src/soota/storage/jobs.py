from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from soota.storage.atomic import atomic_write


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        record = {
            "id": job_id,
            "created_at": datetime.now(UTC).isoformat(),
            "status": payload.get("status", "completed"),
            **payload,
        }
        path = self.root / f"{job_id}.json"
        atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n")
        return record

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        jobs: list[dict[str, Any]] = []
        for path in files[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                jobs.append(data)
        return jobs
