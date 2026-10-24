"""[INPUT]: 已回读的配对 Git 标签回执、审阅过的发布说明和纯 Skill 插件。
[OUTPUT]: 两个 GitHub Release；重跑核对既有正文/文件，不覆盖已发行内容。
[POS]: CI 的 GitHub 分发适配，Git 同步与标签逻辑仍属于 lorelab。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def gh(*args):
    return subprocess.run(["gh", *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                          timeout=120, check=False)


def checked(*args):
    result = gh(*args)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "GitHub operation failed")
    return result.stdout


def lookup(repo, tag):
    response = gh("api", f"repos/{repo}/releases/tags/{tag}")
    if response.returncode:
        try:
            error = json.loads(response.stdout)
        except ValueError:
            raise RuntimeError("GitHub release lookup failed; no release was created") from None
        if str(error.get("status")) == "404":
            # 按 tag 查询只返回已发布版本；草稿需要有 push 权限的 releases 列表。
            pages = json.loads(checked("api", f"repos/{repo}/releases?per_page=100", "--paginate", "--slurp"))
            matches = [item for page in pages for item in page if item["tag_name"] == tag]
            if len(matches) > 1:
                raise ValueError(f"{repo}: multiple release drafts use {tag}; resolve them before retrying")
            return matches[0] if matches else None
        raise RuntimeError("GitHub release lookup failed; no release was created")
    return json.loads(response.stdout)


def github_repository(location):
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?", location)
    if not match:
        raise ValueError("release receipt must refer to GitHub repositories")
    return match[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_identity(source):
    from lorelab.component_sync import clean_source

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from repository import fingerprint

        return clean_source(source), fingerprint(source), digest(source / "components.lock.json")
    finally:
        sys.path.pop(0)


def publish(receipt, plugin_dir, product_notes, soota_notes, source=None):
    if receipt.get("ok") is not True or receipt.get("executed") is not True:
        raise ValueError("publish requires an executed, verified paired-tag receipt")
    commit, identity, lock_hash = source_identity(source or Path(__file__).resolve().parents[1])
    if commit != receipt["lorelab"]["commit"]:
        raise ValueError("plugin source commit differs from the paired-tag receipt")
    plugins = list(plugin_dir.glob(f"lorelab-plugin-{receipt['versions']['lorelab']}-*.zip"))
    if len(plugins) != 1:
        raise ValueError("expected exactly one plugin matching the LoreLab version")
    plugin = plugins[0]
    expected_name = f"lorelab-plugin-{receipt['versions']['lorelab']}-{identity}.zip"
    if plugin.name != expected_name:
        raise ValueError("plugin filename does not match the released source identity")
    with zipfile.ZipFile(plugin) as archive:
        binding = json.loads(archive.read("lorelab/lorelab-binding.json"))
    if (binding.get("source_fingerprint") != identity or binding.get("components_lock_sha256") != lock_hash
            or binding.get("version") != receipt["versions"]["lorelab"]):
        raise ValueError("plugin binding does not match the released source")
    checksum = plugin.with_name(plugin.name + ".sha256")
    if checksum.read_text(encoding="utf-8").split() != [digest(plugin), plugin.name]:
        raise ValueError("plugin checksum mismatch")
    planned = []
    for name, notes, assets in (("soota", soota_notes, []), ("lorelab", product_notes, [plugin, checksum])):
        item = receipt[name]
        repo, tag = github_repository(item["repository"]), item["tag"]
        if tag != "v" + receipt["versions"][name] or not re.fullmatch(r"[0-9a-f]{40,64}", item["commit"]):
            raise ValueError("invalid paired-tag receipt")
        if not notes or not notes.strip():
            raise ValueError("reviewed release notes are required for both repositories")
        commit = json.loads(checked("api", f"repos/{repo}/commits/{tag}"))["sha"]
        if commit != item["commit"]:
            raise ValueError(f"{repo}: tag changed after the Git release receipt")
        title = ("Soota" if name == "soota" else "LoreLab") + " " + tag
        existing = lookup(repo, tag)
        if existing and (existing["name"] != title or existing["body"].strip() != notes.strip()
                         or existing["prerelease"]):
            raise ValueError(f"{repo}: existing release differs from the reviewed notes; refusing replacement")
        if name == "lorelab" and existing:
            expected = {p.name for p in assets}
            if any(a["name"].startswith("lorelab-plugin-") and a["name"] not in expected for a in existing["assets"]):
                raise ValueError(f"{repo}: this version already contains a different plugin; prepare a new version")
        planned.append((repo, tag, title, notes, assets, existing))
    results = []
    with tempfile.TemporaryDirectory(prefix="lorelab-github-release-") as temporary:
        base = Path(temporary)
        for index, (repo, tag, title, notes, assets, existing) in enumerate(planned):
            notes_file = base / f"notes-{index}.md"
            notes_file.write_text(notes, encoding="utf-8")
            if existing is None:
                checked("release", "create", tag, "--repo", repo, "--verify-tag", "--draft",
                        "--title", title, "--notes-file", notes_file)
                existing = lookup(repo, tag)
                if existing is None:
                    raise RuntimeError("created release could not be read back")
            names = {asset["name"] for asset in existing["assets"]}
            for asset in assets:
                if asset.name in names:
                    download = base / f"download-{index}-{asset.name}"
                    download.mkdir()
                    checked("release", "download", tag, "--repo", repo, "--pattern", asset.name, "--dir", download)
                    if digest(download / asset.name) != digest(asset):
                        raise ValueError(f"{repo}: published asset differs; refusing overwrite: {asset.name}")
                else:
                    checked("release", "upload", tag, asset, "--repo", repo)
            if existing["draft"]:
                checked("release", "edit", tag, "--repo", repo, "--draft=false")
            final = lookup(repo, tag)
            if not final or final["draft"] or not {a.name for a in assets} <= {a["name"] for a in final["assets"]}:
                raise RuntimeError(f"{repo}: release readback incomplete; rerun the same reviewed release")
            results.append({"repository": repo, "tag": tag, "url": final["html_url"]})
    return {"ok": True, "releases": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--plugin-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(publish(json.loads(args.receipt.read_text(encoding="utf-8")), args.plugin_dir,
                             os.environ.get("PRODUCT_NOTES"), os.environ.get("SOOTA_NOTES"), args.source), indent=2))
