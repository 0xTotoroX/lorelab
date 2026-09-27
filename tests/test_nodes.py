"""节点编辑的可观察契约：定位、只改目标、失败语义与单次发送。"""

import copy
import json
import os
import time
from pathlib import Path
from unittest import mock

import pytest
import requests
import responses

from mubu.client import MubuClient
from mubu.config import BASE_URL, MubuError
from mubu.desktop import DesktopClient, data_root, read_session
from mubu.node_service import NodeEditor, NodeWriteError
from mubu.nodes import equivalent, list_nodes, make_plan


@pytest.fixture
def snapshot():
    return {"doc_id": "doc", "name": "Fixture", "version": 8, "definition": {
        "layout": "keep", "nodes": [
            {"id": "parent", "text": "<b>父节点</b>", "note": "<span>描述</span>",
             "modified": 10, "color": "red", "images": [{"url": "test-image"}],
             "custom": {"keep": True}, "children": [
                 {"id": "child", "text": "<span>子节点</span>", "modified": 11,
                  "taskStatus": 1, "note": "<span>子描述</span>", "children": []}]},
            {"id": "sibling", "text": "<span>兄弟</span>", "modified": 12},
        ]}}


@pytest.fixture
def client(tmp_path):
    with mock.patch.object(MubuClient, "_load_env_file"), mock.patch.object(MubuClient, "_load_token"):
        client = MubuClient()
    client.token = "test-token"
    client.expires_at = time.time() + 3600
    return client


def respond_snapshot(snapshot):
    responses.post(BASE_URL + "/document/edit/get", json={"code": 0, "data": {
        "baseVersion": snapshot["version"], "name": snapshot["name"],
        "definition": json.dumps(snapshot["definition"])}})


def changed_snapshot(snapshot, field="text", value="<span>新正文</span>"):
    result = copy.deepcopy(snapshot)
    result["version"] += 1
    result["definition"]["nodes"][0][field] = value
    result["definition"]["nodes"][0]["modified"] = 99
    return result


@pytest.mark.parametrize("text", ["", "中文 & <标签>", "第一行\n第二行"])
def test_update_preserves_every_other_field(snapshot, text):
    original = copy.deepcopy(snapshot)
    plan = make_plan(snapshot, "update", "parent", text=text)
    assert snapshot == original
    assert list_nodes(plan["expected"])[0]["text"] == text
    actual = copy.deepcopy(plan["expected"])
    actual["nodes"][0]["text"] = snapshot["definition"]["nodes"][0]["text"]
    assert actual == snapshot["definition"]
    updated = plan["event"]["updated"][0]["updated"]
    assert set(updated) == {"id", "text", "modified"}


def test_nested_note_update_paths(snapshot):
    plan = make_plan(snapshot, "update", "child", text="备注", field="note")
    assert plan["event"]["updated"][0]["path"] == ["nodes", 0, 0]
    child = plan["expected"]["nodes"][0]["children"][0]
    assert child["text"] == "<span>子节点</span>"
    assert child["taskStatus"] == 1
    assert list_nodes(plan["expected"])[1]["note"] == "备注"


@pytest.mark.parametrize("index", [0, 1, None])
def test_create_preserves_existing_children_and_is_plain_text(snapshot, index):
    plan = make_plan(snapshot, "create", "parent", text="<b>literal</b>", index=index)
    created = plan["event"]["created"][0]
    assert created["path"] == ["nodes", 0, "children", 1 if index is None else index]
    nodes = list_nodes(plan["expected"])
    assert next(n for n in nodes if n["node_id"] == plan["node_id"])["text"] == "<b>literal</b>"
    assert next(n for n in nodes if n["node_id"] == "child")["note"] == "子描述"


@pytest.mark.parametrize("index", [-1, 2, True])
def test_create_invalid_index(snapshot, index):
    with pytest.raises(MubuError):
        make_plan(snapshot, "create", "parent", text="x", index=index)


@pytest.mark.parametrize("node_id,remaining,parent_id", [
    ("parent", ["sibling"], None), ("child", ["parent", "sibling"], "parent")])
def test_delete_only_target_subtree(snapshot, node_id, remaining, parent_id):
    plan = make_plan(snapshot, "delete", node_id)
    assert [n["node_id"] for n in list_nodes(plan["expected"])] == remaining
    deleted = plan["event"]["deleted"][0]
    assert deleted["parentId"] == parent_id
    if node_id == "parent":
        assert deleted["node"]["children"][0]["id"] == "child"


def test_duplicate_and_missing_ids_rejected(snapshot):
    with pytest.raises(MubuError):
        make_plan(snapshot, "delete", "missing")
    snapshot["definition"]["nodes"][1]["id"] = "parent"
    with pytest.raises(MubuError):
        list_nodes(snapshot["definition"])


