"""节点子命令参数与 JSON 输出；默认预览。

[INPUT]: CLI 参数和大纲 JSON 文件。
[OUTPUT]: nodes/node-* 命令注册与执行结果。
[POS]: 节点操作参数适配，复用 NodeEditor。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import json

from mubu.node_service import NodeEditor
from mubu.outline import read_outline

COMMANDS = {"nodes", "node-update", "node-create", "node-delete", "node-move", "node-link",
            "node-import"}


def write_options(parser):
    parser.add_argument("--execute", action="store_true", help="提交并读回核验（默认预览）")
    parser.add_argument("--expect-version", type=int, help="拒绝与预览版本不同的文档")
    parser.add_argument("--json", action="store_true", help="JSON 输出（默认）")


def add_commands(subparsers):
    parser = subparsers.add_parser("nodes", help="列出云端节点及文档版本")
    parser.add_argument("doc_id")
    parser.add_argument("--query", help="筛选节点正文和描述")
    parser.add_argument("--node-id", dest="root_id", help="只读取指定节点及后代")
    parser.add_argument("--depth", type=int, help="相对深度，0 只返回分支根（全篇时为顶层）")
    parser.add_argument("--include-html", action="store_true", help="同时返回原始正文/描述 HTML")
    parser.add_argument("--json", action="store_true", help="JSON 输出（默认）")
    labels = {"node-update": "修改节点正文或描述", "node-create": "新建节点",
              "node-import": "批量追加 JSON 大纲分支",
              "node-delete": "删除节点及全部后代", "node-move": "移动子树或调整顺序",
              "node-link": "保留原文并追加链接"}
    for command, label in labels.items():
        parser = subparsers.add_parser(command, help=label + "；默认仅预览")
        parser.add_argument("doc_id")
        if command in {"node-create", "node-import"}:
            group = parser.add_mutually_exclusive_group(required=True)
            group.add_argument("--node-id", help="父节点 ID")
            group.add_argument("--root", action="store_true", help="在文档顶层新增")
        else:
            parser.add_argument("--node-id", required=True, help="目标节点 ID")
        write_options(parser)
        if command == "node-import":
            parser.add_argument("--file", required=True, help="大纲 JSON 文件（nodes/text/note/children）")
        if command in {"node-update", "node-create"}:
            parser.add_argument("--text", required=True, help="纯文本内容")
        if command in {"node-update", "node-link"}:
            parser.add_argument("--field", choices=["text", "note"],
                                default="note" if command == "node-link" else "text")
        if command == "node-update":
            group = parser.add_mutually_exclusive_group()
            group.add_argument("--replace", help="只替换唯一匹配的原文字，保留格式；不跨格式片段")
            group.add_argument("--append", action="store_true", help="保留原文，另起一行追加")
        if command == "node-create":
            parser.add_argument("--note", help="新节点描述")
        if command in {"node-create", "node-move", "node-import"}:
            parser.add_argument("--index", type=int, help="从 0 开始；移动时按移除后的列表计数，默认末尾")
        if command == "node-move":
            group = parser.add_mutually_exclusive_group(required=True)
            group.add_argument("--parent-id", help="目标父节点 ID")
            group.add_argument("--root", action="store_true", help="移到文档顶层")
        if command == "node-link":
            parser.add_argument("--url", required=True, help="http/https/obsidian 链接")
            parser.add_argument("--label", help="链接显示文字，默认 URL")


def run(client, args, *, emit=True):
    editor = NodeEditor(client)
    if args.command == "nodes":
        result = editor.nodes(args.doc_id, args.query, root_id=args.root_id,
                              depth=args.depth, include_html=args.include_html)
    else:
        fields = {key: getattr(args, key) for key in
                  ["text", "field", "note", "index", "parent_id", "replace", "append", "url", "label"]
                  if hasattr(args, key)}
        if args.command == "node-import":
            fields["outline"] = read_outline(args.file)
        result = editor.mutate(args.doc_id, args.command.removeprefix("node-"), args.node_id,
                               execute=args.execute, expect_version=args.expect_version, **fields)
    if emit:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result
