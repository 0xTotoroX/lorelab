from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from soota.content.native_types import NativeEntry
from soota.errors import ContractError, InputError

# These are result contracts, not an exhaustive catalogue of upstream commands.
CONTENT_BINDINGS = {
    "web/read": "saved-markdown",
    "weixin/download": "saved-markdown",
    "zhihu/download": "saved-markdown",
    "twitter/article": "inline-markdown",
    "xiaohongshu/note": "field-value-text",
}
MEDIA_BINDINGS = {"xiaohongshu/download", "twitter/download", "bilibili/download"}
URL_ROW_BINDINGS = {"youtube/search", "bilibili/search", "bilibili/user-videos", "twitter/tweets"}


def validate_target_result(operation: str, params: dict[str, Any], data: Any) -> None:
    """A bound thread read must include its focal post, including on resume."""
    if operation.removeprefix("opencli.").replace(".", "/") != "twitter/thread":
        return
    value = params.get("tweet-id")
    target = value.strip() if isinstance(value, str) else ""
    if not re.fullmatch(r"[0-9]+", target):
        parsed = urlsplit(http_url(target))
        match = re.fullmatch(r"/[^/]+/status/([0-9]+)/?", parsed.path)
        if parsed.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} or not match:
            raise InputError("twitter/thread 需要数字 tweet-id 或完整帖子链接。")
        target = match[1]
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ContractError("twitter/thread 结果需要对象数组。")
    if not any(row.get("id") == target for row in data):
        raise ContractError(
            "twitter/thread 未返回请求的目标帖，不能把父帖或空数组当作目标帖获取成功。",
            hint="检查帖子可见性；提高 limit（例如 50），检查 top-by-engagement 是否排除了目标，再创建新任务。",
            details={
                "category": "contract",
                "reason": "target_not_returned",
                "retryable": False,
                "returned_count": len(data),
            },
        )


def http_url(value: Any) -> str:
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        raise InputError("来源必须是 HTTP(S) URL。")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        _ = parsed.port
    except ValueError as exc:
        raise InputError("来源必须是不含账号凭据的 HTTP(S) URL。") from exc
    return value


def content_candidates(url: str) -> list[tuple[str, dict[str, Any]]]:
    parsed = urlsplit(http_url(url))
    host = (parsed.hostname or "").lower()
    candidates: list[tuple[str, dict[str, Any]]] = []
    if host == "mp.weixin.qq.com":
        candidates.append(("weixin/download", {"url": url}))
    elif host in {"zhihu.com", "www.zhihu.com", "zhuanlan.zhihu.com"}:
        candidates.append(("zhihu/download", {"url": url}))
    elif host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} and "/status/" in parsed.path:
        candidates.append(("twitter/article", {"tweet-id": url}))
    elif host in {"xiaohongshu.com", "www.xiaohongshu.com"}:
        candidates.append(("xiaohongshu/note", {"note-id": url}))
    candidates.append(("web/read", {"url": url}))
    return candidates


def media_binding(url: str) -> tuple[str, dict[str, Any]]:
    parsed = urlsplit(http_url(url))
    host = (parsed.hostname or "").lower()
    if host in {"xiaohongshu.com", "www.xiaohongshu.com", "xhslink.com", "www.xhslink.com"}:
        return "xiaohongshu/download", {"note-id": url}
    if host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} and "/status/" in parsed.path:
        return "twitter/download", {"tweet-url": url}
    if host in {"bilibili.com", "www.bilibili.com"}:
        match = re.fullmatch(r"/video/(BV[A-Za-z0-9]+)(?:/)?", parsed.path)
        if match:
            params: dict[str, Any] = {"bvid": match[1]}
            pages = parse_qs(parsed.query).get("p")
            if pages:
                if len(pages) != 1 or not pages[0].isdigit() or int(pages[0]) < 1:
                    raise InputError("B 站分 P 参数必须是正整数。")
                params["page"] = pages[0]
            return "bilibili/download", params
    raise InputError("该 URL 尚无已核实的 OpenCLI 媒体下载绑定；请使用共享媒体下载器。")


def normalize_url_rows(data: Any) -> list[NativeEntry] | None:
    """Explicitly bound URL-row outputs only; never recursively mine native data."""
    if not isinstance(data, list):
        return None
    entries: list[NativeEntry] = []
    for row in data:
        if not isinstance(row, dict):
            return None
        try:
            url = http_url(row.get("url"))
        except InputError:
            return None
        title = row.get("title", row.get("text", ""))
        if not isinstance(title, str):
            return None
        ident = row.get("id")
        entries.append(NativeEntry(url=url, title=title, raw=row, id=ident if isinstance(ident, str) else None))
    return entries


def normalize_rows(selector: str, data: Any) -> list[NativeEntry] | None:
    operation = selector.removeprefix("opencli.").replace(".", "/")
    return normalize_url_rows(data) if operation in URL_ROW_BINDINGS else None
