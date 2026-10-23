from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from soota.errors import InputError, SourceError
from soota.secrets import CREDENTIAL_FIELDS

REGISTRY_PATH = Path(__file__).with_name("endpoint_registry.json")
SPEC_URL = "https://api.tikhub.io/openapi.json"

PLATFORM_NAMES = {
    "bilibili": "Bilibili",
    "douyin": "抖音",
    "instagram": "Instagram",
    "kuaishou": "快手",
    "lemon8": "Lemon8",
    "linkedin": "LinkedIn",
    "pipixia": "皮皮虾",
    "reddit": "Reddit",
    "telegram": "Telegram",
    "threads": "Threads",
    "tiktok": "TikTok",
    "toutiao": "今日头条",
    "twitter": "X / Twitter",
    "wechat_channels": "微信视频号",
    "wechat_mp": "微信公众号",
    "wechat_search": "微信搜一搜",
    "weibo": "微博",
    "xiaohongshu": "小红书",
    "xigua": "西瓜视频",
    "youtube": "YouTube",
    "zhihu": "知乎",
}

TASK_NAMES = {
    "detail": "内容详情",
    "profile": "用户/频道资料",
    "catalog": "作品/内容列表",
    "search": "搜索",
    "comments": "评论/回复",
    "media": "字幕/媒体地址",
    "trends": "热榜/趋势",
    "live": "直播信息",
    "analytics": "数据分析",
    "commerce": "商品/广告",
    "utility": "ID/链接等辅助查询",
}


class ApiParameter(BaseModel):
    name: str
    required: bool = False
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    description: str = ""


class ApiEndpoint(BaseModel):
    key: str
    group: str
    method: str
    path: str
    platform: str
    resource: str
    version: tuple[int, int]
    summary: str
    docs_url: str = SPEC_URL
    tasks: list[str]
    callable: bool
    deprecated: bool = False
    session_required: bool = False
    parameters: list[ApiParameter] = Field(default_factory=list)
    body_schema: dict[str, Any] | None = None
    body_required: bool = False
    body_sensitive: bool = False

    @property
    def query_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {parameter.name: parameter.schema_ for parameter in self.parameters},
            "required": [parameter.name for parameter in self.parameters if parameter.required],
            "additionalProperties": False,
        }
        names = set(schema["properties"])
        if self.platform == "youtube" and {"video_id", "video_url"} <= names:
            schema["anyOf"] = [{"required": ["video_id"]}, {"required": ["video_url"]}]
        return schema


class EndpointRegistry(BaseModel):
    schema_version: int = 1
    source: str
    as_of: str
    spec_version: str
    endpoints: list[ApiEndpoint]

    def preferred(self) -> list[ApiEndpoint]:
        groups: dict[str, ApiEndpoint] = {}
        for endpoint in self.endpoints:
            previous = groups.get(endpoint.group)
            if previous is None or _priority(endpoint) > _priority(previous):
                groups[endpoint.group] = endpoint
        return sorted(groups.values(), key=lambda endpoint: endpoint.key)

    def resolve(self, selector: str) -> ApiEndpoint:
        # Explicit historical paths and short keys both route to the current implementation.
        matches = [endpoint for endpoint in self.endpoints if selector in {endpoint.key, endpoint.path}]
        if not matches:
            raise SourceError("找不到已登记的 TikHub 接口。", hint="用 soota api list --platform 平台名 查询接口标识。")
        groups = {endpoint.group for endpoint in matches}
        if len(groups) != 1:
            raise InputError("接口标识不唯一。", hint="请使用 api list 中的完整 key 或 path。")
        return next(endpoint for endpoint in self.preferred() if endpoint.group in groups)


def _priority(endpoint: ApiEndpoint) -> tuple[bool, tuple[int, int], str]:
    return not endpoint.deprecated, endpoint.version, endpoint.path


@lru_cache(maxsize=1)
def load_registry() -> EndpointRegistry:
    return EndpointRegistry.model_validate_json(REGISTRY_PATH.read_text(encoding="utf-8"))


def endpoint_identity(path: str) -> tuple[str, str, str, tuple[int, int]]:
    parts = path.removeprefix("/api/v1/").split("/")
    platform, action = parts[0], parts[-1]
    resource_parts: list[str] = []
    resource_version = 1
    for part in parts[1:-1]:
        version = re.fullmatch(r"v(\d+)", part)
        suffix = re.fullmatch(r"(.+)_v(\d+)", part)
        if version:
            resource_version = max(resource_version, int(version[1]))
        elif suffix:
            resource_parts.append(suffix[1])
            resource_version = max(resource_version, int(suffix[2]))
        else:
            resource_parts.append(part)
    action_match = re.fullmatch(r"(.+)_v(\d+)", action)
    action_version = int(action_match[2]) if action_match else 1
    action = action_match[1] if action_match else action
    return platform, ".".join(resource_parts), action, (resource_version, action_version)


def _semantic_action(platform: str, action: str) -> str:
    # Instagram V3 renamed fetch_* to get_*; these aliases were checked against the OpenAPI summaries.
    if platform != "instagram":
        return action
    renamed = {
        "fetch_user_info": "get_user_profile",
        "fetch_user_info_by_username": "get_user_profile",
        "fetch_user_info_by_id": "user_id_to_username",
        "fetch_post_by_url": "get_post_info",
        "fetch_post_by_id": "get_post_info",
        "fetch_user_about_info": "get_user_about",
        "fetch_related_profiles": "get_similar_users",
    }
    return renamed.get(action, re.sub(r"^fetch_", "get_", action))


