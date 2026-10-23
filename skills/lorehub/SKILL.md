---
name: lorehub
description: 兼容旧 LoreHub 名称。产品安装和组件维护使用 LoreLab Skill；采集、文章整理、学习大纲与交付恢复使用 Soota Skill。旧命令和冻结任务继续可用。
---

# LoreHub 兼容入口

统一产品现名 LoreLab。安装、检查与组件维护读取 [LoreLab Skill](../lorelab/SKILL.md)；知识提炼、学习大纲和交付恢复直接读取 [Soota Skill](../../modules/soota/skills/soota/SKILL.md)。旧 `lorehub` 命令转到同一份实现，不维护第二套流程。

用 `lorehub skills list` 或 `lorelab skills list` 定位安装的真实 source；按原任务绝对路径恢复，不搬动状态、不改写冻结 schema，也不扩大旧删除授权。旧[流程文档入口](../../docs/workflow.md)继续提供导航。兼容细节见 [Soota 契约](../../modules/soota/docs/knowledge.md#配置独立组件与兼容入口)。
