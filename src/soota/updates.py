from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.parse import quote

import httpx

from soota import __version__
from soota.config import SootaSettings
from soota.models import CommandResult
from soota.providers.opencli_runtime import OpenCLIRuntime
from soota.providers.process import run_process

PROVIDERS = (
    ("opencli-mcp", "jackwener/opencli-mcp", "https://registry.npmjs.org/opencli-mcp/latest"),
    ("opencli", "jackwener/OpenCLI", "https://registry.npmjs.org/@jackwener%2fopencli/latest"),
    ("tikhub", "TikHub/TikHub-API-Python-SDK", "https://pypi.org/pypi/tikhub/json"),
)


def _installed_versions(settings: SootaSettings) -> dict[str, str | None]:
    runtime = OpenCLIRuntime(settings).status()
    binary = shutil.which(settings.opencli_mcp.binary or "opencli-mcp")
    mcp_version = None
    if binary:
        result = run_process([binary, "--version"], timeout=10, max_bytes=65536)
        if result.returncode == 0:
            mcp_version = result.stdout.strip() or None
    try:
        tikhub_version = version("tikhub")
    except PackageNotFoundError:
        tikhub_version = None
    return {
        "opencli-mcp": mcp_version,
        "opencli": runtime["version"] if runtime.get("available") else None,
        "tikhub": tikhub_version,
    }


def _get(client: httpx.Client, url: str) -> dict[str, Any]:
    headers = {"Accept": "application/vnd.github+json"} if url.startswith("https://api.github.com/") else {}
    response = client.get(url, headers=headers)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("expected object")
    return payload


def _version_tuple(value: str | None) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        return None
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _check(settings: SootaSettings, client: httpx.Client) -> CommandResult:
    installed = _installed_versions(settings)
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for name, repository, registry in PROVIDERS:
        current = installed[name]
        row: dict[str, Any] = {
            "provider": name,
            "repository": f"https://github.com/{repository}",
            "installed_version": current,
            "latest_package_version": None,
            "package_update_available": None,
            "default_branch": None,
            "repository_pushed_at": None,
            "branch_relation_to_installed_tag": "unknown",
            "commits_ahead": None,
            "commits_behind": None,
        }
        try:
            package = _get(client, registry)
            latest = (package.get("info") or package).get("version")
            if not isinstance(latest, str) or not latest:
                raise ValueError("missing version")
            row["latest_package_version"] = latest
            local_parts, latest_parts = _version_tuple(current), _version_tuple(latest)
            if local_parts and latest_parts:
                row["package_update_available"] = latest_parts > local_parts
        except (httpx.HTTPError, ValueError, AttributeError):
            warnings.append(f"{name}：无法读取包仓库版本。")
        try:
            repo = _get(client, f"https://api.github.com/repos/{repository}")
            branch = repo.get("default_branch")
            if not isinstance(branch, str) or not branch:
                raise ValueError("missing branch")
            row["default_branch"] = branch
            row["repository_pushed_at"] = repo.get("pushed_at")
            if current and _version_tuple(current):
                comparison = _get(
                    client,
                    f"https://api.github.com/repos/{repository}/compare/"
                    f"{quote('v' + current, safe='')}...{quote(branch, safe='')}",
                )
                relation = comparison.get("status")
                if relation not in {"identical", "ahead", "behind", "diverged"}:
                    raise ValueError("unknown comparison")
                row["branch_relation_to_installed_tag"] = relation
                row["commits_ahead"] = comparison.get("ahead_by")
                row["commits_behind"] = comparison.get("behind_by")
        except (httpx.HTTPError, ValueError):
            warnings.append(f"{name}：无法比较上游仓库与本机版本标签。")
        rows.append(row)
    complete = not warnings
    return CommandResult(
        ok=complete,
        status="success" if complete else "partial",
        code="ok" if complete else "partial",
        exit_code=0 if complete else 2,
        message="三个 Provider 的上游更新检查完成。" if complete else "上游更新检查只完成了部分来源。",
        data={"soota_version": __version__, "checked_at": datetime.now(UTC).isoformat(), "provider_updates": rows},
        warnings=warnings,
    )


def check_updates(settings: SootaSettings, *, client: httpx.Client | None = None) -> CommandResult:
    if client is not None:
        return _check(settings, client)
    with httpx.Client(timeout=15) as session:
        return _check(settings, session)
