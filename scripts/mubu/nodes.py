"""节点定位与单事件计划；保留原始 definition，绝不经 Markdown 整篇重建。"""

import copy
import html
import secrets
import time
from html.parser import HTMLParser

from mubu.config import MubuError


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")


def plain(value):
    if not isinstance(value, str):
        raise MubuError("暂不支持此节点的富文本数据格式；未进行写入")
    parser = _Text()
    parser.feed(value)
    return "".join(parser.parts)


def as_html(text):
    return "<span>" + html.escape(text).replace("\n", "<br>") + "</span>"


def walk(nodes, prefix=("nodes",), parent_id=None):
    if not isinstance(nodes, list):
        raise MubuError("节点 children/nodes 不是列表")
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            raise MubuError("文档含无效节点 ID")
        path = prefix + (index,)
        yield node, path, parent_id
        yield from walk(node.get("children", []), path, node["id"])


def indexed(definition):
    result = {}
    for node, path, parent_id in walk(definition.get("nodes", [])):
        if node["id"] in result:
            raise MubuError("文档含重复节点 ID，拒绝模糊定位")
        result[node["id"]] = (node, path, parent_id)
    return result


def at(definition, path):
    node = definition["nodes"][path[1]]
    for index in path[2:]:
        node = node["children"][index]
    return node


def api_path(path):
    result = ["nodes", path[1]]
    for index in path[2:]:
        result.extend(["children", index])
    return result


def list_nodes(definition, query=None):
    result = []
    for node, path, parent_id in indexed(definition).values():
        text, note = plain(node.get("text", "")), plain(node.get("note", ""))
        if query and query.casefold() not in (text + "\n" + note).casefold():
            continue
        result.append({"node_id": node["id"], "parent_id": parent_id,
                       "path": api_path(path), "text": text, "note": note,
                       "child_count": len(node.get("children", []))})
    return result


def make_plan(snapshot, action, node_id, text=None, field="text", note=None, index=None):
    definition = snapshot["definition"]
    entries = indexed(definition)
    if node_id not in entries:
        raise MubuError("目标节点 ID 不存在；未进行写入")
    node, path, parent_id = entries[node_id]
    expected = copy.deepcopy(definition)
    target = at(expected, path)
    now = int(time.time() * 1000)
    changed_ids = {at(definition, path[:end])["id"] for end in range(2, len(path) + 1)}
    result_id = node_id
    if action == "update":
        if field not in {"text", "note"} or not isinstance(text, str):
            raise MubuError("更新需要 text/note 字段和字符串内容")
        original = node.get(field, "")
        plain(original)  # 不擅自降级未知富文本格式
        target[field] = as_html(text)
        event = {"name": "update", "updated": [{
            "updated": {"id": node_id, field: target[field], "modified": now},
            "original": {"id": node_id, field: original, "modified": node.get("modified")},
            "path": list(path),
        }]}
    elif action == "create":
        if not isinstance(text, str):
            raise MubuError("新节点内容必须为字符串")
        children = target.setdefault("children", [])
        index = len(children) if index is None else index
        if type(index) is not int or not 0 <= index <= len(children):
            raise MubuError("插入位置超出子节点范围")
        result_id = secrets.token_hex(5)
        if result_id in entries:
            raise MubuError("新节点 ID 碰撞，请重新生成计划")
        child = {"id": result_id, "taskStatus": 0, "text": as_html(text),
                 "modified": now, "children": []}
        if note is not None:
            child["note"] = as_html(note)
        children.insert(index, child)
        changed_ids.add(result_id)
        event = {"name": "create", "created": [{"index": index, "parentId": node_id,
                 "node": copy.deepcopy(child), "path": api_path(path) + ["children", index]}]}
    elif action == "delete":
        siblings = expected["nodes"] if len(path) == 2 else at(expected, path[:-1])["children"]
        siblings.pop(path[-1])
        event = {"name": "delete", "deleted": [{"parentId": parent_id, "index": path[-1],
                 "node": copy.deepcopy(node), "path": api_path(path)}]}
    else:
        raise MubuError("不支持的节点操作")
    return {"action": action, "node_id": result_id, "target_id": node_id,
            "event": event, "expected": expected, "changed_ids": changed_ids}


def equivalent(actual, expected, changed_ids):
    """容忍服务端省略叶子的空 children/默认 taskStatus，以及受影响节点时间戳。"""
    def normalize(definition):
        result = copy.deepcopy(definition)
        for node, _, _ in walk(result.get("nodes", [])):
            node.setdefault("children", [])
            node.setdefault("taskStatus", 0)
            if node["id"] in changed_ids:
                node.pop("modified", None)
        return result
    return normalize(actual) == normalize(expected)
