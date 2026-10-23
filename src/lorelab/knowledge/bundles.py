"""[INPUT]: 已有 Soota v2 内容包清单、登记产物及正文/字幕。
[OUTPUT]: 私有来源快照与可复用的本地分析输入；不修改或删除原包。
[POS]: 知识任务的非 Cubox 输入适配，复用 artifacts 校验。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from pathlib import Path

from soota.artifacts.bundle import load_bundle, verify_artifacts

from .workflow_sources import protected
from .workflow_state import check_file, digest, immutable, inside, read_json, require, seal


def inputs(path: Path) -> list[Path]:
    path = path.expanduser().resolve()
    values = read_json(path)
    require(
        isinstance(values, list) and values and all(isinstance(x, str) and x for x in values),
        "bundles-file 必须是非空 JSON 路径数组。",
    )
    result = []
    for value in values:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        candidate = candidate.absolute()
        require(candidate.resolve() == candidate, "来源包路径不能包含符号链接或越界片段。")
        if candidate.name == "manifest.json":
            candidate = candidate.parent
        require(candidate.is_dir(), "来源包必须是现有目录或 manifest.json。")
        if candidate not in result:
            result.append(candidate)
    return result


def identities(paths: list[Path]) -> list[str]:
    return ["bundle-" + digest(str(path).encode()) for path in paths]


def collect(job: Path, state: dict, paths: list[Path]):
    sources, mapping, by_path = [], [], {}
    for identity, folder in zip(identities(paths), paths, strict=True):
        manifest_path = inside(folder, "manifest.json")
        raw_manifest = manifest_path.read_bytes()
        require(read_json(manifest_path).get("schema_version") == 2, "知识输入只接受 Soota v2 内容包。")
        bundle = load_bundle(folder)
        require(not verify_artifacts(folder, bundle), "来源包登记产物不完整或已修改。")
        artifacts = {a.path: a for a in bundle.artifacts}
        require(
            "context.md" in artifacts
            and artifacts["context.md"].verification == "hash"
            and artifacts["context.md"].sha256 == bundle.context_fingerprint,
            "来源包缺少已验证 context。",
        )
        context = inside(folder, "context.md")
        check_file(context, bundle.context_fingerprint)
        required = []
        scope = "unknown"
        if bundle.content is not None and bundle.content.has_text:
            required.append(("body.md", "body"))
            scope = bundle.content.scope
        if bundle.transcript.status.value == "ready":
            required.append(("transcript.md", "transcript"))
            scope = "excerpt" if scope == "excerpt" else "unknown"
        require(required, "来源包没有可用正文或字幕。")
        for name, kind in required:
            require(
                name in artifacts and artifacts[name].kind == kind and artifacts[name].verification == "hash",
                "来源包缺少已验证的正文/字幕产物。",
            )
            require(inside(folder, name).read_bytes().strip(), "来源正文不能为空。")
        # context 保留正文和字幕；同时存在时不能只挑正文而漏掉视频内容。
        raw = context.read_bytes()
        require(digest(raw) == bundle.context_fingerprint, "来源 context 在读取时已改变。")
        source_path = job / "sources" / digest(raw) / "source.txt"
        immutable(source_path, raw)
        files = {str(inside(folder, a.path)): a.sha256 for a in bundle.artifacts}
        files[str(manifest_path)] = digest(raw_manifest)
        check_file(manifest_path, files[str(manifest_path)])
        snapshot = job / "supplements" / identity
        immutable(snapshot / "manifest.json", raw_manifest)
        immutable(snapshot / "context.md", context.read_bytes())
        url = bundle.source.canonical_url or bundle.source.url
        is_protected = protected({"url": url, "domain": ""}, [])
        sources.append(
            {
                "id": identity,
                "status": "ok",
                "content_status": "body_available",
                "protected": is_protected,
                "url": url,
                "title": bundle.content.title if bundle.content else bundle.source.id,
                "error": None,
                "source_sha256": digest(raw),
                "source_path": str(source_path),
                "scope": scope,
                "origin": "soota_bundle",
                "supplement": {
                    "bundle": str(folder),
                    "source": bundle.source.model_dump(mode="json"),
                    "scope": scope,
                    "files": files,
                    "snapshot": str(snapshot),
                },
            }
        )
        if not is_protected:
            if str(source_path) not in by_path:
                by_path[str(source_path)] = len(mapping)
                mapping.append({"path": str(source_path), "source_ids": []})
            mapping[by_path[str(source_path)]]["source_ids"].append(identity)
    seal(job, state, "sources.json", sources)
    seal(job, state, "source-inputs.json", {"inputs": [row["path"] for row in mapping]})
    seal(job, state, "input-map.json", mapping)
