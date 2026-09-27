[English](README.md) | **中文**

# Mubu CLI

在终端管理幕布文档、编辑节点、导出内容。

本项目 Fork 自 [liuboacean/mubu-integration](https://github.com/liuboacean/mubu-integration)，保留原有文档管理和导入导出能力，新增节点编辑和桌面登录复用。

**项目版本：`1.4.0`（待发布）** · [已发布版本](https://github.com/0xTotoroX/mubu-cli/releases)。本页仅列已发布的功能。

## 功能对比

| 功能 | 官方 MCP | 原项目 | 本 Fork |
| --- | --- | --- | --- |
| 创建、读取文档，浏览目录，创建文件夹及移动 | 支持 | 支持 | 保留 |
| 搜索文档和文件夹 | 关键词搜索 | 按名称搜索 | 保留 |
| 重命名、删除、整篇保存 | 未列出 | 支持 | 保留 |
| Markdown 单篇/批量导出、OPML/FreeMind 导出 | 未列出 | 支持 | 保留 |
| 查询昵称和会员到期时间 | 支持 | 无专用命令 | 无专用命令 |
| 登录方式 | OAuth / 官方 Token | 密码 / JWT | 增加复用桌面登录 |
| 按节点读取、修改、新增子节点、删除子树 | 未列出 | 无专用命令 | **已发布** |
| 节点编辑预览、版本检查、写入后核验 | 未列出 | 无统一流程 | **已发布** |

原项目基线：[f2f0e53](https://github.com/liuboacean/mubu-integration/commit/f2f0e53af66447970a1f2664a10bfbbea3f1d406)。官方能力依据 [MCP 帮助文档](https://mubu.com/help/124)（2026-09-27）；“未列出”不代表确认不支持，未做登录后的工具清单验收。

## 快速开始

需要 Python 3.9+，无需另外安装原项目。

```sh
git clone https://github.com/0xTotoroX/mubu-cli.git
cd mubu-cli
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 先在幕布桌面端登录，再读取文档节点
.venv/bin/python scripts/mubu_api.py --auth desktop nodes DOC_ID

# 预览节点修改；确认后加 --execute 与 --expect-version VERSION 执行
.venv/bin/python scripts/mubu_api.py --auth desktop node-update DOC_ID \
  --node-id NODE_ID --text '新的内容'
```

## 使用说明

- 本项目使用幕布非官方接口，不接入官方 MCP；不提供多人协作或自动双向同步。
- 节点写入默认预览。普通 `node-update --text` 会将所选字段替换为纯文本；不要同时在其他客户端编辑目标文档。
- 桌面登录复用已在 macOS App Store 版验证；Windows/Linux 尚未实机验收。

[节点编辑用法](https://github.com/0xTotoroX/mubu-cli/blob/totoro-v1.4.0-alpha.1/docs/node-editing.md) · [版本说明](https://github.com/0xTotoroX/mubu-cli/releases/tag/totoro-v1.4.0-alpha.1)

## 来源与上游文档

- **Fork 基础：**[mubu-integration](https://github.com/liuboacean/mubu-integration)，复用文档管理、转换器和请求层，沿用 MIT 许可。
- **实现参考：**[CLI-Anything 幕布实现](https://github.com/HKUDS/CLI-Anything/blob/main/mubu/agent-harness/mubu_probe.py)的桌面会话读取与节点协议。新增模块独立实现。
- **方案比较：**[OpenCLI](https://github.com/jackwener/opencli) 与官方 MCP，仅作比较，未集成。

根目录 README 保留上游原文，与本页分开维护：[中文原文](../README.zh-CN.md) · [English](../README.md) · [同步维护说明](../docs/fork-maintenance.md#readme-维护)。
