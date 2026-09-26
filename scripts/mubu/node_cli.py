"""节点子命令参数与 JSON 输出；默认预览。"""

import json

from mubu.node_service import NodeEditor

COMMANDS = {"nodes", "node-update", "node-create", "node-delete"}


def add_commands(subparsers):
    parser = subparsers.add_parser("nodes", help="列出云端节点 ID、正文、描述及文档版本")
    parser.add_argument("doc_id")
    parser.add_argument("--query", help="筛选节点正文和描述")
    parser.add_argument("--json", action="store_true", help="JSON 输出（默认）")
    for command, label in [("node-update", "替换节点正文或描述（纯文本）"),
                           ("node-create", "在指定节点下新建子节点"),
                           ("node-delete", "删除指定节点及其全部后代")]:
        parser = subparsers.add_parser(command, help=label + "；默认仅预览")
        parser.add_argument("doc_id")
        parser.add_argument("--node-id", required=True, help="目标节点 ID；新增时为父节点 ID")
        parser.add_argument("--execute", action="store_true", help="发送一次写请求并读回核验")
        parser.add_argument("--expect-version", type=int, help="拒绝与预览版本不同的文档")
        parser.add_argument("--json", action="store_true", help="JSON 输出（默认）")
        if command != "node-delete":
            parser.add_argument("--text", required=True, help="纯文本；替换整个字段，不保留该字段原格式")
        if command == "node-update":
            parser.add_argument("--field", choices=["text", "note"], default="text")
        if command == "node-create":
            parser.add_argument("--note", help="新节点描述")
            parser.add_argument("--index", type=int, help="从 0 开始；默认追加到末尾")


def run(client, args):
    editor = NodeEditor(client)
    if args.command == "nodes":
        result = editor.nodes(args.doc_id, args.query)
    else:
        fields = {key: getattr(args, key) for key in ["text", "field", "note", "index"]
                  if hasattr(args, key)}
        result = editor.mutate(args.doc_id, args.command.removeprefix("node-"), args.node_id,
                               execute=args.execute, expect_version=args.expect_version, **fields)
    print(json.dumps(result, ensure_ascii=False, indent=2))
