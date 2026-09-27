"""保留现有标记的文字替换、追加及安全链接。"""

import html
from html.parser import HTMLParser
from urllib.parse import urlsplit

from mubu.config import MubuError


class TextRuns(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.offsets = [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.runs = []
        self.feed(source)

    def handle_data(self, data):
        line, column = self.getpos()
        start = self.offsets[line - 1] + column
        end = self.source.find('<', start)
        self.runs.append((start, len(self.source) if end < 0 else end, data))


def replace_text(source, old, new):
    """只替换唯一且位于同一格式片段的文本；拒绝跨标记或多义匹配。"""
    if not old:
        raise MubuError("--replace 不能为空")
    runs = TextRuns(source).runs
    if sum(text.count(old) for _, _, text in runs) != 1:
        raise MubuError("替换文本必须在单个格式片段中唯一匹配；跨格式或重复匹配未写入")
    for start, end, text in runs:
        if old in text:
            updated = html.escape(text.replace(old, new))
            return source[:start] + updated + source[end:]
    raise MubuError("未找到替换内容")


def append_html(source, fragment):
    return source + ('<span>\n</span>' if source else '') + fragment


def link_html(url, label):
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in {'http', 'https', 'obsidian'} and bool(parsed.netloc)
    except ValueError:
        valid = False
    if not valid or any(ord(char) < 32 for char in url):
        raise MubuError("链接仅接受完整的 http/https/obsidian URL")
    return '<a href="' + html.escape(url, quote=True) + '">' + html.escape(label) + '</a>'
