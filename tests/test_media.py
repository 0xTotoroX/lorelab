"""媒体写入的阶段边界、保真和凭据隔离。"""
import copy
import json
from unittest.mock import Mock

import pytest
from PIL import Image

from mubu.config import MubuError
from mubu.media import MediaService, download_digest, read_file
from mubu.node_service import NodeWriteError


@pytest.fixture
def media(tmp_path):
    client = Mock()
    service = MediaService(client, tmp_path / 'state')
    service.editor.snapshot = Mock(return_value={'doc_id': 'doc', 'name': 'fixture', 'version': 4,
        'definition': {'nodes': [{'id': 'parent', 'text': '<b>保留</b>',
                                 'images': [{'id': 'old', 'uri': 'old'}]}]}})
    return service


@pytest.fixture
def png(tmp_path):
    path = tmp_path / 'fixture.png'
    Image.new('RGB', (12, 8), 'blue').save(path)
    return path


@pytest.fixture
def attachment(tmp_path):
    path = tmp_path / 'fixture.txt'
    path.write_text('附件验收', encoding='utf-8')
    return path


def test_image_preview_and_missing_node_never_upload(media, png):
    result = media.upload('doc', png, kind='image', node_id='parent')
    assert result['status'] == 'preview'
    media.client._request.assert_not_called()
    assert not media.editor.state_dir.exists()
    with pytest.raises(MubuError):
        media.upload('doc', png, kind='image', node_id='missing', execute=True)
    media.client._request.assert_not_called()


def test_image_upload_keeps_old_images_and_binds_expected_version(media, png):
    media.client._request.return_value = {'fileId': 'new-image'}
    media.editor.mutate = Mock(return_value={'status': 'verified', 'version': 5, 'operation_id': 'nodeop'})
    result = media.upload('doc', png, kind='image', node_id='parent', execute=True)
    assert result['status'] == 'verified'
    upload = media.client._request.call_args
    assert upload.kwargs['_network_retries'] == 0 and upload.kwargs['max_retries'] == 0
    assert not upload.kwargs['json']['data'].startswith('data:')
    args = media.editor.mutate.call_args.kwargs
    assert args['expect_version'] == 4
    assert args['image']['ow'] == 12 and args['image']['oh'] == 8
    record = json.loads(next((media.editor.state_dir / 'operations').glob('*.json')).read_text())
    assert record['stage'] == 'verified'
    assert 'token' not in json.dumps(record)


def test_image_binding_conflict_remains_uncertain_upload(media, png):
    media.client._request.return_value = {'fileId': 'already-uploaded'}
    media.editor.mutate = Mock(side_effect=NodeWriteError({'status': 'conflict', 'executed': False,
                                                         'message': 'changed'}))
    with pytest.raises(NodeWriteError) as error:
        media.upload('doc', png, kind='image', node_id='parent', execute=True)
    assert error.value.result['status'] == 'uncertain'
    assert error.value.result['executed'] is True
    assert error.value.result['stage'] == 'binding'
    assert media.client._request.call_count == 1


def test_attachment_bind_then_download_checksum(media, attachment, monkeypatch):
    media.attachments = Mock(side_effect=[[], [], [{'uuid': 'new'}]])
    media._upload_attachment = Mock(return_value='document_image/key')
    media.client._request.side_effect = [{'attachment_uuid': 'new'}, {'file_url': 'https://mubu.com/file'}]
    _, meta = read_file(attachment, 'attachment')
    monkeypatch.setattr('mubu.media.download_digest', lambda url, size: meta['sha256'])
    result = media.upload('doc', attachment, kind='attachment', execute=True)
    assert result['status'] == 'verified' and result['attachment_id'] == 'new'
    bind = media.client._request.call_args_list[0]
    assert bind.kwargs['json']['source'] == 'document'
    assert bind.kwargs['_api_version'] == 4 and bind.kwargs['_network_retries'] == 0


def test_attachment_concurrent_change_never_binds(media, attachment):
    media.attachments = Mock(return_value=[])
    media._upload_attachment = Mock(return_value='document_image/key')
    before = media.editor.snapshot.return_value
    changed = copy.deepcopy(before)
    changed['version'] += 1
    media.editor.snapshot.side_effect = [before, before, changed]
    with pytest.raises(NodeWriteError) as error:
        media.upload('doc', attachment, kind='attachment', execute=True)
    media.client._request.assert_not_called()
    assert error.value.result['stage'] == 'uploaded_unbound'


def test_attachment_checksum_failure_is_not_success(media, attachment, monkeypatch):
    media.attachments = Mock(side_effect=[[], [], [{'uuid': 'new'}]])
    media._upload_attachment = Mock(return_value='document_image/key')
    media.client._request.side_effect = [{'attachment_uuid': 'new'}, {'file_url': 'https://mubu.com/file'}]
    monkeypatch.setattr('mubu.media.download_digest', lambda url, size: 'wrong')
    with pytest.raises(NodeWriteError) as error:
        media.upload('doc', attachment, kind='attachment', execute=True)
    assert error.value.result['attachment_id'] == 'new'
    assert error.value.result['stage'] == 'bound'


def test_invalid_files_fail_before_network(media, tmp_path):
    path = tmp_path / 'image.png'
    path.write_bytes(b'not an image')
    with pytest.raises(MubuError):
        media.upload('doc', path, kind='image', node_id='parent', execute=True)
    path = tmp_path / 'payload.exe'
    path.write_bytes(b'unsupported')
    with pytest.raises(MubuError):
        media.upload('doc', path, kind='attachment', execute=True)
    media.client._request.assert_not_called()


def test_download_never_forwards_auth_and_rejects_redirect(monkeypatch):
    response = Mock(status_code=302)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    get = Mock(return_value=response)
    monkeypatch.setattr('mubu.media.requests.get', get)
    with pytest.raises(MubuError):
        download_digest('https://api2.mubu.com/file', 3)
    assert get.call_args.kwargs['allow_redirects'] is False
    assert 'headers' not in get.call_args.kwargs
    with pytest.raises(MubuError):
        download_digest('https://unrelated.example/file', 3)
    assert get.call_count == 1


def test_failed_storage_upload_has_durable_key(media, attachment):
    media.attachments = Mock(return_value=[])
    def fail(data, metadata, key):
        record = json.loads(next((media.editor.state_dir / 'operations').glob('*.json')).read_text())
        assert record['resource'] == key and record['stage'] == 'uploading'
        raise MubuError('storage timeout')
    media._upload_attachment = fail
    with pytest.raises(NodeWriteError) as error:
        media.upload('doc', attachment, kind='attachment', execute=True)
    assert error.value.result['stage'] == 'uploading'
    media.client._request.assert_not_called()
