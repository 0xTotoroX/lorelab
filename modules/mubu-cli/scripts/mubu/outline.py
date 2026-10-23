"""大纲 JSON 校验及新节点构建；仅支持纯文本增量导入。

[INPUT]: 用户提供的 nodes/text/note/children JSON 与现有节点 ID。
[OUTPUT]: 校验后的大纲及带新 ID 的节点树。
[POS]: 节点计划的输入转换，不负责网络、覆盖或重试。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import json
import secrets
from pathlib import Path

from mubu.config import MubuError

# 客户端限制，不宣称服务端的容量上限。
MAX_BYTES = 512 * 1024
MAX_NODES = 500
MAX_DEPTH = 32


def validate_outline(value):
    if not isinstance(value, dict) or set(value) != {"nodes"}:
        raise ValueError('大纲必须是仅包含 "nodes" 列表的 JSON 对象')
    count = 0

    def visit(items, depth):
        nonlocal count
        if not isinstance(items, list) or depth > MAX_DEPTH:
            raise ValueError("children 必须是列表；大纲深度不能超过 32 层")
        for item in items:
            count += 1
            if count > MAX_NODES:
                raise ValueError("每批大纲最多 500 个节点，请按分支拆分")
            if (not isinstance(item, dict) or set(item) - {"text", "note", "children"}
                    or not isinstance(item.get("text"), str) or not item["text"].strip()):
                raise ValueError("节点需要非空 text，仅允许 text/note/children 字段")
            if "note" in item and not isinstance(item["note"], str):
                raise ValueError("note 必须为字符串")
            if "children" in item:
                visit(item["children"], depth + 1 if item["children"] else depth)

    if not value["nodes"]:
        raise ValueError("大纲 nodes 不能为空")
    visit(value["nodes"], 1)
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise ValueError("大纲不能超过 512 KiB，请按分支拆分")
    return count


def read_outline(path):
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("大纲文件不能超过 512 KiB")
    value = json.loads(raw)
    validate_outline(value)
    return value


def build_outline(value, existing_ids, now, render_text):
    # 在纯计划层同样校验，避免程序调用绕过 CLI 检查。
    validate_outline(value)
    ids = set(existing_ids)

    def build(item):
        node_id = secrets.token_hex(5)
        if node_id in ids:
            raise MubuError("新节点 ID 碰撞，请重新生成计划")
        ids.add(node_id)
        result = {"id": node_id, "text": render_text(item["text"]), "taskStatus": 0,
                  "modified": now, "children": [build(child) for child in item.get("children", [])]}
        if "note" in item:
            result["note"] = render_text(item["note"])
        return result

    nodes = [build(item) for item in value["nodes"]]
    return nodes, ids - set(existing_ids)
