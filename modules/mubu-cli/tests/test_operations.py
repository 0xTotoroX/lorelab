"""恢复核验只读、只给证据支持的结论，不把未找到视为可重试。"""

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mubu import operations
from mubu.config import MubuError
from mubu.node_service import NodeEditor, NodeWriteError

ID = 'a' * 32


@pytest.fixture
def record(tmp_path, monkeypatch):
    monkeypatch.setenv('MUBU_STATE_DIR', str(tmp_path))
    return {'operation_id': ID, 'status': 'uncertain', 'action': 'update', 'node_id': 'node',
            'before': {'doc_id': 'doc', 'version': 1, 'definition': {'nodes': []}},
            'expected': {'nodes': [{'id': 'node', 'text': 'expected-secret'}]}, 'changed_ids': ['node']}


def save(record):
    path = operations.state_dir() / 'operations' / (record['operation_id'] + '.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(record))
    return path


def test_local_query_is_redacted_and_requires_no_client(record, capsys, monkeypatch):
    save(record)
    result = operations.run(SimpleNamespace(command='operations', doc_id='doc', limit=20))
    assert result['operations'][0]['operation_id'] == ID
    assert 'expected-secret' not in json.dumps(result)
    local = operations.run(SimpleNamespace(command='operation-status', operation_id=ID, verify=False))
    assert local['record_status'] == 'uncertain' and local['retryable'] is False
    from mubu import cli
    monkeypatch.setattr(cli, 'MubuClient', Mock(side_effect=AssertionError('client constructed')))
    monkeypatch.setattr('sys.argv', ['mubu', '--agent', 'operations'])
    cli.main()
    assert json.loads(capsys.readouterr().out)['data']['operations'][0]['operation_id'] == ID


def test_invalid_paths_and_corrupt_records(record):
    with pytest.raises(MubuError):
        operations.load('../outside')
    path = save(record)
    path.write_text('broken')
    assert operations.list_operations()['invalid_records'] == 1
    with pytest.raises(MubuError):
        operations.load(ID)


def test_node_verification_requires_exact_version_and_full_content(record, monkeypatch):
    after = {'version': 2, 'definition': copy.deepcopy(record['expected'])}
    monkeypatch.setattr(NodeEditor, 'snapshot', lambda self, doc: after)
    client = Mock()
    path = save(record)
    original = path.read_bytes()
    result = operations.verify(record, client)
    assert result['status'] == 'verified' and result['verification_scope'] == 'whole_document'
    after['version'] = 3
    assert operations.verify(record, client)['status'] == 'uncertain'
    after['version'] = 2
    after['definition']['extra'] = 'unexpected'
    assert operations.verify(record, client)['status'] == 'uncertain'
    assert path.read_bytes() == original
    client._request.assert_not_called()


def test_old_record_cannot_be_guessed_verified(record):
    del record['expected']
    client = Mock()
    assert operations.verify(record, client)['status'] == 'uncertain'
    client._request.assert_not_called()
    save(record)
    with pytest.raises(NodeWriteError):
        operations.run(SimpleNamespace(command='operation-status', operation_id=ID, verify=True), client)


def test_no_change_does_not_mean_safe_to_retry(record, monkeypatch):
    monkeypatch.setattr(NodeEditor, 'snapshot', lambda self, doc: record['before'])
    result = operations.verify(record, Mock())
    assert result['status'] == 'uncertain' and result['retryable'] is False


def test_image_verification_only_claims_binding(record, monkeypatch):
    record.update(kind='image', image={'id': 'img', 'uri': 'fixture'}, node_id='node')
    monkeypatch.setattr(NodeEditor, 'snapshot', lambda self, doc: {'definition': {'nodes': [
        {'id': 'node', 'text': 'other edits', 'images': [record['image']]}]}})
    result = operations.verify(record, Mock())
    assert result['status'] == 'observed' and result['verification_scope'] == 'image_binding'
    assert result['retryable'] is False


def test_attachment_requires_known_id_and_checksum(record, monkeypatch):
    record.update(kind='attachment', prior_attachments=[], file={'size': 3, 'sha256': 'expected'})
    client = Mock()
    assert operations.verify(record, client)['status'] == 'uncertain'
    client._request.assert_not_called()
    record['attachment_id'] = 'attachment'
    client._request.side_effect = [{'attachments': [{'uuid': 'attachment'}]}, {'file_url': 'https://mubu.com/file'}]
    monkeypatch.setattr(operations, 'download_digest', lambda url, size: 'expected')
    result = operations.verify(record, client)
    assert result['status'] == 'verified' and result['verification_scope'] == 'attachment_content'
    assert all(call.args[0] == 'GET' for call in client._request.call_args_list)
    client._request.side_effect = [{'attachments': [{'uuid': 'attachment'}]}, {'file_url': 'https://mubu.com/file'}]
    monkeypatch.setattr(operations, 'download_digest', lambda url, size: 'wrong')
    assert operations.verify(record, client)['status'] == 'uncertain'


def test_persist_expected_before_send(record, monkeypatch, tmp_path):
    editor = NodeEditor(Mock(), tmp_path)
    before = {'doc_id': 'doc', 'version': 1, 'definition': {'nodes': [{'id': 'node', 'text': 'old'}]}}
    after = copy.deepcopy(before)
    after['version'] = 2
    after['definition']['nodes'][0]['text'] = '<span>new</span>'
    editor.snapshot = Mock(side_effect=[before, before, after])
    def send(*args, **kwargs):
        saved = json.loads(next((tmp_path / 'operations').glob('*.json')).read_text())
        assert saved['expected']['nodes'][0]['text'] == '<span>new</span>'
        assert saved['changed_ids'] == ['node']
        return {}
    editor.client._request.side_effect = send
    assert editor.mutate('doc', 'update', 'node', text='new', execute=True)['status'] == 'verified'
