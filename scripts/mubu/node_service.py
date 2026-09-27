"""节点编辑闭环：快照、预览、单次提交、读回核验及本地操作记录。"""

import json
import os
import secrets
import uuid
from pathlib import Path

from mubu.config import MubuError
from mubu.nodes import equivalent, list_nodes, make_plan


class NodeWriteError(MubuError):
    def __init__(self, result):
        super().__init__(result["message"])
        self.result = result


class NodeEditor:
    def __init__(self, client, state_dir=None):
        self.client = client
        self.state_dir = Path(state_dir or os.getenv(
            "MUBU_STATE_DIR", str(Path.home() / ".local/state/mubu-cli")))

    def snapshot(self, doc_id):
        endpoint = getattr(self.client, "document_endpoint", "/document/edit/get")
        raw = self.client._request("POST", endpoint, max_retries=0,
                                   json={"docId": doc_id, "password": "", "isFromDocDir": True})
        if not isinstance(raw, dict):
            raise MubuError("文档响应不是 JSON 对象")
        try:
            definition = json.loads(raw["definition"])
            version = raw["baseVersion"]
        except (ValueError, TypeError, KeyError):
            raise MubuError("文档快照缺少有效 definition/baseVersion") from None
        if not isinstance(definition, dict) or type(version) is not int or version < 0:
            raise MubuError("文档快照格式或版本号无效")
        return {"doc_id": doc_id, "name": raw.get("name"),
                "version": version, "definition": definition}

    def nodes(self, doc_id, query=None, **options):
        snapshot = self.snapshot(doc_id)
        return {"doc_id": doc_id, "name": snapshot["name"], "version": snapshot["version"],
                "nodes": list_nodes(snapshot["definition"], query, **options)}

    def _record(self, path, record):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def mutate(self, doc_id, action, node_id, *, execute=False, expect_version=None, **kwargs):
        before = self.snapshot(doc_id)
        if expect_version is not None and before["version"] != expect_version:
            raise NodeWriteError({"status": "conflict", "executed": False,
                                  "message": "文档版本已变化；请重新读取并审核预览",
                                  "version": before["version"]})
        plan = make_plan(before, action, node_id, **kwargs)
        preview = {"status": "preview", "executed": False, "doc_id": doc_id,
                   "version": before["version"], "node_id": plan["node_id"],
                   "action": action, "event": plan["event"],
                   "message": "仅预览；使用 --execute 提交，--expect-version 可绑定本次版本"}
        if not execute:
            return preview
        if equivalent(before["definition"], plan["expected"], plan["changed_ids"]):
            return {**preview, "status": "unchanged", "message": "内容已相同，无需发送写请求"}
        # 这是客户端前置检查，不是服务端 CAS；检查到发送之间仍存在竞争窗口。
        current = self.snapshot(doc_id)
        if current != before:
            raise NodeWriteError({**preview, "status": "conflict",
                                  "message": "准备提交期间文档发生变化；未发送写请求"})
        operation_id = uuid.uuid4().hex
        path = self.state_dir / "operations" / (operation_id + ".json")
        record = {"operation_id": operation_id, "before": before,
                  "event": plan["event"], "status": "prepared",
                  "action": action, "node_id": plan["node_id"],
                  "expected": plan["expected"], "changed_ids": sorted(plan["changed_ids"])}
        self._record(path, record)
        payload = {"memberId": str(secrets.randbelow(2**53 - 1001) + 1000),
                   "type": "CHANGE", "version": before["version"],
                   "documentId": doc_id, "events": [plan["event"]]}
        error = None
        response = None
        try:
            response = self.client._request(
                "POST", "/colla/events", max_retries=0, _network_retries=0,
                headers={"x-reg-entrance": f"https://mubu.com/app/edit/home/{doc_id}"},
                json=payload,
            )
        except MubuError as exc:
            error = {"http_status": exc.status_code,
                     "api_code": exc.body.get("code") if isinstance(exc.body, dict) else None}
        result = {"doc_id": doc_id, "node_id": plan["node_id"], "action": action,
                  "operation_id": operation_id, "record": str(path), "executed": True}
        try:
            after = self.snapshot(doc_id)
            record["after"] = after
            matched = equivalent(after["definition"], plan["expected"], plan["changed_ids"])
            advanced_once = after["version"] == before["version"] + 1
            if matched and advanced_once:
                result.update(status="verified", version=after["version"],
                              message="已读回核验目标变化及其他节点内容")
                if error:
                    result["transport_warning"] = "请求响应异常，但读回确认了预期结果；未重发"
            elif error and error["api_code"] is not None and after == before:
                result.update(status="rejected", message="服务端拒绝写入，文档未变化；未重发")
            else:
                result.update(status="uncertain", version=after["version"],
                              message="写入结果未通过完整核验；请检查操作记录，不要直接重试")
        except MubuError:
            result.update(status="uncertain", message="已发送一次写请求，读回失败；不要直接重试")
        record.update(status=result["status"], result=result, response=response, error=error)
        try:
            self._record(path, record)
        except OSError:
            result["record_warning"] = "写后记录保存失败；保留以上已发送/核验结果，不要重复提交"
        if result["status"] != "verified":
            raise NodeWriteError(result)
        return result
