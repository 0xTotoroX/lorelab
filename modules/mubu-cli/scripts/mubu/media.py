"""节点图片与文档附件；上传、绑定、核验分阶段记录，不重发写请求。"""

import base64
import hashlib
import io
import mimetypes
import secrets
import uuid
import warnings
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image

from mubu.config import MubuError
from mubu.node_service import NodeEditor, NodeWriteError
from mubu.nodes import make_plan

MAX_FILE_BYTES = 50 * 1024 * 1024
ATTACHMENT_SUFFIXES = set(('pdf doc docx wps wpt dot ppt pptx txt rtf md xls xlsx csv pages '
                           'numbers keynote mm opml xmind epub mobi mp3 m4a wav aac flac ogg '
                           'mp4 mov webm avi mkv psd ai sketch eps fig drawio vsdx zip rar 7z tar gz').split())


def read_file(path, kind):
    path = Path(path).expanduser()
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise MubuError("文件不存在、为空或超过 CLI 的 50 MiB 上限")
    with path.open('rb') as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if not 0 < len(data) <= MAX_FILE_BYTES:
        raise MubuError("读取期间文件大小变化或超过 50 MiB")
    metadata = {"file_name": path.name, "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}
    if kind == 'image':
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as img:
                    if img.format not in {'PNG', 'JPEG', 'GIF'}:
                        raise MubuError("图片仅支持 PNG、JPEG、GIF；不自动转换或压缩")
                    metadata.update(width=img.width, height=img.height, format=img.format)
                    img.verify()
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise MubuError("图片格式无效或像素尺寸过大") from None
    elif path.suffix.lower().lstrip('.') not in ATTACHMENT_SUFFIXES:
        raise MubuError("附件类型不在幕布支持列表；图片请用 image-upload")
    return data, metadata


def image_reference(uri, metadata):
    width, height = metadata['width'], metadata['height']
    result = {"id": secrets.token_hex(5), "uri": uri, "ow": width, "oh": height}
    if max(width, height) > 400:
        result['w'] = min(400, width / height * 400)
    return result


def download_digest(url, size):
    """下载服务返回的临时链接；绝不转发幕布鉴权头，不记录签名 URL。"""
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise MubuError("附件下载地址格式异常")
        if not any(parsed.hostname == host or parsed.hostname.endswith('.' + host)
                   for host in ('mubu.com', 'volces.com', 'volccdn.com', 'bytedance.com')):
            raise MubuError("附件下载地址不是已知幕布存储域名，未下载")
        digest, count = hashlib.sha256(), 0
        with requests.get(url, timeout=30, stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise MubuError("附件下载核验失败")
            for chunk in response.iter_content(65536):
                count += len(chunk)
                if count > size:
                    raise MubuError("下载附件大于原文件，核验失败")
                digest.update(chunk)
        if count != size:
            raise MubuError("下载附件大小与原文件不符")
        return digest.hexdigest()
    except requests.RequestException:
        raise MubuError("附件下载核验网络异常") from None


class MediaService:
    def __init__(self, client, state_dir=None):
        self.client = client
        self.editor = NodeEditor(client, state_dir)

    def attachments(self, doc_id):
        data = self.client._request('GET', '/document/attachment/list', _api_version=4,
                                    max_retries=0, params={'doc_id': doc_id})
        items = data.get('attachments') if isinstance(data, dict) else None
        if not isinstance(items, list) or any(not isinstance(item, dict) or not item.get('uuid')
                                               for item in items):
            raise MubuError("附件列表格式异常")
        return items

    def _save(self, path, record, result):
        record['result'] = result
        try:
            self.editor._record(path, record)
        except OSError:
            result['record_warning'] = '写后记录保存失败，请保留当前结果，不要重复上传'

    def _upload_attachment(self, data, metadata, key):
        # SDK 只在附件上传时加载；临时凭据仅驻留内存，不写操作记录。
        import tos
        response = self.client._request('GET', '/tos/sts', max_retries=0)
        credentials = response.get('credentials') if isinstance(response, dict) else None
        if not isinstance(credentials, dict) or not all(credentials.get(key) for key in
                ('accessKeyId', 'secretAccessKey', 'sessionToken')):
            raise MubuError("幕布没有返回有效的临时上传凭据")
        storage = tos.TosClientV2(credentials['accessKeyId'], credentials['secretAccessKey'],
                                  'tos-cn-shanghai.volces.com', 'cn-shanghai',
                                  security_token=credentials['sessionToken'], max_retry_count=0,
                                  connection_time=15, socket_timeout=60)
        try:
            storage.put_object('mubu-img', key, content=data, content_length=len(data),
                               content_type=mimetypes.guess_type(metadata['file_name'])[0]
                               or 'application/octet-stream')
        except Exception:
            raise MubuError("附件存储上传失败或结果不确定；未重试，未发送文档绑定") from None
        finally:
            storage.close()
        return key

    def upload(self, doc_id, path, *, kind, node_id=None, execute=False, expect_version=None):
        data, metadata = read_file(path, kind)
        before = self.editor.snapshot(doc_id)
        if expect_version is not None and before['version'] != expect_version:
            raise NodeWriteError({'status': 'conflict', 'executed': False,
                                  'message': '文档版本已变化；未上传'})
        if kind == 'image':
            # 在任何上传请求之前验证节点和原图片字段。
            make_plan(before, 'image', node_id,
                      image=image_reference('preview:not-uploaded', metadata))
            prior = None
        else:
            prior = self.attachments(doc_id)
        result = {'status': 'preview', 'executed': False, 'doc_id': doc_id,
                  'kind': kind, 'file': metadata, 'version': before['version'],
                  'message': '仅预览，未上传；使用 --execute 上传并核验'}
        if node_id:
            result['node_id'] = node_id
        if not execute:
            return result
        if self.editor.snapshot(doc_id) != before:
            raise NodeWriteError({**result, 'status': 'conflict', 'message': '准备期间文档变化；未上传'})
        operation = uuid.uuid4().hex
        record_path = self.editor.state_dir / 'operations' / (operation + '.json')
        record = {'operation_id': operation, 'before': before, 'file': metadata,
                  'kind': kind, 'stage': 'prepared_upload', 'prior_attachments': prior}
        self.editor._record(record_path, record)
        result.update(executed=True, status='uncertain', operation_id=operation,
                      record=str(record_path), message='上传结果尚未核验')
        try:
            if kind == 'image':
                uploaded = self.client._request('POST', '/document/upload_img_base64',
                    max_retries=0, _network_retries=0,
                    json={'data': base64.b64encode(data).decode('ascii')})
                key = uploaded.get('fileId') if isinstance(uploaded, dict) else None
                if not isinstance(key, str) or not key:
                    raise MubuError('上传响应缺少图片引用；可能已上传，未绑定节点')
                record.update(stage='uploaded_unbound', resource=key)
                self.editor._record(record_path, record)
                # 上传期间云端可能变化；绑定必须仍基于原预览版本。
                image = image_reference(key, metadata)
                record.update(stage='binding', node_id=node_id, image=image)
                self.editor._record(record_path, record)
                bound = self.editor.mutate(doc_id, 'image', node_id, execute=True,
                            expect_version=before['version'], image=image)
                if bound.get('record_warning'):
                    result['node_record_warning'] = bound['record_warning']
                result.update(status='verified', version=bound['version'], image_uri=key,
                              node_operation=bound['operation_id'],
                              message='图片已上传，节点及其他文档内容已读回核验')
            else:
                suffix = Path(metadata['file_name']).suffix.lower().lstrip('.')
                key = f'document_image/{self.client.user_id}_{uuid.uuid4()}.{suffix}'
                record.update(stage='uploading', resource=key)
                self.editor._record(record_path, record)
                self._upload_attachment(data, metadata, key)
                record.update(stage='uploaded_unbound', resource=key)
                self.editor._record(record_path, record)
                if self.editor.snapshot(doc_id) != before or self.attachments(doc_id) != prior:
                    raise MubuError('上传期间文档或附件列表发生变化；文件已上传，未绑定')
                record['stage'] = 'binding'
                self.editor._record(record_path, record)
                bound = self.client._request('POST', '/document/attachment/bind', _api_version=4,
                    max_retries=0, _network_retries=0, json={
                        'doc_id': doc_id, 'tos_key': key, 'file_name': metadata['file_name'],
                        'file_suffix': Path(metadata['file_name']).suffix.lower().lstrip('.'),
                        'source': 'document'})
                attachment_id = bound.get('attachment_uuid') if isinstance(bound, dict) else None
                if not attachment_id:
                    raise MubuError('附件绑定响应缺少 ID；结果不确定，请先检查附件列表')
                result['attachment_id'] = attachment_id
                record.update(stage='bound', attachment_id=attachment_id)
                self.editor._record(record_path, record)
                after = self.attachments(doc_id)
                ids = {item['uuid'] for item in after}
                if attachment_id not in ids or not {item['uuid'] for item in prior} <= ids:
                    raise MubuError('附件列表读回不符合预期')
                download = self.client._request('GET', '/document/attachment/download',
                    _api_version=4, max_retries=0,
                    params={'doc_id': doc_id, 'attachment_uuid': attachment_id})
                url = download.get('file_url') if isinstance(download, dict) else None
                if not isinstance(url, str) or download_digest(url, len(data)) != metadata['sha256']:
                    raise MubuError('附件下载内容与原文件不符')
                result.update(status='verified', message='文档附件已绑定，列表与下载文件 SHA-256 已核验')
        except (MubuError, OSError) as error:
            if isinstance(error, NodeWriteError):
                result['node_result'] = error.result
            result.update(status='uncertain', stage=record['stage'],
                          message='上传或绑定未完成核验；可能留下已上传文件，请检查记录，不要直接重试')
            record['failure'] = str(error) if isinstance(error, MubuError) else '本地记录写入失败'
            self._save(record_path, record, result)
            raise NodeWriteError(result) from None
        record['stage'] = 'verified'
        self._save(record_path, record, result)
        return result
