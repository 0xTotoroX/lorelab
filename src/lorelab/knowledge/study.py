"""[INPUT]: 显式选择的既有文章、共用标题解析、Agent 审阅和幕布发布器。
[OUTPUT]: prepare/submit/publish/verify/status；私有文章快照及不可变学习大纲。
[POS]: 按需学习流程；只读知识库，不采集来源，不调用 Cubox/Soota。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md。
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .markdown import title as _title
from .workflow_publish import publish_approved, reconcile, writer
from .workflow_review import validate_outline
from .workflow_state import (
    WorkflowError,
    check_file,
    default_root,
    destination,
    digest,
    open_job,
    path_key,
    read_json,
    require,
    save,
    seal,
    unseal,
    write_json,
)

__all__ = ["WorkflowError", "prepare", "publish", "status", "submit", "verify"]


def run_json(tool: str, args: list[str], receipt: Path | None = None, acceptable_codes: tuple = (0,)):
    # 唯一进程边界；prepare/submit/status 不会到达这里。
    from .runtime import run_json as invoke

    return invoke(tool, args, receipt=receipt, acceptable_codes=acceptable_codes)


def _mubu_options(spec: dict):
    doc, parent, auth = spec.get("mubu_doc"), spec.get("mubu_parent"), spec.get("mubu_auth")
    require(isinstance(doc, str) and doc.strip() and not doc.startswith("-"), "mubu_doc 无效。")
    require(
        parent is None or isinstance(parent, str) and parent.strip() and not parent.startswith("-"),
        "mubu_parent 无效。",
    )
    require(isinstance(auth, str) and auth in {"desktop", "password"}, "mubu_auth 无效。")


def _spec(job: Path, state: dict) -> dict:
    spec = unseal(job, state, "spec.json")
    require(
        state.get("kind") == "study" and isinstance(spec, dict) and spec.get("kind") == "study",
        "job kind 必须是 study。",
    )
    require(
        spec.get("with_outline") is True
        and spec.get("subdir") == ""
        and isinstance(spec.get("vault"), str)
        and spec.get("destination") == spec["vault"],
        "study 目的地或大纲契约已改变。",
    )
    vault = destination(spec)
    require(vault.is_absolute() and vault.is_dir() and not vault.is_symlink(), "vault 必须是现有真实目录。")
    require(not job.is_relative_to(vault) and not vault.is_relative_to(job), "状态目录必须与知识库分离。")
    _mubu_options(spec)
    return spec


def _article_path(spec: dict, relative: str) -> Path:
    require(isinstance(relative, str) and relative, "文章相对路径不能为空。")
    path = destination(spec, relative)
    require(path.name.casefold() not in {"agents.override.md", "gemini.md", "skill.md"}, "拒绝选择指令文件。")
    return path



def _unique(articles: list[dict]):
    paths, titles = set(), set()
    for article in articles:
        key, title = path_key(article["relative_path"]), path_key(article["title"].strip())
        require(key not in paths and title not in titles, "文章路径或主题标题重复（含大小写及 Unicode 等价形式）。")
        paths.add(key)
        titles.add(title)


def _articles(job: Path, state: dict) -> list[dict]:
    spec = _spec(job, state)
    articles = unseal(job, state, "articles.json")
    require(isinstance(articles, list) and articles, "文章快照不能为空。")
    for article in articles:
        require(
            isinstance(article, dict) and set(article) == {"relative_path", "title", "markdown", "body_sha256"},
            "文章快照字段不符。",
        )
        path = _article_path(spec, article["relative_path"])
        body = article["markdown"]
        require(isinstance(body, str) and body.strip(), "文章快照正文不能为空。")
        require(digest(body.encode("utf-8")) == article["body_sha256"], "文章快照 body_sha256 不符。")
        require(article["title"] == _title(body, path), "文章快照标题与原文不符。")
        check_file(path, article["body_sha256"])
    _unique(articles)
    require(
        state.get("notes") == {a["relative_path"]: a["body_sha256"] for a in articles},
        "既有文章指纹登记与快照不符。",
    )
    return articles


def _template(articles: list[dict]) -> dict:
    return {
        "articles": [
            {
                "relative_path": article["relative_path"],
                "body_sha256": article["body_sha256"],
                "review_notes": "",
                "outline": {"text": article["title"], "children": []},
            }
            for article in articles
        ]
    }


def _approved(articles: list[dict], review: dict) -> dict:
    require(isinstance(review, dict) and set(review) == {"articles"}, "审阅仅接受 articles。")
    entries = review["articles"]
    require(isinstance(entries, list) and len(entries) == len(articles), "articles 必须逐一覆盖全部选定文章。")
    selected = {a["relative_path"]: a for a in articles}
    reviews = {}
    for entry in entries:
        require(
            isinstance(entry, dict) and set(entry) == {"relative_path", "body_sha256", "review_notes", "outline"},
            "文章审阅字段不符；不能替换正文、标题或目的地。",
        )
        relative = entry["relative_path"]
        require(
            isinstance(relative, str) and relative in selected and relative not in reviews,
            "文章身份不匹配、重复或遗漏。",
        )
        require(entry["body_sha256"] == selected[relative]["body_sha256"], "文章 body_sha256 不匹配。")
        notes = entry["review_notes"]
        require(isinstance(notes, str) and notes.strip(), "须填写具体 review_notes。")
        # 只能拒绝明显占位；实际阅读、语义覆盖和大纲质量仍由 Agent 判断。
        placeholder = path_key(notes.strip()).strip(" .!?。！？…")
        require(
            any(c.isalnum() for c in notes)
            and placeholder
            not in {
                "todo",
                "tbd",
                "pending",
                "reviewed",
                "done",
                "ok",
                "n/a",
                "待填写",
                "待审阅",
                "待补充",
                "已阅读",
                "已审阅",
                "已完成",
                "完成",
                "无",
            },
            "review_notes 须记录具体审阅依据，不能只填占位或完成状态。",
        )
        reviews[relative] = entry
    notes = [{**article, "outline": reviews[article["relative_path"]]["outline"]} for article in articles]
    validate_outline(notes)
    return {"articles": [reviews[a["relative_path"]] for a in articles], "notes": notes}


def check_study(job: Path, state: dict) -> dict:
    """共享发布器的 checker：只核对学习快照、批准稿与仍然存在的文章。"""
    articles = _articles(job, state)
    approved = unseal(job, state, "approved.json")
    require(isinstance(approved, dict) and set(approved) == {"articles", "notes"}, "study approved 字段不符。")
    expected = _approved(articles, {"articles": approved["articles"]})
    require(approved == expected, "approved 与文章快照或审阅不符。")
    require(
        unseal(job, state, "outline.json") == {"nodes": [n["outline"] for n in approved["notes"]]},
        "outline 与 approved 不符。",
    )
    return approved


def _report(job: Path, state: dict) -> dict:
    return {
        **state,
        "ok": state["status"] != "publish_uncertain",
        "articles": [
            {k: a[k] for k in ("relative_path", "title", "body_sha256")} for a in unseal(job, state, "articles.json")
        ],
        "article_snapshot": str(job / "articles.json"),
        "review_template": str(job / "review-template.json"),
        "semantic_review": "Agent 须实读文章并填写具体审阅依据与学习大纲；程序只校验身份、指纹和结构。",
    }


def prepare(
    article_files: list[Path],
    vault: Path,
    mubu_doc: str,
    mubu_parent: str | None = None,
    state_root: Path | None = None,
    mubu_auth: str = "desktop",
) -> dict:
    vault = Path(vault).expanduser().absolute()
    require(vault.is_dir() and vault.resolve() == vault and not vault.is_symlink(), "vault 必须是现有真实目录。")
    spec = {
        "kind": "study",
        "with_outline": True,
        "vault": str(vault),
        "subdir": "",
        "destination": str(vault),
        "mubu_doc": mubu_doc,
        "mubu_parent": mubu_parent,
        "mubu_auth": mubu_auth,
    }
    _mubu_options(spec)
    require(isinstance(article_files, list) and article_files, "必须显式选择至少一份 Markdown 文章。")
    articles = []
    for value in article_files:
        path = Path(value).expanduser()
        if path.is_absolute():
            require(path.is_relative_to(vault), "文章必须位于显式 vault 内。")
            path = path.relative_to(vault)
        relative = path.as_posix()
        selected = _article_path(spec, relative)
        require(selected.is_file(), f"文章文件不存在：{selected}")
        try:
            raw = selected.read_bytes()
            markdown = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise WorkflowError(f"无法读取 UTF-8 文章：{selected}") from exc
        require(bool(markdown.strip()), f"文章正文不能为空：{selected}")
        articles.append(
            {
                "relative_path": relative,
                "title": _title(markdown, selected),
                "markdown": markdown,
                "body_sha256": digest(raw),
            }
        )
    _unique(articles)
    root = Path(state_root or default_root()).expanduser().resolve()
    require(not root.is_relative_to(vault) and not vault.is_relative_to(root), "状态目录必须与知识库分离。")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    job = root / uuid4().hex
    job.mkdir(mode=0o700)
    state = {
        "schema_version": 1,
        "kind": "study",
        "job": str(job),
        "status": "waiting_review",
        "sealed": {},
        "notes": {a["relative_path"]: a["body_sha256"] for a in articles},
    }
    seal(job, state, "spec.json", spec)
    seal(job, state, "articles.json", articles)
    write_json(job / "review-template.json", _template(articles))
    save(job, state)
    with open_job(str(job)) as (folder, state):
        _articles(folder, state)
        return _report(folder, state)


def submit(job: str, review_file: Path) -> dict:
    with open_job(job) as (folder, state):
        approved = _approved(_articles(folder, state), read_json(Path(review_file)))
        if "approved.json" in state.get("sealed", {}):
            require(approved == check_study(folder, state), "approved 已冻结；不能替换审阅或大纲。")
        else:
            seal(folder, state, "approved.json", approved)
            seal(folder, state, "outline.json", {"nodes": [n["outline"] for n in approved["notes"]]})
            state["status"] = "approved"
            save(folder, state)
        return _report(folder, state)


def publish(job: str) -> dict:
    with open_job(job) as (folder, state):
        check_study(folder, state)
        publish_approved(run_json, folder, state, checker=check_study, write_articles=False)
        # 对账可能因缺少执行证据提前返回；仍须在云端读取后复核本地输入。
        check_study(folder, state)
        return _report(folder, state)


def verify(job: str) -> dict:
    with open_job(job) as (folder, state):
        approved = check_study(folder, state)
        with writer(_spec(folder, state)):
            verified = reconcile(run_json, folder, state, approved, checker=check_study)
            check_study(folder, state)
            require(
                verified,
                "幕布尚无可确认的完整写入；只能对账，不能重导入。",
            )
        return _report(folder, state)


def status(job: str) -> dict:
    with open_job(job) as (folder, state):
        if "approved.json" in state.get("sealed", {}):
            check_study(folder, state)
        else:
            _articles(folder, state)
        return _report(folder, state)
