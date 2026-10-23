from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from soota.models import ContentBundleManifest, SourceRef, TranscriptManifest, TranscriptStatus


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or any(part in {"..", "."} for part in value.split("/")):
        raise ValueError("产物路径必须是内容包内的相对路径。")
    if ":" in value or not path.parts or any(not part for part in value.split("/")) or any(ord(c) < 32 for c in value):
        raise ValueError("产物路径无效。")
    return value


class ContentBlock(BaseModel):
    block_id: str = ""
    kind: Literal["paragraph", "heading", "list", "image", "markdown"] = "paragraph"
    text: str = ""
    level: int = Field(default=2, ge=1, le=6)
    target: str | None = None

    @field_validator("block_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if value and (not value.isascii() or any(not (c.isalnum() or c in "-_") for c in value)):
            raise ValueError("正文块 ID 只允许 ASCII 字母、数字、横线和下划线。")
        return value

    @property
    def markdown(self) -> str:
        if self.kind == "heading":
            return f"{'#' * self.level} {self.text}"
        if self.kind == "image":
            return f"![{self.text}]({self.target})" if self.target else self.text
        return self.text


class ContentDocument(BaseModel):
    title: str | None = None
    source: SourceRef
    blocks: list[ContentBlock] = Field(default_factory=list)
    scope: Literal["full", "excerpt", "unknown"] = "unknown"
    body_markdown: str | None = None

    @model_validator(mode="after")
    def identify_blocks(self) -> ContentDocument:
        used: set[str] = set()
        for block in self.blocks:
            if not block.block_id:
                signature = f"{block.kind}\0{block.text}\0{block.target or ''}"
                stem = "para-" + hashlib.sha256(signature.encode()).hexdigest()[:12]
                block.block_id = stem
                suffix = 2
                while block.block_id in used:
                    block.block_id = f"{stem}-{suffix}"
                    suffix += 1
            if block.block_id in used:
                raise ValueError("正文块 ID 重复。")
            used.add(block.block_id)
        return self

    @property
    def body_md(self) -> str:
        if self.body_markdown is not None:
            return self.body_markdown
        return "\n\n".join(block.markdown for block in self.blocks)

    @property
    def has_text(self) -> bool:
        return any(block.text.strip() or block.target for block in self.blocks)


class Artifact(BaseModel):
    path: str
    kind: str
    format: str
    bytes: int = Field(ge=0)
    sha256: str
    provider: str | None = None
    verification: Literal["hash", "media", "unverified"] = "hash"
    completeness: Literal["full", "partial", "unknown"] = "unknown"
    attributes: dict[str, Any] = Field(default_factory=dict)

    _relative_path = field_validator("path")(relative_path)

    @field_validator("sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("无效的 SHA-256。")
        return value


class BundleV2(ContentBundleManifest):
    schema_version: Literal[2] = 2
    transcript: TranscriptManifest = Field(
        default_factory=lambda: TranscriptManifest(status=TranscriptStatus.NOT_REQUESTED)
    )
    content: ContentDocument | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    context_fingerprint: str | None = None

    @model_validator(mode="after")
    def unique_artifacts(self) -> BundleV2:
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("产物路径重复。")
        if "manifest.json" in paths or ".soota-export.json" in paths:
            raise ValueError("产物不能使用内容包保留路径。")
        for path in self.files.values():
            relative_path(path)
        if self.content and self.content.source.cache_identity != self.source.cache_identity:
            raise ValueError("正文来源与内容包来源不一致。")
        return self
