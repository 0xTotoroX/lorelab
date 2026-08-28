from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from soota.models import SourceRef
from soota.secrets import redact_any
from soota.storage.atomic import atomic_write


class CacheStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, source: SourceRef, artifact: str) -> Path:
        digest = hashlib.sha256(f"{source.cache_identity}:{artifact}".encode()).hexdigest()[:16]
        folder = self.root / source.platform / source.id
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{artifact}.{digest}.json"

    def get_json(self, source: SourceRef, artifact: str) -> dict[str, Any] | None:
        path = self.path_for(source, artifact)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data

    def put_json(self, source: SourceRef, artifact: str, payload: dict[str, Any], *, redact: bool = True) -> Path:
        data = redact_any(payload) if redact else payload
        path = self.path_for(source, artifact)
        atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n")
        return path

    def has(self, source: SourceRef, artifact: str) -> bool:
        return self.path_for(source, artifact).is_file()

    def audio_path(self, source: SourceRef) -> Path:
        folder = self.root / source.platform / source.id / "audio"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "audio.m4a"