def endpoint_tasks(path: str, summary: str) -> list[str]:
    action = path.rsplit("/", 1)[-1].lower() + " " + summary.lower().replace(" ", "_")
    patterns = {
        "search": r"search|query|suggest",
        "comments": r"comment|repl(?:y|ies)|danmaku",
        "media": r"subtitle|caption|playurl|play_url|stream|audio|download|video_url",
        "live": r"live|webcast",
        "trends": r"trending|trends|hot_|hotlist|rank|billboard|leaderboard",
        "catalog": r"posts|videos|notes|feed|articles|collections|reels|stories|items|list",
        "profile": r"user|profile|channel|author|account|blogger|follower|following",
        "detail": r"detail|one_video|post_info|video_info|one_post|one_note|article_content",
        "analytics": r"analytics|insights|stats|statistic|audience|portrait|analysis|analyse|overview|metrics",
        "commerce": r"product|goods|shop|ads|advertis|commerce|delivery|promot",
    }
    tasks = [task for task, pattern in patterns.items() if re.search(pattern, action)]
    return tasks or ["utility"]


def _readable(platform: str, action: str, summary: str) -> bool:
    if platform not in PLATFORM_NAMES:
        return False
    described_query = re.search(
        r"/\s*(?:Get|Fetch|Search|Query|Detect|Convert|Extract|Find|Multi Get|Batch Get)\b", summary, re.I
    )
    return (
        bool(described_query)
        or action.startswith(("get_", "fetch_", "search", "query", "check_", "list_", "batch_"))
        or action
        in {
            "general_search",
            "shortcode_to_media_id",
            "media_id_to_shortcode",
            "user_id_to_username",
            "extract_shortcode",
            "translate_comment",
            "bulk_translate_comments",
            "bv_to_aid",
        }
    )


def _request_schema(value: Any, definitions: dict[str, Any], sensitive: bool = False) -> Any:
    if isinstance(value, list):
        return [_request_schema(item, definitions) for item in value]
    if not isinstance(value, dict):
        return value
    sensitive = sensitive or str(value.get("title", "")).lower() in CREDENTIAL_FIELDS
    if "$ref" in value:
        name = value["$ref"].removeprefix("#/components/schemas/")
        if name not in definitions:
            raise ValueError(f"Unknown or nonlocal request schema reference: {value['$ref']}")
        return _request_schema(
            {**definitions[name], **{k: v for k, v in value.items() if k != "$ref"}}, definitions, sensitive
        )
    # Keep validation constraints, not long response examples or documentation dumps.
    schema: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"example", "examples", "title", "description"}:
            continue
        if key == "default" and sensitive:
            continue
        if key in {"properties", "$defs", "patternProperties"}:
            schema[key] = {
                name: _request_schema(child, definitions, name.lower() in CREDENTIAL_FIELDS)
                for name, child in item.items()
            }
        elif key in {"default", "enum", "const"}:
            schema[key] = item
        else:
            schema[key] = _request_schema(item, definitions)
    if schema.get("type") == "object" and "properties" in schema:
        schema.setdefault("additionalProperties", False)
    return schema


def compile_registry(spec: dict[str, Any], as_of: str) -> EndpointRegistry:
    definitions = spec.get("components", {}).get("schemas", {})
    endpoints: list[ApiEndpoint] = []
    for path, methods in sorted(spec["paths"].items()):
        if not path.startswith("/api/v1/"):
            continue
        platform, resource, action, version = endpoint_identity(path)
        key = ".".join(part for part in (platform, resource, action) if part)
        group = ".".join(part for part in (platform, resource, _semantic_action(platform, action)) if part)
        for method, operation in methods.items():
            if method not in {"get", "post"}:
                continue
            parameters = [
                ApiParameter(
                    name=parameter["name"],
                    required=parameter.get("required", False),
                    schema=_request_schema(
                        parameter.get("schema", {}), definitions, parameter["name"].lower() in CREDENTIAL_FIELDS
                    ),
                    description=parameter.get("description", "")[:300],
                )
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "query"
            ]
            body = operation.get("requestBody", {})
            body_schema = body.get("content", {}).get("application/json", {}).get("schema")
            body_sensitive = bool(body_schema and str(body_schema.get("title", "")).lower() in CREDENTIAL_FIELDS)
            body_schema = _request_schema(body_schema, definitions) if body_schema is not None else None
            names = {parameter.name for parameter in parameters if parameter.required}
            if isinstance(body_schema, dict):
                names.update(body_schema.get("required", []))
            tag = (operation.get("tags") or [""])[0]
            operation_id = operation.get("operationId", "")
            endpoints.append(
                ApiEndpoint(
                    key=key,
                    group=group,
                    method=method.upper(),
                    path=path,
                    platform=platform,
                    resource=resource,
                    version=version,
                    summary=operation.get("summary", action),
                    docs_url=f"https://api.tikhub.io/#/{tag}/{operation_id}" if tag and operation_id else SPEC_URL,
                    tasks=endpoint_tasks(path, operation.get("summary", action)),
                    callable=_readable(platform, action, operation.get("summary", action)),
                    deprecated=operation.get("deprecated", False),
                    session_required=bool(names & {"cookie", "auth", "password", "session_token"}),
                    parameters=parameters,
                    body_schema=body_schema,
                    body_required=body.get("required", False),
                    body_sensitive=body_sensitive,
                )
            )
    return EndpointRegistry(source=SPEC_URL, as_of=as_of, spec_version=spec["info"]["version"], endpoints=endpoints)


def write_registry(spec_path: Path, destination: Path, as_of: str) -> EndpointRegistry:
    registry = compile_registry(json.loads(spec_path.read_text(encoding="utf-8")), as_of)
    destination.write_text(registry.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8")
    return registry
