"""Agent 的进程输出、无交互、部分失败和单次请求契约。"""

import json
import time
from unittest.mock import Mock

import pytest
import requests
import responses

from mubu import __version__, cli
from mubu.client import MubuClient
from mubu.config import BASE_URL, MubuError
from mubu.node_service import NodeWriteError


@pytest.fixture
def client(monkeypatch):
    instance = Mock(phone=None, password=None)
    monkeypatch.setattr(cli, 'MubuClient', lambda: instance)
    return instance


def call(monkeypatch, capsys, *args):
    monkeypatch.setattr('sys.argv', ['mubu', '--agent', *args])
    code = 0
    try:
        cli.main()
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result['schema_version'] == 1 and result['cli_version'] == __version__
    return code, result


def test_login_never_prompts_or_leaks_token(client, monkeypatch, capsys):
    monkeypatch.setattr('builtins.input', Mock(side_effect=AssertionError('prompt')))
    monkeypatch.setattr('getpass.getpass', Mock(side_effect=AssertionError('prompt')))
    code, result = call(monkeypatch, capsys, 'login')
    assert code == 1 and result['error']['code'] == 'AUTH_REQUIRED'
    client.login.assert_not_called()
    client.phone, client.password = 'configured', 'secret'
    client.login.return_value = {'username': 'fixture', 'user_id': 'u1', 'token': 'hidden-token'}
    code, result = call(monkeypatch, capsys, 'login')
    assert code == 0 and result['data'] == {'username': 'fixture', 'user_id': 'u1'}
    assert 'hidden-token' not in json.dumps(result)


@pytest.mark.parametrize('args,expected', [
    (('save', 'doc'), 'INPUT_REQUIRED'),
    (('node-create', 'doc', '--root', '--text', 'x', '--execute'), 'VERSION_REQUIRED'),
    (('purge', 'doc'), 'CONFIRMATION_REQUIRED'),
    (('delete', 'doc'), 'CONFIRMATION_REQUIRED'),
])
def test_agent_preconditions_fail_without_client(client, monkeypatch, capsys, args, expected):
    code, result = call(monkeypatch, capsys, *args)
    assert code == 1 and result['error']['code'] == expected
    assert client.mock_calls == []


@pytest.mark.parametrize('args', [('missing-command',), ('nodes',), ('nodes', 'doc', '--depth', 'bad')])
def test_parser_errors_are_json(monkeypatch, capsys, args):
    code, result = call(monkeypatch, capsys, *args)
    assert code == 2 and result['error']['code'] == 'INVALID_ARGUMENTS'


def test_help_is_json(monkeypatch, capsys):
    code, result = call(monkeypatch, capsys, '--help')
    assert code == 0 and 'operation-status' in result['data']['help']


@pytest.mark.parametrize('command,result,key', [('create', 'doc1', 'doc_id'), ('mkdir', 'folder1', 'folder_id')])
def test_created_ids_are_structured(client, monkeypatch, capsys, command, result, key):
    client.create_doc.return_value = client.create_folder.return_value = result
    code, value = call(monkeypatch, capsys, command, 'new')
    assert code == 0 and value['data'][key] == result
    assert client.agent_mode is True


def test_search_preserves_truncation_and_reports_failures(client, monkeypatch, capsys):
    client.search.return_value = {'results': [], 'truncated': True, 'limit': 3, 'max_depth': 2, 'errors': 0}
    code, result = call(monkeypatch, capsys, 'search', 'x')
    assert code == 0 and result['data']['truncated'] is True
    client.search.return_value['errors'] = 1
    code, result = call(monkeypatch, capsys, 'search', 'x')
    assert code == 1 and result['status'] == 'partial'


@pytest.mark.parametrize('errors,truncated', [(1, False), (0, True)])
def test_incomplete_export_is_not_success(client, monkeypatch, capsys, errors, truncated):
    client.export_tree.return_value = {'docs': 1, 'folders': 0, 'errors': errors, 'truncated': truncated}
    code, result = call(monkeypatch, capsys, 'export-tree')
    assert code == 1 and result['error']['code'] == 'PARTIAL_FAILURE'


