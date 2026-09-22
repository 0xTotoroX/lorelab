from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from soota.errors import InputError
from soota.routing import recognize


@dataclass(frozen=True)
class FeatureAlias:
    id: str
    description: str
    parameter: str
    opencli: str
    opencli_parameter: str
    tikhub: str
    tikhub_parameter: str
    opencli_extra: dict[str, Any] = field(default_factory=dict)


ALIASES = [
    FeatureAlias(
        "twitter.profile",
        "X 用户资料",
        "username",
        "twitter/profile",
        "username",
        "twitter.web.fetch_user_profile",
        "screen_name",
    ),
    FeatureAlias(
        "instagram.profile",
        "Instagram 用户资料",
        "username",
        "instagram/profile",
        "username",
        "instagram.get_user_profile",
        "username",
    ),
    FeatureAlias(
        "reddit.profile",
        "Reddit 用户资料",
        "username",
        "reddit/user",
        "username",
        "reddit.app.fetch_user_profile",
        "username",
    ),
    FeatureAlias(
        "tiktok.profile",
        "TikTok 用户资料",
        "username",
        "tiktok/profile",
        "username",
        "tiktok.web.fetch_user_profile",
        "uniqueId",
    ),
    FeatureAlias(
        "weibo.profile", "微博用户资料（数字 UID）", "uid", "weibo/user", "id", "weibo.web.fetch_user_info", "uid"
    ),
    FeatureAlias(
        "zhihu.answer.detail",
        "知乎回答全文（原始格式不同）",
        "answer_id",
        "zhihu/answer-detail",
        "id",
        "zhihu.web.fetch_answer_detail",
        "answer_id",
        {"max-content": 0},
    ),
    FeatureAlias(
        "instagram.user.search",
        "Instagram 首批用户搜索（无统一分页）",
        "query",
        "instagram/search",
        "query",
        "instagram.search_users",
        "query",
    ),
    FeatureAlias(
        "twitter.post.search",
        "X 首批帖子搜索（无统一分页）",
        "query",
        "twitter/search",
        "query",
        "twitter.web.fetch_search_timeline",
        "keyword",
    ),
    FeatureAlias(
        "bilibili.video.detail",
        "Bilibili 视频详情",
        "url",
        "bilibili/video",
        "bvid",
        "bilibili.web.fetch_one_video",
        "url",
    ),
    FeatureAlias(
        "youtube.video.detail",
        "YouTube 视频详情",
        "url",
        "youtube/video",
        "url",
        "youtube.web.get_video_info",
        "video_id",
    ),
    FeatureAlias(
        "xiaohongshu.note.detail",
        "小红书笔记详情（带 xsec_token 官方链接）",
        "url",
        "xiaohongshu/note",
        "note-id",
        "xiaohongshu.web.fetch_note_detail",
        "note_id",
    ),
]


def alias_params(alias: FeatureAlias, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    allowed = {alias.parameter} | ({"sort"} if alias.id == "twitter.post.search" else set())
    value = params.get(alias.parameter)
    if params.keys() - allowed or not isinstance(value, str) or not value.strip():
        raise InputError(f"该功能需要字符串参数 {alias.parameter}；不支持未列出的参数。")
    value = value.strip()
    if alias.parameter == "username":
        value = value.removeprefix("u/") if alias.id.startswith("reddit.") else value.removeprefix("@")
        if not value or "/" in value:
            raise InputError("username 应是用户名，不是 URL。")
    if (
        alias.parameter in {"uid", "answer_id"}
        and not value.isascii()
        or alias.parameter in {"uid", "answer_id"}
        and not value.isdigit()
    ):
        raise InputError(f"{alias.parameter} 必须是数字 ID。")
    cheap = {alias.opencli_parameter: value, **alias.opencli_extra}
    paid = {alias.tikhub_parameter: value}
    if alias.id in {"bilibili.video.detail", "youtube.video.detail"}:
        source = recognize(value)
        if source.platform != alias.id.split(".")[0] or source.kind != "video":
            raise InputError("请提供该平台的标准视频 URL。")
        cheap[alias.opencli_parameter] = source.id
        paid[alias.tikhub_parameter] = source.canonical_url if source.platform == "bilibili" else source.id
    if alias.id == "twitter.post.search":
        sort = params.get("sort", "top")
        if sort not in {"top", "latest"}:
            raise InputError("sort 只支持 top/latest。")
        cheap["product"] = "top" if sort == "top" else "live"
        paid["search_type"] = "Top" if sort == "top" else "Latest"
    if alias.id == "xiaohongshu.note.detail":
        url = urlparse(value)
        parts = url.path.strip("/").split("/")
        token = parse_qs(url.query).get("xsec_token", [""])[0]
        if (
            url.scheme != "https"
            or url.hostname not in {"xiaohongshu.com", "www.xiaohongshu.com"}
            or not token
            or len(parts) < 2
            or not (
                len(parts) == 2
                and parts[0] in {"explore", "item", "search_result", "note"}
                or len(parts) == 4
                and parts[:2] == ["user", "profile"]
            )
        ):
            raise InputError("需要已展开的 https 官方笔记链接，并包含 xsec_token。")
        paid = {"note_id": parts[-1], "xsec_token": token}
    return cheap, paid
