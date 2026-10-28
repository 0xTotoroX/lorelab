"""[INPUT]: 知识目录内的分类体系、Markdown 和 Agent 明确选定的类别。
[OUTPUT]: 分类树、只读书目、冻结分类与归档前的重复/路径校验。
[POS]: knowledge 的确定性图书馆支持；不调用模型、不改写旧文章。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .markdown import title
from .workflow_state import destination, digest, encoded, inside, path_key, read_json, require, sync_dir

TAXONOMY_FILE = "分类体系.json"


def validate(value: dict) -> dict:
    require(isinstance(value, dict) and value.get("schema_version") == 1, "分类体系 schema_version 必须为 1。")
    require(isinstance(value.get("id"), str) and value["id"].strip(), "分类体系缺少 id。")
    require(type(value.get("version")) is int and value["version"] > 0, "分类体系 version 必须为正整数。")
    require(isinstance(value.get("title"), str) and value["title"].strip(), "分类体系缺少 title。")
    categories = value.get("categories")
    require(isinstance(categories, list) and categories, "分类体系 categories 不能为空。")
    seen = set()
    for entry in categories:
        require(isinstance(entry, dict), "类别必须为对象。")
        code, name = entry.get("code"), entry.get("name")
        require(isinstance(code, str) and re.fullmatch(r"\d{2}(?:\.\d{2}){0,2}", code, re.ASCII),
                "类别编码须为 00、00.01 或 00.01.01 格式的字符串。")
        require(code not in seen, f"类别编码重复：{code}")
        seen.add(code)
        require(isinstance(name, str) and name == name.strip() and bool(name)
                and not any(c in name for c in '/\\:*?"<>|') and not name.endswith(".")
                and not any(ord(c) < 32 for c in name), "类别名称必须能用作跨平台目录名。")
        require(isinstance(entry.get("scope", ""), str), "类别 scope 必须为字符串。")
    require(all("." not in c or c.rsplit(".", 1)[0] in seen for c in seen), "分类体系缺少父类别。")
    excluded = value.get("exclude_files", [])
    require(isinstance(excluded, list) and all(isinstance(x, str) and x.endswith(".md")
                and "/" not in x and "\\" not in x for x in excluded), "exclude_files 必须为 Markdown 文件名数组。")
    return value


def load(root: Path) -> dict | None:
    if not root.exists():
        return None
    path = inside(root, TAXONOMY_FILE)
    return validate(read_json(path)) if path.exists() else None


def paths(taxonomy: dict) -> dict[str, str]:
    entries = {x["code"]: x for x in taxonomy["categories"]}
    result = {}
    for code in sorted(entries):
        tokens = code.split(".")
        chain = [".".join(tokens[:i]) for i in range(1, len(tokens) + 1)]
        result[code] = "/".join(f"{key} {entries[key]['name']}" for key in chain)
    return result


def tree(taxonomy: dict) -> str:
    entries = {x["code"]: x for x in taxonomy["categories"]}
    children: dict[str, list[str]] = {}
    for code in sorted(entries):
        parent = code.rsplit(".", 1)[0] if "." in code else ""
        children.setdefault(parent, []).append(code)
    lines = [taxonomy["title"] + "/"]

    def visit(parent, prefix):
        for i, code in enumerate(children.get(parent, [])):
            last = i == len(children[parent]) - 1
            lines.append(prefix + ("└── " if last else "├── ") + f"{code} {entries[code]['name']}/")
            visit(code, prefix + ("    " if last else "│   "))

    visit("", "")
    return "\n".join(lines)



def catalog(root: Path, taxonomy: dict | None = None, query: str = "", category: str | None = None) -> dict:
    taxonomy = taxonomy if taxonomy is not None else load(root)
    directories = paths(taxonomy) if taxonomy else {}
    require(category is None or category in directories, "未知类别编码。")
    ignored = {"agents.md", "claude.md", *(path_key(x) for x in (taxonomy or {}).get("exclude_files", []))}
    records, skipped = [], []
    if root.exists():
        for folder, dirs, files in os.walk(root, followlinks=False):
            base = Path(folder)
            for name in list(dirs):
                child = base / name
                if name.startswith(".") or child.is_symlink():
                    dirs.remove(name)
                    if child.is_symlink():
                        skipped.append(child.relative_to(root).as_posix())
            for name in sorted(files):
                if not name.lower().endswith(".md") or name.startswith(".") or path_key(name) in ignored:
                    continue
                path = base / name
                if path.is_symlink():
                    skipped.append(path.relative_to(root).as_posix())
                    continue
                relative = path.relative_to(root).as_posix()
                raw = inside(root, relative).read_bytes()
                body = raw.decode("utf-8-sig")
                match = next((c for c, d in sorted(directories.items(), key=lambda item: -len(item[1]))
                              if relative.startswith(d + "/")), None)
                if category and (match is None or not (match == category or match.startswith(category + "."))):
                    continue
                if query and path_key(query) not in path_key(name + "\n" + body):
                    continue
                records.append({"relative_path": relative, "title": title(body, path),
                                "category": match, "body_sha256": digest(raw)})
    records.sort(key=lambda item: path_key(item["relative_path"]))
    grouped: dict[str, list[str]] = {}
    for record in records:
        grouped.setdefault(path_key(record["title"].strip()), []).append(record["relative_path"])
    return {"articles": records, "count": len(records),
            "uncategorized": [r["relative_path"] for r in records if r["category"] is None],
            "duplicate_titles": [group for group in grouped.values() if len(group) > 1],
            "skipped_symlinks": sorted(skipped)}


def init(root: Path, source: Path | None = None) -> dict:
    taxonomy = validate(read_json(source or Path(__file__).with_name("world_taxonomy.json")))
    root.mkdir(parents=True, exist_ok=True)
    target = inside(root, TAXONOMY_FILE)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        require(load(root) == taxonomy, "已有分类体系不同；请先审阅，init 不覆盖人工修改。")
        created = False
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded(taxonomy))
            stream.flush()
            os.fsync(stream.fileno())
        sync_dir(root)
        created = True
    return {"ok": True, "created": created, "taxonomy": str(target), "tree": tree(taxonomy)}


def check_notes(spec: dict, notes: list[dict]):
    taxonomy = spec.get("library")
    if taxonomy is None:
        return  # 旧批次保持原有路径、冻结内容和清理条件。
    root = destination(spec)
    require(load(root) == taxonomy, "分类体系已改变；旧任务保留，请按新分类重新准备任务。")
    directories = paths(taxonomy)
    existing = catalog(root, taxonomy)["articles"]
    hashes = [note["body_sha256"] for note in notes]
    require(len(hashes) == len(set(hashes)), "同批文章正文重复；请合并为一份正文。")
    for note in notes:
        code = note.get("category")
        require(isinstance(code, str) and code in directories, "笔记 category 必须是分类体系中的编码。")
        relative = note["relative_path"]
        excluded = {"agents.md", "claude.md", *(path_key(x) for x in taxonomy.get("exclude_files", []))}
        require(path_key(Path(relative).name) not in excluded, "文章不能使用规则或导航文件名。")
        require(Path(relative).parent.as_posix() == directories[code], "笔记路径与 category 不符。")
        require(Path(relative).stem == note["title"], "图书馆文章文件名须与 title 一致。")
        require(title(note["markdown"], Path(relative)) == note["title"], "正文标题与 title 不一致。")
        related = note.get("related_categories", [])
        require(isinstance(related, list) and all(isinstance(c, str) and c in directories and c != code for c in related)
                and len(set(related)) == len(related), "related_categories 必须是其他类别的去重编码数组。")
        for old in existing:
            if old["relative_path"] == relative:
                continue  # 原有 hash/O_EXCL 保护在 submit/publish 中继续生效。
            require(path_key(old["title"].strip()) != path_key(note["title"].strip())
                    and old["body_sha256"] != note["body_sha256"],
                    f"已存在同标题或相同内容：{old['relative_path']}；请审阅复用或合并，不另建副本。")