def test_unsupported_rich_text_does_not_silently_strip(snapshot):
    snapshot["definition"]["nodes"][0]["text"] = [{"text": "unknown representation"}]
    with pytest.raises(MubuError):
        make_plan(snapshot, "update", "parent", text="new")


def test_full_verification_detects_non_target_damage(snapshot):
    actual = copy.deepcopy(snapshot["definition"])
    actual["nodes"][0]["images"] = []
    assert not equivalent(actual, snapshot["definition"], {"parent"})
    actual = copy.deepcopy(snapshot["definition"])
    actual["nodes"][1]["modified"] += 1
    assert not equivalent(actual, snapshot["definition"], {"parent"})


@responses.activate
def test_preview_never_writes_or_creates_record(snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    result = NodeEditor(client, tmp_path).mutate("doc", "delete", "parent")
    assert result["status"] == "preview"
    assert len(responses.calls) == 1
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("version", [None, "8", True, -1])
@responses.activate
def test_invalid_version_rejected(version, snapshot, client, tmp_path):
    snapshot["version"] = version
    respond_snapshot(snapshot)
    with pytest.raises(MubuError):
        NodeEditor(client, tmp_path).mutate("doc", "delete", "parent", execute=True)
    assert len(responses.calls) == 1


@responses.activate
def test_stale_preview_never_sends_write(snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    with pytest.raises(NodeWriteError) as exc:
        NodeEditor(client, tmp_path).mutate("doc", "delete", "parent", execute=True, expect_version=7)
    assert exc.value.result["status"] == "conflict"
    assert len(responses.calls) == 1


@responses.activate
def test_preflight_detects_same_version_content_change(snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    changed = copy.deepcopy(snapshot)
    changed["definition"]["nodes"][1]["text"] = "different"
    respond_snapshot(changed)
    with pytest.raises(NodeWriteError) as exc:
        NodeEditor(client, tmp_path).mutate("doc", "delete", "parent", execute=True)
    assert exc.value.result["status"] == "conflict"
    assert len(responses.calls) == 2


@responses.activate
def test_success_with_full_readback_and_private_record(snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    respond_snapshot(snapshot)
    respond_snapshot(changed_snapshot(snapshot))
    responses.post(BASE_URL + "/colla/events", json={"code": 0, "data": {"latestVersion": 9}})
    result = NodeEditor(client, tmp_path).mutate("doc", "update", "parent", text="新正文", execute=True)
    assert result["status"] == "verified"
    record_path = Path(result["record"])
    assert os.stat(record_path).st_mode & 0o777 == 0o600
    record = json.loads(record_path.read_text())
    assert record["before"] == snapshot
    assert "test-token" not in record_path.read_text()
    writes = [c for c in responses.calls if c.request.url.endswith("/colla/events")]
    assert len(writes) == 1
    payload = json.loads(writes[0].request.body)
    assert 1000 <= int(payload["memberId"]) < 2**53
    assert payload["version"] == 8


@pytest.mark.parametrize("failure", ["timeout", "500", "429", "html", "401"])
@responses.activate
def test_uncertain_write_is_never_retried(failure, snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    respond_snapshot(snapshot)
    respond_snapshot(snapshot)
    if failure == "timeout":
        responses.post(BASE_URL + "/colla/events", body=requests.Timeout("timeout"))
    elif failure == "html":
        responses.post(BASE_URL + "/colla/events", body="not json", status=200)
    else:
        responses.post(BASE_URL + "/colla/events", json={"code": int(failure)}, status=int(failure))
    with pytest.raises(NodeWriteError) as exc:
        NodeEditor(client, tmp_path).mutate("doc", "update", "parent", text="新正文", execute=True)
    assert exc.value.result["status"] in {"uncertain", "rejected"}
    assert len([c for c in responses.calls if c.request.url.endswith("/colla/events")]) == 1


@responses.activate
def test_timeout_but_committed_is_confirmed_by_readback(snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    respond_snapshot(snapshot)
    respond_snapshot(changed_snapshot(snapshot))
    responses.post(BASE_URL + "/colla/events", body=requests.Timeout("timeout"))
    result = NodeEditor(client, tmp_path).mutate("doc", "update", "parent", text="新正文", execute=True)
    assert result["status"] == "verified"
    assert "transport_warning" in result


@responses.activate
def test_api_success_but_other_node_damaged_is_not_success(snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    respond_snapshot(snapshot)
    after = changed_snapshot(snapshot)
    after["definition"]["nodes"][1]["text"] = "lost"
    respond_snapshot(after)
    responses.post(BASE_URL + "/colla/events", json={"code": 0, "data": {}})
    with pytest.raises(NodeWriteError) as exc:
        NodeEditor(client, tmp_path).mutate("doc", "update", "parent", text="新正文", execute=True)
    assert exc.value.result["status"] == "uncertain"


@responses.activate
def test_concurrent_extra_version_fails_verification(snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    respond_snapshot(snapshot)
    after = changed_snapshot(snapshot)
    after["version"] += 1
    respond_snapshot(after)
    responses.post(BASE_URL + "/colla/events", json={"code": 0, "data": {}})
    with pytest.raises(NodeWriteError):
        NodeEditor(client, tmp_path).mutate("doc", "update", "parent", text="新正文", execute=True)


def test_mac_app_store_session_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("MUBU_DATA_ROOT", raising=False)
    root = tmp_path / "Library/Containers/com.mubu.mas/Data/Library/Application Support/Mubu/mubu_app_data/mubu_data"
    collection = root / ".storage/mubu_desktop_app-rxdb-1-users"
    collection.mkdir(parents=True)
    raw = b'prefix' + json.dumps({"id": 1, "|u": "session", "|h": 10, "_rev": "1-abc"}).encode()
    file = collection / "000001.log"
    file.write_bytes(raw)
    assert data_root() == root
    assert read_session(root) == {"token": "session", "user_id": "1"}
    assert file.read_bytes() == raw
    assert DesktopClient()._get_headers()["token"] == "session"


def test_deleted_session_does_not_fall_back(tmp_path):
    collection = tmp_path / ".storage/mubu_desktop_app-rxdb-1-users"
    collection.mkdir(parents=True)
    records = [{"id": 1, "|u": "old", "_rev": "1-a"},
               {"id": 1, "_deleted": True, "_rev": "2-b"}]
    (collection / "001.log").write_text("".join(json.dumps(r) for r in records))
    with pytest.raises(MubuError):
        read_session(tmp_path)


@pytest.mark.parametrize("body", [None, [], "success"])
@responses.activate
def test_non_object_write_response_still_reads_back(body, snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    respond_snapshot(snapshot)
    respond_snapshot(changed_snapshot(snapshot))
    responses.post(BASE_URL + "/colla/events", body=json.dumps(body), content_type="application/json")
    result = NodeEditor(client, tmp_path).mutate("doc", "update", "parent", text="新正文", execute=True)
    assert result["status"] == "verified"
    assert "transport_warning" in result


@responses.activate
def test_postwrite_disk_failure_preserves_confirmed_result(snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    respond_snapshot(snapshot)
    respond_snapshot(changed_snapshot(snapshot))
    responses.post(BASE_URL + "/colla/events", json={"code": 0, "data": {}})
    editor = NodeEditor(client, tmp_path)
    with mock.patch.object(editor, "_record", side_effect=[None, OSError("disk full")]):
        result = editor.mutate("doc", "update", "parent", text="新正文", execute=True)
    assert result["status"] == "verified"
    assert result["executed"] and result["operation_id"] and result["record_warning"]


@responses.activate
def test_readback_failure_reports_uncertain(snapshot, client, tmp_path):
    respond_snapshot(snapshot)
    respond_snapshot(snapshot)
    responses.post(BASE_URL + "/document/edit/get", json={"code": 0, "data": []})
    responses.post(BASE_URL + "/colla/events", json={"code": 0, "data": {}})
    with pytest.raises(NodeWriteError) as exc:
        NodeEditor(client, tmp_path).mutate("doc", "update", "parent", text="新正文", execute=True)
    assert exc.value.result["status"] == "uncertain"
    assert json.loads(Path(exc.value.result["record"]).read_text())["status"] == "uncertain"


@pytest.mark.parametrize("args", [["--auth", "desktop", "login"],
                                 ["--data-root", "/unused", "list"]])
def test_auth_arguments_fail_without_credential_prompt(args):
    from mubu.cli import main
    with mock.patch("sys.argv", ["mubu", *args]), mock.patch("builtins.input") as prompt:
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 2
    prompt.assert_not_called()


def test_branch_depth_and_ancestor_context(snapshot):
    nodes = list_nodes(snapshot['definition'], root_id='child', depth=0, include_html=True)
    assert [n['node_id'] for n in nodes] == ['child']
    assert nodes[0]['ancestors'] == [{'node_id': 'parent', 'text': '父节点'}]
    assert nodes[0]['text_html'] == '<span>子节点</span>'
    assert [n['node_id'] for n in list_nodes(snapshot['definition'], depth=0)] == ['parent', 'sibling']
    with pytest.raises(MubuError):
        list_nodes(snapshot['definition'], root_id='missing')


def test_root_creation_preserves_existing_tree(snapshot):
    plan = make_plan(snapshot, 'create', None, text='root', index=1)
    assert plan['event']['created'][0]['parentId'] is None
    assert plan['event']['created'][0]['path'] == ['nodes', 1]
    assert plan['expected']['nodes'][0] == snapshot['definition']['nodes'][0]
    assert plan['expected']['nodes'][2] == snapshot['definition']['nodes'][1]


def test_move_subtree_recalculates_destination_path(snapshot):
    plan = make_plan(snapshot, 'move', 'parent', parent_id='sibling', index=0)
    assert plan['expected']['nodes'][0]['id'] == 'sibling'
    assert plan['expected']['nodes'][0]['children'][0] == snapshot['definition']['nodes'][0]
    change = plan['event']['changed'][0]
    assert change['original']['path'] == ['nodes', 0]
    assert change['changed']['path'] == ['nodes', 0, 'children', 0]
    assert plan['changed_ids'] == {'parent', 'sibling'}


def test_move_to_root_and_reorder(snapshot):
    plan = make_plan(snapshot, 'move', 'child', parent_id=None, index=0)
    assert [n['id'] for n in plan['expected']['nodes']] == ['child', 'parent', 'sibling']
    assert plan['expected']['nodes'][1]['children'] == []
    reordered = make_plan(snapshot, 'move', 'parent', index=1)
    assert [n['id'] for n in reordered['expected']['nodes']] == ['sibling', 'parent']


@pytest.mark.parametrize('parent_id', ['parent', 'child', 'missing'])
def test_move_rejects_cycles_and_missing_destinations(snapshot, parent_id):
    with pytest.raises(MubuError):
        make_plan(snapshot, 'move', 'parent', parent_id=parent_id)


def test_rich_replace_and_append_keep_format_links_and_images(snapshot):
    node = snapshot['definition']['nodes'][0]
    node['text'] = '<b>旧观点 &amp; 条件</b><a href="https://example.com">出处</a>'
    plan = make_plan(snapshot, 'update', 'parent', text='新观点', replace='旧观点')
    assert plan['expected']['nodes'][0]['text'] == node['text'].replace('旧观点', '新观点')
    assert plan['expected']['nodes'][0]['images'] == node['images']
    appended = make_plan(snapshot, 'update', 'parent', text='补充', append=True)
    assert appended['expected']['nodes'][0]['text'].startswith(node['text'] + '<span>\n</span>')


@pytest.mark.parametrize('source,old', [('<b>相同</b><i>相同</i>', '相同'),
                                        ('<b>跨</b><i>格式</i>', '跨格式'), ('abc', '')])
def test_rich_replace_rejects_ambiguous_or_cross_format(snapshot, source, old):
    snapshot['definition']['nodes'][0]['text'] = source
    with pytest.raises(MubuError):
        make_plan(snapshot, 'update', 'parent', text='new', replace=old)


def test_link_append_preserves_original_and_escapes(snapshot):
    plan = make_plan(snapshot, 'link', 'parent', field='note',
                     url='https://example.com/?a=1&b=2', label='<来源>')
    assert plan['expected']['nodes'][0]['note'] == (
        '<span>描述</span><span>\n</span><a href="https://example.com/?a=1&amp;b=2">&lt;来源&gt;</a>')
    with pytest.raises(MubuError):
        make_plan(snapshot, 'link', 'parent', url='javascript:alert(1)')


@responses.activate
def test_desktop_expired_read_gives_desktop_relogin_guidance(tmp_path):
    client = DesktopClient.__new__(DesktopClient)
    client.token, client.user_id = 'expired', 'user'
    client._session = requests.Session()
    responses.post(BASE_URL + '/document/get', json={'code': 10007, 'msg': 'Unauthorized'})
    with pytest.raises(MubuError, match='幕布桌面端重新登录'):
        NodeEditor(client, tmp_path).snapshot('doc')
    assert len(responses.calls) == 1


@responses.activate
def test_live_observed_login_expired_code_two(tmp_path):
    client = DesktopClient.__new__(DesktopClient)
    client.token, client.user_id = 'expired', 'user'
    client._session = requests.Session()
    responses.post(BASE_URL + '/document/get', json={'code': 2, 'msg': 'Login Expired',
                                                    'data': {'message': 'Login Expired'}})
    with pytest.raises(MubuError, match='幕布桌面端重新登录'):
        NodeEditor(client, tmp_path).snapshot('doc')
    assert len(responses.calls) == 1
