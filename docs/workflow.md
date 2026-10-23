# 知识流程兼容入口

文章整理、学习大纲、交付核对与授权清理的唯一实现和文档主源已归入 Soota。本文保留旧链接入口；完整字段、状态和恢复规则见 [Soota 知识流程](../modules/soota/docs/knowledge.md)。

| 产品命令（旧 `lorehub` 同样保留） | Soota 命令 |
| --- | --- |
| `lorelab init` | `soota knowledge init` |
| `lorelab batch prepare/submit/publish/verify/cleanup/status` | `soota knowledge prepare/submit/publish/verify/cleanup/status` |
| `lorelab study prepare/submit/publish/verify/status` | `soota study prepare/submit/publish/verify/status` |

## 默认文章流程

见[文章流程](../modules/soota/docs/knowledge.md#默认文章流程)。普通 ingest 仍默认只保存原文 context。

## Python 接口

见 [Soota 知识模块接口](../modules/soota/docs/knowledge.md#python-接口)。产品只路由同一套实现。

## 交付选择与旧任务

见[交付选择与旧任务](../modules/soota/docs/knowledge.md#交付选择与旧任务)及[配置兼容](../modules/soota/docs/knowledge.md#配置独立组件与兼容入口)。已有任务按原绝对路径继续，冻结 schema 和旧删除条件不变。

## prepare 与补抓

见 [Cubox 输入与补抓](../modules/soota/docs/knowledge.md#cubox-输入与补抓)；普通媒体先摄取为[现有内容包输入](../modules/soota/docs/knowledge.md#现有内容包输入)。

## Agent 审阅 schema

见[实际审阅 schema](../modules/soota/docs/knowledge.md#agent-审阅-schema)。以任务返回模板为准。

## 发布、核验和恢复

见[发布、核验和恢复](../modules/soota/docs/knowledge.md#发布核验和恢复)。沿用旧共享写锁，不重复导入不确定的云端写入。

## 清理门禁

见[清理门禁](../modules/soota/docs/knowledge.md#清理门禁)。内容包来源不执行 Cubox 或源文件删除。

## 独立学习任务 study

见[独立学习任务](../modules/soota/docs/knowledge.md#独立学习任务-study)。仅在明确请求时从选定文章生成学习树。

## 模块与验证

见 [Soota 模块职责与验证边界](../modules/soota/docs/knowledge.md#模块与验证)。产品安装和组件维护另见[安装说明](installation.md)与[组件说明](components.md)。
