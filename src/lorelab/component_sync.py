"""[INPUT]: 已提交的产品源码、组件锁和明确的独立 Git 仓库。
[OUTPUT]: 保留原历史的组件同步预览、提交与远端回读。
[POS]: Cubox、Soota、幕布共用的单向同步边界；复用组件导出，不 checkout 用户仓库或强推历史。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from . import components


def git(root: Path, *args: str, data: bytes | None = None, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *map(str, args)], input=data, capture_output=True, timeout=120, check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1", **(env or {})},
    )
    if result.returncode:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.decode('utf-8', errors='replace').strip()}")
    return result.stdout.decode("utf-8").strip("\n")


def repository(value: str) -> str:
    # 不在地址中携带认证，Git 使用其现有凭据机制。
    if not value or value.startswith("-") or any(ord(c) < 32 for c in value):
        raise ValueError("invalid repository location")
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname or parsed.password:
            raise ValueError("use HTTPS/SSH without embedded credentials, or a local Git repository")
        if parsed.scheme == "https" and parsed.username:
            raise ValueError("repository credentials belong in the Git credential manager")
        return value
    if re.fullmatch(r"[\w.-]+@[\w.-]+:.+", value):
        return value
    path = Path(value).expanduser().resolve(strict=True)
    return str(path)


def ref(root: Path, kind: str, value: str) -> str:
    full = f"refs/{kind}/{value}"
    if not value or value.startswith("-") or any(ord(c) < 32 for c in value):
        raise ValueError("invalid Git ref")
    git(root, "check-ref-format", full)
    return full


def remote_refs(root: Path, remote: str, *refs: str) -> dict[str, str]:
    result = {}
    for line in git(root, "ls-remote", "--refs", "--", remote, *refs).splitlines():
        oid, name = line.split("\t", 1)
        result[name] = oid
    return result


def clean_source(root: Path) -> str:
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root.resolve():
        raise ValueError("--source must be the LoreLab Git repository root")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("commit the reviewed source, Skill and component lock before sync/release")
    checked = components.verify(root)
    if not checked["ok"]:
        raise ValueError("; ".join(checked["errors"]))
    return git(root, "rev-parse", "HEAD")


def tree_entries(root: Path, revision: str) -> dict[str, tuple[str, str]]:
    entries = {}
    for line in git(root, "ls-tree", "-rz", "--full-tree", revision).split("\0"):
        if not line:
            continue
        metadata, path = line.split("\t", 1)
        mode, kind, oid = metadata.split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"unsupported Git source entry: {path}")
        components._relative_path(path, "Git source")
        entries[path] = (mode, oid)
    return entries


def _check_previous(root: Path, bare: Path, tip: str, name: str, source: str) -> dict | None:
    entries = tree_entries(bare, tip)
    if components.PROVENANCE_FILE not in entries:
        return None
    previous = json.loads(git(bare, "show", f"{tip}:{components.PROVENANCE_FILE}"))
    sync = previous.get("sync", {})
    prior_source = sync.get("source_commit", "")
    if (previous.get("component") != name or sync.get("schema_version") != 1
            or not re.fullmatch(r"[0-9a-f]{40,64}", prior_source)):
        raise ValueError("standalone provenance is not managed by LoreLab sync")
    message = git(bare, "log", "-1", "--format=%B", tip)
    if f"LoreLab-Source: {prior_source}" not in message.splitlines():
        raise ValueError("standalone tip was edited outside LoreLab; review changes before continuing")
    files = previous.get("files", {})
    if set(entries) != set(files) | {components.PROVENANCE_FILE}:
        raise ValueError("standalone source file set differs from its sync receipt")
    modes = sync.get("modes", {})
    for path, expected in files.items():
        blob = subprocess.run(["git", "-C", str(bare), "cat-file", "blob", entries[path][1]],
                              capture_output=True, check=True).stdout
        if hashlib.sha256(blob).hexdigest() != expected or modes.get(path) != entries[path][0]:
            raise ValueError(f"standalone source or Skill changed outside LoreLab: {path}")
    if components._tree_sha256(files) != previous.get("tree_sha256"):
        raise ValueError("standalone sync receipt fingerprint is invalid")
    # 拒绝较旧的 CI 任务覆盖较新的主源；需要完整 LoreLab 历史。
    git(root, "merge-base", "--is-ancestor", prior_source, source)
    return previous


def _write_tree(bare: Path, exported: Path, modes: dict[str, str]) -> str:
    names = sorted(modes)
    entries = []
    for start in range(0, len(names), 64):
        chunk = names[start:start + 64]
        oids = git(bare, "hash-object", "-w", "--no-filters", "--",
                   *(str(exported / name) for name in chunk)).splitlines()
        for name, oid in zip(chunk, oids, strict=True):
            entries.append(f"{modes[name]} {oid}\t{name}\0")
    git(bare, "read-tree", "--empty")
    git(bare, "update-index", "-z", "--index-info", data="".join(entries).encode("utf-8"))
    return git(bare, "write-tree")


@dataclass
class SyncPlan:
    bare: Path
    target: str
    branch: str
    old: str
    commit: str
    source: str
    fingerprint: str
    version: str
    fixed_tag: bool = False
    name: str = "soota"

    def report(self, *, executed: bool = False, tag: str | None = None) -> dict:
        return {"ok": True, "component": self.name, "repository": self.target,
                "branch": self.branch, "previous_commit": self.old, "commit": self.commit,
                "source_commit": self.source, "tree_sha256": self.fingerprint, "version": self.version,
                "changed": not self.fixed_tag and self.old != self.commit, "executed": executed, "tag": tag,
                "fixed_tag": self.fixed_tag, "branch_commit": self.old if self.fixed_tag else self.commit}

    def check_tag(self, tag: str) -> bool:
        tag_ref = ref(self.bare, "tags", tag)
        existing = remote_refs(self.bare, self.target, tag_ref).get(tag_ref)
        if existing and existing != self.commit:
            # 支持已有 annotated tag，比较被指向的提交，绝不移动 tag。
            git(self.bare, "fetch", "--no-tags", "--", self.target, tag_ref)
            if git(self.bare, "rev-parse", "FETCH_HEAD^{commit}") != self.commit:
                raise ValueError(f"{tag} already names a different standalone version; prepare a new version")
        return existing is not None

    def push(self, *, tag: str | None = None) -> dict:
        branch_ref = ref(self.bare, "heads", self.branch)
        tag_exists = self.check_tag(tag) if tag else False
        refs = [f"{self.commit}:{branch_ref}"] if not self.fixed_tag and self.old != self.commit else []
        if tag and not tag_exists:
            refs.append(f"{self.commit}:{ref(self.bare, 'tags', tag)}")
        if refs:
            # 快进拒绝并发分歧，--atomic 保证同仓库分支与 tag 一起成功。
            git(self.bare, "push", "--atomic", "--", self.target, *refs)
        actual = remote_refs(self.bare, self.target, branch_ref)
        if actual.get(branch_ref) != (self.old if self.fixed_tag else self.commit):
            raise RuntimeError("standalone branch changed during sync; inspect the remote before retrying")
        if tag and not self.check_tag(tag):
            raise RuntimeError("standalone tag is missing after publication")
        return self.report(executed=True, tag=tag)


@contextlib.contextmanager
def plan(root: Path, *, name: str = "soota", target: str | None = None, branch: str | None = None, tag: str | None = None):
    root = root.resolve()
    source = clean_source(root)
    lock = components._load(root)
    if name not in lock["components"]:
        raise ValueError(f"unknown component: {name}")
    entry = lock["components"][name]
    target = repository(target or entry["repository"])
    branch = branch or entry.get("sync", {}).get("branch", "main")
    with tempfile.TemporaryDirectory(prefix=f"lorelab-{name}-sync-") as temporary:
        base = Path(temporary)
        bare = base / "mirror.git"
        bare.mkdir()
        git(bare, "init", "--bare", "--quiet")
        branch_ref = ref(bare, "heads", branch)
        git(bare, "fetch", "--no-tags", "--", target, branch_ref)
        tip = git(bare, "rev-parse", "FETCH_HEAD^{commit}")
        tag_tip = None
        if tag and remote_refs(bare, target, ref(bare, "tags", tag)):
            git(bare, "fetch", "--no-tags", "--", target, ref(bare, "tags", tag))
            tag_tip = git(bare, "rev-parse", "FETCH_HEAD^{commit}")
        previous = _check_previous(root, bare, tag_tip or tip, name, source)
        if tag_tip and previous is None:
            raise ValueError(f"{tag} already names a different standalone version without a managed receipt")
        parent = tip
        if previous is None:
            baseline = entry.get("sync", {}).get("initial_revision", entry["revision"])
            if not re.fullmatch(r"[0-9a-f]{40,64}", baseline):
                raise ValueError("initial_revision must identify the reviewed full original commit")
            if tip != baseline:
                # 首次迁移保留导入前尚未推送的历史；主源必须已显式接入这段历史。
                git(root, "merge-base", "--is-ancestor", baseline, source)
                git(bare, "fetch", "--no-tags", "--", str(root), baseline)
                git(bare, "merge-base", "--is-ancestor", tip, baseline)
                parent = baseline
        exported = base / "source"
        components.export_component(root, name, exported)
        provenance_path = exported / components.PROVENANCE_FILE
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        # 每一份有效源文件必须来自此提交；不能把 ignored/untracked 文件夹带进发行仓库。
        committed = tree_entries(root, f"{source}:{entry['path']}")
        modes = {}
        for path in provenance["files"]:
            if path not in committed:
                raise ValueError(f"component export contains an uncommitted file: {path}")
            mode, oid = committed[path]
            if git(root, "hash-object", "--no-filters", str(exported / path)) != oid:
                raise ValueError(f"component working bytes differ from the committed source: {path}")
            modes[path] = mode
        same = (previous and previous["tree_sha256"] == provenance["tree_sha256"]
                and previous["sync"]["modes"] == modes and previous["version"] == entry["version"])
        if same:
            commit = tag_tip or tip
        else:
            if tag_tip:
                raise ValueError(f"{tag} already names a different standalone version; prepare a new version")
            provenance["sync"] = {"schema_version": 1, "source_commit": source,
                                  "source_path": entry["path"], "modes": modes}
            provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tree = _write_tree(bare, exported, {**modes, components.PROVENANCE_FILE: "100644"})
            date = git(root, "show", "-s", "--format=%cI", source)
            identity = {"GIT_AUTHOR_NAME": "LoreLab Sync", "GIT_AUTHOR_EMAIL": "sync@lorelab.invalid",
                        "GIT_COMMITTER_NAME": "LoreLab Sync", "GIT_COMMITTER_EMAIL": "sync@lorelab.invalid",
                        "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
            label = {"soota": "Soota", "cubox": "Cubox CLI", "mubu": "Mubu CLI"}.get(name, name)
            message = (f"chore(sync): {label} from LoreLab {source[:12]}\n\n"
                       f"LoreLab-Source: {source}\nLoreLab-Tree: {provenance['tree_sha256']}\n")
            commit = git(bare, "commit-tree", tree, "-p", parent, data=message.encode(), env=identity)
        if clean_source(root) != source:
            raise ValueError("source changed while preparing synchronization")
        yield SyncPlan(bare, target, branch, tip, commit, source, provenance["tree_sha256"], entry["version"],
                       fixed_tag=tag_tip is not None, name=name)


def synchronize(root: Path, *, name: str = "soota", target: str | None = None, branch: str | None = None,
                execute: bool = False) -> dict:
    with plan(root, name=name, target=target, branch=branch) as prepared:
        return prepared.push() if execute else prepared.report()
