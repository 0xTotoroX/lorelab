"""[INPUT]: Markdown 正文和备用文件名。
[OUTPUT]: 忽略属性与代码块后的 H1 标题，缺少标题时用文件名。
[POS]: knowledge 图书馆与 study 共用的确定性标题解析。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import re
from pathlib import Path

from .workflow_state import require


def title(markdown: str, path: Path) -> str:
    """读取 H1（ATX/Setext）；忽略 front matter 和围栏代码，不生成语义内容。"""
    lines = markdown.lstrip("\ufeff").splitlines()
    front_matter = bool(lines and lines[0] == "---" and any(line in {"---", "..."} for line in lines[1:]))
    fence = None
    paragraph = []
    for index, line in enumerate(lines):
        if front_matter:
            if index and line in {"---", "..."}:
                front_matter = False
            continue
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*", line):
                fence = None
            continue
        opening = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if opening:
            fence = opening[1]
            paragraph = []
            continue
        heading = re.match(r" {0,3}#[ \t]+(.+)", line)
        if heading:
            title = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", heading[1]).strip()
            if title:
                return title
        if paragraph and re.fullmatch(r" {0,3}=+[ \t]*", line):
            return " ".join(paragraph)
        if line.strip() and not re.match(r"(?: {4}|\t| {0,3}[#>\-*+])", line):
            paragraph.append(line.strip())
        else:
            paragraph = []
    title = path.stem.strip()
    require(bool(title), "文章标题和文件名均为空。")
    return title

