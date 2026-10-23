# 知识流程入口

文章整理、学习大纲、交付核对与授权清理的唯一实现和文档主源归 LoreLab。本文保留旧链接入口；完整字段、状态和恢复规则见 [LoreLab 知识流程](knowledge.md)。

| 产品命令 | 正式命令 |
| --- | --- |
| `lorelab init` | `lorelab knowledge init` |
| `lorelab batch prepare/submit/publish/verify/cleanup/status` | `lorelab knowledge prepare/submit/publish/verify/cleanup/status` |
| `lorelab study prepare/submit/publish/verify/status` | `lorelab study prepare/submit/publish/verify/status` |

旧 `lorehub` 命令和 Python 兼容入口已移除；旧任务继续使用原 JOB 路径，由表中命令读取，不需要改写任务或恢复旧入口。

## 默认文章流程

见[文章流程](knowledge.md#默认文章流程)。普通 ingest 仍默认只保存原文 context。

## Python 接口

见 [LoreLab 知识模块接口](knowledge.md#python-接口)。唯一实现在 `lorelab.knowledge`。

## 交付选择与旧任务

见[交付选择与旧任务](knowledge.md#交付选择与旧任务)及[配置兼容](knowledge.md#配置独立组件与兼容入口)。已有任务按原绝对路径继续，冻结 schema 和旧删除条件不变。

## prepare 与补抓

见 [Cubox 输入与补抓](knowledge.md#cubox-输入与补抓)；普通媒体先摄取为[现有内容包输入](knowledge.md#现有内容包输入)。

## Agent 审阅 schema

见[实际审阅 schema](knowledge.md#agent-审阅-schema)。以任务返回模板为准。

## 发布、核验和恢复

见[发布、核验和恢复](knowledge.md#发布核验和恢复)。沿用旧共享写锁，不重复导入不确定的云端写入。

## 清理门禁

见[清理门禁](knowledge.md#清理门禁)。内容包来源不执行 Cubox 或源文件删除。

## 独立学习任务 study

见[独立学习任务](knowledge.md#独立学习任务-study)。仅在明确请求时从选定文章生成学习树。

## 模块与验证

见 [LoreLab 模块职责与验证边界](knowledge.md#模块与验证)。产品安装和组件维护另见[安装说明](installation.md)与[组件说明](components.md)。
