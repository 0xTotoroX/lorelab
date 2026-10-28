"""[INPUT]: 可演进分类的概念、父子关系、显示顺序和文章归属。
[OUTPUT]: schema v2 校验、稳定编码与显示编号分离的目录树。
[POS]: library 的自适应分类契约；不搬动文件、不推断语义。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import re

from .workflow_state import parts, path_key, require


def empty() -> dict:
    return {"schema_version": 2, "id": "adaptive-library", "version": 1, "title": "知识图书馆",
            "categories": [], "assignments": {}, "retired_codes": [], "next_code": 1,
            "exclude_files": ["知识索引.md", "图书馆目录.md"]}


def safe_name(name):
    require(isinstance(name, str) and name == name.strip() and name and name not in {".", ".."}
            and not any(c in name for c in '/\\:*?"<>|') and not name.endswith(".")
            and not any(ord(c) < 32 for c in name), "类别名称不能用作安全目录名。")
    require(name.split(".", 1)[0].upper() not in {"CON", "PRN", "AUX", "NUL",
            *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}, "类别名为系统保留名称。")


def validate(value: dict) -> dict:
    require(type(value.get("schema_version")) is int and value["schema_version"] == 2, "分类 schema 无效。")
    require(isinstance(value.get("id"), str) and value["id"].strip(), "分类缺少 id。")
    require(type(value.get("version")) is int and value["version"] > 0, "分类 version 无效。")
    require(isinstance(value.get("title"), str) and value["title"].strip(), "分类缺少 title。")
    entries = value.get("categories")
    require(isinstance(entries, list), "categories 必须为数组。")
    codes, paths, names = {}, set(), set()
    for entry in entries:
        require(isinstance(entry, dict), "类别必须为对象。")
        code = entry.get("code")
        require(isinstance(code, str) and re.fullmatch(r"K[0-9]{4,}", code) and code not in codes,
                "类别 code 必须为唯一的 K 编码。")
        safe_name(entry.get("name"))
        require(entry.get("parent") is None or isinstance(entry["parent"], str), "parent 无效。")
        require(type(entry.get("order")) is int and entry["order"] >= 0, "order 无效。")
        require(isinstance(entry.get("scope"), str) and entry["scope"].strip(), "类别须说明适用范围。")
        for part in parts(entry.get("path")):
            safe_name(part)
            require(not part.startswith("."), "拒绝隐藏类别目录。")
        key = path_key(entry["path"])
        require(key not in paths, "类别物理目录重复。")
        paths.add(key)
        name_key = (entry.get("parent"), path_key(entry["name"]))
        require(name_key not in names, "同层类别名称重复。")
        names.add(name_key)
        codes[code] = entry
    for code, entry in codes.items():
        chain = {code}
        parent = entry.get("parent")
        while parent is not None:
            require(parent in codes and parent not in chain, "类别父级缺失或形成循环。")
            chain.add(parent)
            parent = codes[parent].get("parent")
    retired = value.get("retired_codes", [])
    require(isinstance(retired, list) and all(isinstance(c, str) for c in retired)
            and len(retired) == len(set(retired)) and not set(retired) & codes.keys(), "退役编码重复或仍在使用。")
    allocated = [int(c[1:]) for c in [*codes, *retired] if re.fullmatch(r"K[0-9]{4,}", c)]
    require(type(value.get("next_code")) is int and value["next_code"] > max(allocated, default=0),
            "next_code 不能复用已分配编码。")
    assignments = value.get("assignments")
    require(isinstance(assignments, dict), "assignments 必须为路径到编码的映射。")
    for path, code in assignments.items():
        require(code is None or isinstance(code, str) and code in codes, "文章归属引用未知类别。")
        require(all(not p.startswith(".") for p in parts(path)) and path.lower().endswith(".md"), "文章归属路径无效。")
    excluded = value.get("exclude_files", [])
    require(isinstance(excluded, list) and all(isinstance(x, str) and x.endswith(".md")
            and "/" not in x and "\\" not in x for x in excluded), "exclude_files 无效。")
    return value


def ordered(taxonomy: dict) -> list[tuple[str, dict]]:
    children = {}
    for entry in taxonomy["categories"]:
        children.setdefault(entry.get("parent"), []).append(entry)
    result = []

    def visit(parent, prefix):
        for i, entry in enumerate(sorted(children.get(parent, []), key=lambda e: (e["order"], e["code"])), 1):
            label = f"{prefix}.{i:02}" if prefix else f"{i:02}"
            result.append((label, entry))
            visit(entry["code"], label)

    visit(None, "")
    return result


def contains(taxonomy: dict, selected: str, actual: str | None) -> bool:
    entries = {e["code"]: e for e in taxonomy["categories"]}
    while actual in entries:
        if actual == selected:
            return True
        actual = entries[actual].get("parent")
    return False


def tree(taxonomy: dict) -> str:
    return "\n".join([taxonomy["title"] + "/", *(
        "  " * label.count(".") + f"{label} {entry['name']} [{entry['code']}]"
        for label, entry in ordered(taxonomy))])
