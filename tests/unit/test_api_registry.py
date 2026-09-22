import pytest
from jsonschema import Draft202012Validator

from soota.errors import SourceError
from soota.providers.tikhub.registry import compile_registry, load_registry


@pytest.mark.parametrize(
    "selector,expected",
    [
        ("/api/v1/bilibili/web/fetch_one_video", "/api/v1/bilibili/web/fetch_one_video_v3"),
        ("/api/v1/bilibili/web/fetch_one_video_v2", "/api/v1/bilibili/web/fetch_one_video_v3"),
        ("youtube.web.get_video_info", "/api/v1/youtube/web_v2/get_video_info_v2"),
        ("/api/v1/youtube/web/get_channel_id_v2", "/api/v1/youtube/web_v2/get_channel_id"),
        ("/api/v1/instagram/v1/fetch_user_posts", "/api/v1/instagram/v3/get_user_posts"),
        ("/api/v1/instagram/v2/fetch_user_info", "/api/v1/instagram/v3/get_user_profile"),
        ("douyin.app.fetch_multi_video", "/api/v1/douyin/app/v3/fetch_multi_video_v2"),
        ("xiaohongshu.web.fetch_note_detail", "/api/v1/xiaohongshu/web_v3/fetch_note_detail"),
        ("xiaohongshu.app.get_video_note_detail", "/api/v1/xiaohongshu/app_v2/get_video_note_detail"),
    ],
)
def test_latest_resource_and_operation_versions(selector, expected) -> None:
    assert load_registry().resolve(selector).path == expected


def test_numeric_versions_and_distinct_app_web_families() -> None:
    paths = {
        path: {"get": {"summary": "Get example"}}
        for path in [
            "/api/v1/youtube/web_v2/get_example_v3",
            "/api/v1/youtube/web_v2/get_example_v10",
            "/api/v1/youtube/web_v3/get_example",
            "/api/v1/youtube/app/get_example_v12",
            "/api/v1/youtube/web_v2/get_legacy_only",
        ]
    }
    registry = compile_registry({"info": {"version": "test"}, "paths": paths}, "2026-09-12")
    assert registry.resolve("youtube.web.get_example").path.endswith("web_v3/get_example")
    assert registry.resolve("youtube.app.get_example").path.endswith("app/get_example_v12")
    assert registry.resolve("youtube.web.get_legacy_only").path.endswith("web_v2/get_legacy_only")
    paths.pop("/api/v1/youtube/web_v3/get_example")
    registry = compile_registry({"info": {"version": "test"}, "paths": paths}, "2026-09-12")
    assert registry.resolve("youtube.web.get_example").path.endswith("get_example_v10")


def test_registry_request_schemas_are_valid_and_fully_local() -> None:
    registry = load_registry()
    for endpoint in registry.endpoints:
        Draft202012Validator.check_schema(endpoint.query_schema)
        if endpoint.body_schema is not None:
            Draft202012Validator.check_schema(endpoint.body_schema)
        assert "#/components/schemas/" not in endpoint.model_dump_json()
    assert len({endpoint.group for endpoint in registry.preferred()}) == len(registry.preferred())


def test_request_properties_named_title_description_or_examples_are_not_dropped() -> None:
    body = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "title help"},
            "description": {"type": "string"},
            "examples": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title"],
    }
    spec = {
        "info": {"version": "test"},
        "paths": {
            "/api/v1/wechat_mp/v2/fetch_test": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Test"}}},
                    },
                }
            }
        },
        "components": {"schemas": {"Test": body}},
    }
    endpoint = compile_registry(spec, "2026-09-12").endpoints[0]
    assert set(endpoint.body_schema["properties"]) == {"title", "description", "examples"}
    assert endpoint.body_schema["properties"]["title"] == {"type": "string"}


def test_unknown_urls_cannot_be_used_as_credential_bearing_api_targets() -> None:
    with pytest.raises(SourceError):
        load_registry().resolve("https://example.com/collect")
    assert not load_registry().resolve("/api/v1/tiktok/web/device_register").callable
    assert load_registry().resolve("/api/v1/bilibili/huahuo/upper_detail").callable


def test_cookie_body_is_marked_sensitive_without_shipping_example_credentials() -> None:
    endpoint = load_registry().resolve("douyin.web.fetch_query_user")
    assert endpoint.body_sensitive
    assert endpoint.body_schema == {"type": "string"}
