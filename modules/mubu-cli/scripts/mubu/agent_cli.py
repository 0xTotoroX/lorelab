"""Agent 调用契约：无交互、JSON 结果、稳定错误码；保留原 CLI 默认行为。

[INPUT]: CLI 状态与请求错误。
[OUTPUT]: 结构化结果、错误码和写入恢复指引。
[POS]: 命令行 Agent 契约；node-import 纳入写命令集合。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import argparse
import json
import sys

from mubu import __version__
from mubu.config import DesktopDataAccessError, MubuError

WRITE_COMMANDS = {'mkdir', 'create', 'save', 'delete', 'restore', 'purge', 'move', 'rename',
                  'node-update', 'node-create', 'node-delete', 'node-move', 'node-link', 'node-import',
                  'image-upload', 'attachment-upload'}


class AgentError(MubuError):
    def __init__(self, code, message, next_action='fix_arguments'):
        super().__init__(message)
        self.code, self.next_action = code, next_action


def requested():
    # -- 后是位置参数，不能把文档正文中的 --agent 误认为全局选项。
    args = sys.argv[1:]
    return '--agent' in args[:args.index('--') if '--' in args else len(args)]


def emit(command, data=None, *, status='ok', error=None):
    result = {'schema_version': 1, 'cli_version': __version__, 'command': command,
              'ok': error is None, 'status': status, 'data': data}
    if error is not None:
        result['error'] = error
    print(json.dumps(result, ensure_ascii=False, indent=2))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        if requested():
            emit(None, status='error', error={'code': 'INVALID_ARGUMENTS', 'message': message,
                 'retryable': False, 'next_action': 'fix_arguments'})
            self.exit(2)
        super().error(message)

    def print_help(self, file=None):
        if requested():
            emit(None, {'help': self.format_help()}, status='help')
        else:
            super().print_help(file)


def error_info(error, command):
    if isinstance(error, AgentError):
        return error.code, str(error), error.next_action
    if isinstance(error, DesktopDataAccessError):
        return 'DESKTOP_ACCESS_DENIED', str(error), 'grant_desktop_data_access'
    body = error.body if isinstance(error, MubuError) and isinstance(error.body, dict) else {}
    status = getattr(error, 'status_code', None)
    message = str(error).lower()
    if status == 401 or body.get('code') == 10007 or any(word in message for word in
            ('登录失效', '重新登录', '先登录', '登录记录', 'mubu_phone', 'login expired')):
        return 'AUTH_REQUIRED', '登录不可用；请配置凭据或在幕布桌面端重新登录', 'authenticate'
    if command in WRITE_COMMANDS and not isinstance(error, (ValueError, OSError)):
        # 旧接口没有操作日志，无法判断请求是否已经到达服务器；保守禁止重试。
        return 'WRITE_UNCONFIRMED', '写入未确认；先读取目标内容，禁止直接重试', 'inspect_remote_state'
    if isinstance(error, (ValueError, OSError)):
        return 'LOCAL_INPUT_ERROR', '本地输入或文件不可用；请检查参数、路径和文件格式', 'fix_input'
    if isinstance(error, MubuError):
        return 'REQUEST_FAILED', '请求未完成；请检查鉴权、权限、网络或响应格式', 'inspect_request'
    return 'INTERNAL_ERROR', '命令异常结束；没有自动重试', 'inspect_failure'


def fail(error, command):
    code, message, action = error_info(error, command)
    emit(command, status='uncertain' if code == 'WRITE_UNCONFIRMED' else 'error', error={
        'code': code, 'message': message, 'retryable': False, 'next_action': action})


def write_failure(error, command):
    status = error.result['status']
    codes = {'conflict': ('VERSION_CONFLICT', 'read_and_preview'),
             'rejected': ('WRITE_REJECTED', 'inspect_rejection'),
             'uncertain': ('WRITE_UNCERTAIN', 'inspect_operation')}
    code, action = codes.get(status, ('WRITE_UNCERTAIN', 'inspect_operation'))
    emit(command, error.result, status=status, error={
        'code': code, 'message': error.result['message'],
        'retryable': False, 'next_action': action})
