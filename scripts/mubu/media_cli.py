"""图片/附件命令与只读鉴权检查。"""

import json

from mubu.media import MediaService
from mubu.node_cli import write_options

COMMANDS = {'image-upload', 'attachment-upload', 'attachments', 'auth-status'}


def add_commands(subparsers):
    for name, label in [('image-upload', '上传图片并追加到指定节点'),
                        ('attachment-upload', '上传附件并绑定到文档')]:
        parser = subparsers.add_parser(name, help=label + '；默认仅预览')
        parser.add_argument('doc_id')
        parser.add_argument('--file', required=True, help='本地文件')
        if name == 'image-upload':
            parser.add_argument('--node-id', required=True)
        write_options(parser)
    parser = subparsers.add_parser('attachments', help='读取文档附件列表')
    parser.add_argument('doc_id')
    parser.add_argument('--json', action='store_true')
    parser = subparsers.add_parser('auth-status', help='只读请求验证当前鉴权，不输出凭据')
    parser.add_argument('--json', action='store_true')


def run(client, args):
    if args.command == 'auth-status':
        client.get_list('0')
        result = {'status': 'authenticated', 'auth': args.auth}
    elif args.command == 'attachments':
        result = {'doc_id': args.doc_id, 'attachments': MediaService(client).attachments(args.doc_id)}
    else:
        result = MediaService(client).upload(args.doc_id, args.file,
                    kind='image' if args.command == 'image-upload' else 'attachment',
                    node_id=getattr(args, 'node_id', None), execute=args.execute,
                    expect_version=args.expect_version)
    print(json.dumps(result, ensure_ascii=False, indent=2))
