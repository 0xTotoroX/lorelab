# settings/

> L2 | 父级: ../AGENTS.md

- `SettingsApp.tsx`：完整侧栏、四分类、主题、视图、草稿差异与保存保护。
- `model.ts`：合成服务/配置/任务数据、字段校验与配置差异。
- `use-settings.ts`：共享会话状态、模拟测试/任务/诊断与日志。
- `Services.tsx`：服务列表、连接状态与参数编辑器。
- `ConfigSections.tsx`：费用、来源优先级、存储与导出分组。
- `DiagnosticWorkspace.tsx`：复用配置分组的诊断页面与行内详情。
- `Diagnostics.tsx`：任务、重试反馈与日志筛选。
- `FlowMap.tsx`：关系图节点交互、Canvas动画和动效生命周期。
- `flow-geometry.ts`：SVG、Canvas与节点共用的响应式几何。
- `settings.css`：共享语义控件与基础调色板。
- `layouts.css`：配置分组、列表、诊断与保存区的基础布局。
- `responsive.css`：共享控件和页面的响应式基础规则。
- `flow.css`：关系图、节点与轨道基础样式。
- `obsidian-tokens.css`：当前灰紫深浅主题、语义颜色、字体和控件变量。
- `unified.css`：完整侧栏、品牌 SVG 蒙版、三列布局和控件样式，无内容横向分隔线。
- `diagnostic-groups.css`：诊断分组对齐、行内详情与手机重排。

只有当前三列布局。切换分类必须经过未保存保护；切换主题或连接视图不丢草稿。来源启用、测试成功和配置保存不能合并为一个状态。动画不执行真实采集或交付，减少动效/暂停/离屏/后台时停止。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
