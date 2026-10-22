"""节点定位与单事件计划；保留原始 definition，绝不经 Markdown 整篇重建。

[INPUT]: 快照、目标 ID、纯文本或已校验大纲。
[OUTPUT]: 单事件修改计划、预期文档、整篇等价比较。
[POS]: 节点操作的纯计划层；大纲转换调用 outline。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import copy
import html
import secrets
import time
from html.parser import HTMLParser

from mubu.config import MubuError
from mubu.outline import build_outline
from mubu.rich_text import append_html, link_html, replace_text


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
    return "<span>" + html.escape(text) + "</span>"


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


def list_nodes(definition, query=None, root_id=None, depth=None, include_html=False):
    entries = indexed(definition)
    if root_id is not None and root_id not in entries:
        raise MubuError("分支节点 ID 不存在")
    if depth is not None and (type(depth) is not int or depth < 0):
        raise MubuError("深度必须为非负整数")
    root_path = entries[root_id][1] if root_id is not None else ("nodes",)
    result = []
    for node, path, parent_id in entries.values():
        if path[:len(root_path)] != root_path:
            continue
        level = len(path) - len(root_path) - (0 if root_id is not None else 1)
        if depth is not None and level > depth:
            continue
        text, note = plain(node.get("text", "")), plain(node.get("note", ""))
        if query and query.casefold() not in (text + "\n" + note).casefold():
            continue
        item = {"node_id": node["id"], "parent_id": parent_id,
                "path": api_path(path), "text": text, "note": note,
                "ancestors": [{"node_id": at(definition, path[:end])["id"],
                               "text": plain(at(definition, path[:end]).get("text", ""))}
                              for end in range(2, len(path))],
                "child_count": len(node.get("children", [])),
                "images": copy.deepcopy(node.get("images", []))}
        if include_html:
            item.update(text_html=node.get("text", ""), note_html=node.get("note", ""))
        result.append(item)
    return result


def _siblings(definition, path):
    return definition["nodes"] if len(path) == 2 else at(definition, path[:-1])["children"]


def _position(index, size):
    index = size if index is None else index
    if type(index) is not int or not 0 <= index <= size:
        raise MubuError("插入位置超出节点范围")
    return index


def make_plan(snapshot, action, node_id, text=None, field="text", note=None, index=None,
              parent_id=None, replace=None, append=False, url=None, label=None, image=None,
              outline=None):
    definition = snapshot["definition"]
    entries = indexed(definition)
    if node_id not in entries and not (action in {"create", "import"} and node_id is None):
        raise MubuError("目标节点 ID 不存在；未进行写入")
    node, path, old_parent = entries[node_id] if node_id is not None else ({}, (), None)
    expected = copy.deepcopy(definition)
    target = at(expected, path) if path else None
    now = int(time.time() * 1000)
    changed_ids = {at(definition, path[:end])["id"] for end in range(2, len(path) + 1)}
    result_id = node_id
    if action in {"update", "link", "image"}:
        if action == "image":
            if not isinstance(image, dict) or not image.get("id") or not image.get("uri"):
                raise MubuError("无效的图片引用")
            field = "images"
            original = node.get(field, [])
            if not isinstance(original, list):
                raise MubuError("原节点图片字段不是列表")
            if any(item.get("id") == image["id"] for item in original):
                raise MubuError("图片 ID 已存在，未重复添加")
            value = original + [copy.deepcopy(image)]
        else:
            if field not in {"text", "note"}:
                raise MubuError("仅支持 text/note 字段")
            original = node.get(field, "")
            plain(original)
            if action == "link":
                value = append_html(original, link_html(url, label or url))
            else:
                if not isinstance(text, str):
                    raise MubuError("更新需要字符串内容")
                if replace is not None and append:
                    raise MubuError("不能同时追加和替换")
                value = (replace_text(original, replace, text) if replace is not None else
                         append_html(original, as_html(text)) if append else as_html(text))
        target[field] = value
        event = {"name": "update", "updated": [{
            "updated": {"id": node_id, field: value, "modified": now},
            "original": {"id": node_id, field: original, "modified": node.get("modified")},
            "path": list(path),
        }]}
    elif action == "create":
        if not isinstance(text, str):
            raise MubuError("新节点内容必须为字符串")
        children = target.setdefault("children", []) if target is not None else expected.setdefault("nodes", [])
        index = _position(index, len(children))
        result_id = secrets.token_hex(5)
        if result_id in entries:
            raise MubuError("新节点 ID 碰撞，请重新生成计划")
        child = {"id": result_id, "taskStatus": 0, "text": as_html(text),
                 "modified": now, "children": []}
        if note is not None:
            child["note"] = as_html(note)
        children.insert(index, child)
        changed_ids.add(result_id)
        new_path = api_path(path) + ["children", index] if path else ["nodes", index]
        event = {"name": "create", "created": [{"index": index, "parentId": node_id,
                 "node": copy.deepcopy(child), "path": new_path}]}
    elif action == "import":
        children = target.setdefault("children", []) if target is not None else expected.setdefault("nodes", [])
        index = _position(index, len(children))
        imported, new_ids = build_outline(outline, entries, now, as_html)
        children[index:index] = imported
        changed_ids.update(new_ids)
        event = {"name": "create", "created": [
            {"index": index + offset, "parentId": node_id, "node": copy.deepcopy(child),
             "path": (api_path(path) + ["children", index + offset] if path else
                      ["nodes", index + offset])}
            for offset, child in enumerate(imported)]}
        result_id = imported[0]["id"]
    elif action == "delete":
        _siblings(expected, path).pop(path[-1])
        event = {"name": "delete", "deleted": [{"parentId": old_parent, "index": path[-1],
                 "node": copy.deepcopy(node), "path": api_path(path)}]}
    elif action == "move":
        if parent_id is not None:
            if parent_id not in entries:
                raise MubuError("目标父节点不存在")
            destination = entries[parent_id][1]
            if destination[:len(path)] == path:
                raise MubuError("不能移动到自身或后代节点下")
            changed_ids.update(at(definition, destination[:end])["id"]
                               for end in range(2, len(destination) + 1))
        moved = _siblings(expected, path).pop(path[-1])
        new_parent_path = indexed(expected)[parent_id][1] if parent_id is not None else None
        children = (at(expected, new_parent_path).setdefault("children", [])
                    if new_parent_path else expected["nodes"])
        index = _position(index, len(children))
        children.insert(index, moved)
        new_path = api_path(indexed(expected)[node_id][1])
        event = {"name": "structureChanged", "changed": [{
            "original": {"parentId": old_parent, "index": path[-1],
                         "node": copy.deepcopy(node), "path": api_path(path)},
            "changed": {"parentId": parent_id, "index": index,
                        "node": copy.deepcopy(moved), "path": new_path}}]}
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