@pytest.mark.parametrize('status,code', [('conflict', 2), ('uncertain', 3), ('rejected', 3)])
def test_node_failure_keeps_operation_id(client, monkeypatch, capsys, status, code):
    monkeypatch.setattr(cli.node_cli, 'run', Mock(side_effect=NodeWriteError({
        'status': status, 'operation_id': 'abc', 'message': 'fixture'})))
    actual, result = call(monkeypatch, capsys, 'node-delete', 'doc', '--node-id', 'node')
    assert actual == code and result['data']['operation_id'] == 'abc'
    assert result['error']['retryable'] is False


def test_error_never_emits_raw_server_body(client, monkeypatch, capsys):
    client.create_doc.side_effect = MubuError('hidden-token', body={'token': 'hidden-token'})
    code, result = call(monkeypatch, capsys, 'create', 'new')
    assert code == 1 and result['status'] == 'uncertain'
    assert 'hidden-token' not in json.dumps(result)


@responses.activate
@pytest.mark.parametrize('failure', ['timeout', 'server', 'auth'])
def test_agent_write_never_retries_or_reauthenticates(monkeypatch, failure):
    monkeypatch.setattr(MubuClient, '_load_env_file', lambda s: None)
    monkeypatch.setattr(MubuClient, '_load_token', lambda s: None)
    client = MubuClient()
    client.agent_mode = True
    client.token, client.expires_at = 'fixture', time.time() + 3600
    client.login = Mock(side_effect=AssertionError('unexpected login'))
    if failure == 'timeout':
        responses.post(BASE_URL + '/list/create_doc', body=requests.Timeout('timeout'))
    elif failure == 'server':
        responses.post(BASE_URL + '/list/create_doc', status=503)
    else:
        responses.post(BASE_URL + '/list/create_doc', json={'code': 2, 'msg': 'Login Expired'})
    with pytest.raises(MubuError):
        client.create_doc('new')
    assert len(responses.calls) == 1
    client.login.assert_not_called()


def test_export_depth_and_search_failure_are_explicit(tmp_path, monkeypatch):
    client = MubuClient.__new__(MubuClient)
    client.get_list = Mock(return_value={'folders': [{'id': 'child', 'name': 'child'}], 'docs': []})
    stats = client.export_tree('0', str(tmp_path), max_depth=0)
    assert stats['truncated'] is True
    client._load_trash = Mock(return_value={})
    client.get_list.side_effect = MubuError('network')
    result = client.search('missing')
    assert result['errors'] == 1 and result['failures'] == [{'type': 'folder', 'id': '0'}]


@pytest.mark.parametrize('command', ['create', 'mkdir'])
@pytest.mark.parametrize('missing_id', ['', None, {}])
def test_create_missing_id_is_uncertain(client, monkeypatch, capsys, command, missing_id):
    client.create_doc.return_value = client.create_folder.return_value = missing_id
    code, result = call(monkeypatch, capsys, command, 'new')
    assert code == 1 and result['error']['code'] == 'WRITE_UNCONFIRMED'
    assert result['status'] == 'uncertain' and result['error']['retryable'] is False


@pytest.mark.parametrize('command', ['search', 'export-tree'])
def test_partial_failure_stderr_does_not_echo_server_message(monkeypatch, capsys, command, tmp_path):
    client = MubuClient.__new__(MubuClient)
    client._load_trash = Mock(return_value={})
    client.get_list = Mock(side_effect=MubuError('SYNTHETIC_SECRET'))
    monkeypatch.setattr(cli, 'MubuClient', lambda: client)
    args = ['search', 'x'] if command == 'search' else ['export-tree', '--output', str(tmp_path)]
    monkeypatch.setattr('sys.argv', ['mubu', '--agent', *args])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert 'SYNTHETIC_SECRET' not in captured.out + captured.err
    assert json.loads(captured.out)['status'] == 'partial'
