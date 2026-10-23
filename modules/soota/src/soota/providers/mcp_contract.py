from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from soota.errors import ContractError


def _schema(field: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    if depth > 8:
        raise ContractError("opencli-mcp 参数嵌套过深。")
    kind = field.get("type", "string")
    if kind not in {"string", "int", "number", "boolean", "array", "object"}:
        raise ContractError("opencli-mcp 参数类型不受支持。")
    result: dict[str, Any] = {"type": "integer" if kind == "int" else kind}
    if kind == "array":
        result["items"] = _schema(field.get("items", {"type": "string"}), depth + 1)
    if kind == "object":
        properties = field.get("properties", {})
        result.update(
            properties={key: _schema(value, depth + 1) for key, value in properties.items()},
            required=[key for key, value in properties.items() if value.get("required") is True],
            additionalProperties=False,
        )
    for source, target in (("min", "minimum"), ("max", "maximum")):
        if source in field:
            result[target if kind != "array" else ("minItems" if source == "min" else "maxItems")] = field[source]
    for key in ("minLength", "maxLength"):
        if key in field:
            result[key] = field[key]
    if field.get("choices"):
        result["enum"] = field["choices"]
    if field.get("nullable"):
        result = {"anyOf": [result, {"type": "null"}]}
    return result


def validate_read_command(
    payload: dict[str, Any], site: str, command: str, args: dict[str, Any], expected_domain: str | None
) -> None:
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ContractError("opencli-mcp 未返回站点命令元数据。")
    matches = [row for row in rows if isinstance(row, dict) and row.get("site") == site and row.get("name") == command]
    if len(matches) != 1 or matches[0].get("access") != "read":
        raise ContractError("opencli-mcp 站点命令不符合只读契约。")
    row = matches[0]
    if (
        not isinstance(row.get("domain"), str)
        or not row["domain"]
        or (expected_domain is not None and row["domain"] != expected_domain)
    ):
        raise ContractError("opencli-mcp 站点域名不符合只读契约。")
    try:
        json.dumps(args, allow_nan=False)
        fields = row["args"]
        if not isinstance(fields, list):
            raise ValueError
        properties = {field["name"]: field for field in fields}
        if len(properties) != len(fields):
            raise ValueError
        schema = _schema({"type": "object", "properties": properties})
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(args)
    except (KeyError, TypeError, ValueError, AttributeError, SchemaError, ValidationError) as exc:
        raise ContractError("opencli-mcp 参数不符合当前契约；请重新查询命令并核对 JSON 参数。") from exc
