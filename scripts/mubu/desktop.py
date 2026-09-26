"""只读复用幕布桌面登录，支持 macOS App Store / 普通版和 Windows。"""

import json
import os
import platform
from pathlib import Path
from typing import Optional

import requests

from mubu.client import MubuClient
from mubu.config import MubuError


def data_root(override: Optional[str] = None) -> Path:
    if override or os.getenv("MUBU_DATA_ROOT"):
        root = Path(override or os.environ["MUBU_DATA_ROOT"]).expanduser()
        if not (root / ".storage").is_dir():
            raise MubuError("指定的幕布数据目录中没有 .storage")
        return root
    home = Path.home()
    suffix = Path("Mubu/mubu_app_data/mubu_data")
    candidates = [
        home / "Library/Containers/com.mubu.mas/Data/Library/Application Support" / suffix,
        home / "Library/Application Support" / suffix,
        Path(os.environ.get("APPDATA", home / ".config")) / suffix,
        home / ".config/mubu/mubu_data",
    ]
    for root in candidates:
        if (root / ".storage").is_dir():
            return root
    raise MubuError("未找到幕布桌面数据；请先登录桌面端，或使用 --data-root 指定目录")


def read_session(root: Path) -> dict:
    """只扫描 users 集合，不修改 LevelDB、不读取文档、不保存 Token 副本。"""
    records = {}
    decoder = json.JSONDecoder()
    for path in (root / ".storage").glob("mubu_desktop_app-rxdb-1-users*/*"):
        if path.suffix not in {".log", ".ldb"} or not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore")
        cursor = 0
        while (start := text.find('{"', cursor)) >= 0:
            try:
                record, end = decoder.raw_decode(text[start:])
            except ValueError:
                cursor = start + 2
                continue
            cursor = start + end
            if not isinstance(record, dict) or not isinstance(record.get("id"), int):
                continue
            if "|u" not in record and not record.get("_deleted"):
                continue
            revision = str(record.get("_rev", "0")).split("-", 1)[0]
            rank = (int(revision) if revision.isdigit() else 0, record.get("|h") or 0)
            key = record["id"]
            if key not in records or rank >= records[key][0]:
                records[key] = (rank, record)
    users = [r for _, r in records.values() if r.get("|u") and not r.get("_deleted")]
    if not users:
        raise MubuError("未找到可用的桌面登录记录；请在幕布桌面端重新登录后重试")
    user = max(users, key=lambda r: r.get("|h") or 0)
    return {"token": user["|u"], "user_id": str(user["id"])}


class DesktopClient(MubuClient):
    """沿用现有 API 客户端，仅替换认证与文档读取入口。"""

    document_endpoint = "/document/get"

    def __init__(self, root: Optional[str] = None) -> None:
        self.data_root = data_root(root)
        session = read_session(self.data_root)
        self.token = session["token"]
        self.user_id = session["user_id"]
        self.phone = self.password = self.member_id = None
        self._session = requests.Session()

    def _get_headers(self) -> dict:
        system = {"Darwin": "mac", "Windows": "windows"}.get(platform.system(), "linux")
        return {
            "mubu-desktop": "true", "platform": system,
            "platform-version": platform.mac_ver()[0] or platform.release(),
            "User-Agent": f"{system} Mubu Electron", "token": self.token,
            "userId": self.user_id, "Content-Type": "application/json;charset=UTF-8",
        }

    def ensure_valid_token(self) -> None:
        if not self.token:
            self.login()

    def login(self) -> dict:
        raise MubuError("桌面会话失效；请在幕布桌面端重新登录，再重新运行 CLI")

    def get_doc(self, doc_id: str) -> dict:
        data = self._request("POST", self.document_endpoint, max_retries=0, json={"docId": doc_id})
        try:
            definition = json.loads(data["definition"])
            return {"name": data.get("name"), "nodes": definition.get("nodes", [])}
        except (KeyError, TypeError, ValueError, AttributeError):
            raise MubuError("幕布返回了无法解析的文档") from None

    def create_doc(self, name: str, folder_id: str = "0", content: str = "") -> str:
        data = self._request("POST", "/list/create_doc", max_retries=0, _network_retries=0,
                             json={"folderId": folder_id, "name": name, "content": content})
        doc_id = data.get("id") or data.get("doc", {}).get("id")
        if not doc_id:
            raise MubuError("创建响应缺少文档 ID；结果不确定，请先检查目录，不要盲目重试")
        return doc_id
