# 单来源内容处理与导出

`lorelab content` 接收链接、本地文件或已有内容包，复用 Soota 获取原文，再校验、保存 Agent 提交的分析、笔记、文章或大纲。内容理解与写作由 Agent 完成，CLI 不调用语言模型。普通聊天总结可以直接使用已有正文，不要求创建任务或写入知识库。

## 选择入口和目标

| 请求 | 入口 |
| --- | --- |
| 获取视频、音频、字幕、原文、图片或数据 | `soota ingest`；恢复使用 `soota jobs resume` |
| 单来源分析、笔记、阅读文章或大纲 | `lorelab content ingest`；提交使用 `lorelab content resume` |
| 对已有包校验并保存分析结果 | `lorelab content render` |
| 将已有包导出到明确目录 | `lorelab content export` |
| 将选定 Cubox 收藏或内容包组织成知识文章并核对交付 | `lorelab knowledge`，见[知识流程](knowledge.md) |
| 从明确选定的已有文章制作幕布学习树 | `lorelab study`，见[独立学习任务](knowledge.md#独立学习任务-study) |

Soota 新采集任务只接受 `video/audio/transcript/context/markdown/images/data`。`markdown` 保存源正文，不意味着语义改写。`note/article/analysis/outline` 由 LoreLab content 处理；它也可组合采集目标，例如 `context,note`。知识归档、幕布交付和来源清理都不是单来源分析的隐含步骤。

## 获取来源并接续写作

以下路径与 ID 均为占位符，执行时使用实际输入及返回值。

```sh
lorelab content ingest "https://example.org/article" --want context,note
lorelab content ingest /path/to/source-bundle/manifest.json --want analysis
lorelab content resume JOB --analysis /path/to/submission.json
```

`ingest [INPUT]` 的来源获取复用 Soota 的输入解析、Provider、预算、缓存和产物校验；不另建下载或正文解析流程。已有内容包可复用符合请求的原文与媒体。采集条件、输入清单和费用规则见 [Soota 采集任务](../modules/soota/docs/tasks.md)。本地 TXT 是正文输入，`--inputs-file` 是链接或路径清单；粘贴的正文先原样保存为独立 TXT，不把它当成分享链接清单。

原文就绪后，语义任务以 `waiting_analysis` 等待 Agent。内容包里的 `analysis-request.json` 给出所选目标、真实 task/item 身份、当前 context 指纹、提交 schema 和接续信息。Agent 读取实际 context，按本次请求写作，提交后由 CLI 校验与登记产物。不能以交接文件存在、来源非空或文件 hash 通过代替写作完成和来源完整性判断。

`resume` 使用原 JOB，保留 `task_id/item_id`、来源证据、原路径、费用预留和已有有效产物；恢复参数中的费用、条数和页数仍表示累计总上限，不清零重开。一个 JSON 文件可提交单项结果，多个条目的提交可放在同一目录。并行草拟使用独立文件，由一个协调者接续同一任务，避免并发写同一 JOB。知识批次冻结后由 `knowledge submit` 接续，不独立替换它的来源分析。已有 `analysis-request.json` 的 `task_id`、`item_id`、`context_fingerprint` 和 `requested_outputs` 一致时逐字节保留，不因命令改名重写交接，旧冻结 hash 保持不变。旧交接的 resume 提示可能仍是 Soota 命令；直接使用正式 content 入口，不手工修改该文件。

## Agent 提交契约

v2 内容包使用 `AnalysisSubmission`，以实际 `analysis-request.json` 的 schema 为准，不另造包装字段。`Analysis`、`KeyPoint`、`Chapter` 定义及全部语义渲染实现位于 LoreLab 的 `src/lorelab/content/`；旧 v1 Analysis 的 schema 位于 LoreLab 主仓 `schemas/analysis.v1.json`，不再位于 Soota 组件。

| 字段 | 用途与约束 |
| --- | --- |
| `task_id`、`item_id` | 接续任务时必须与当前交接一致；不能移用另一任务的身份 |
| `context_fingerprint` | 当前 context 的字节 SHA-256；来源改变后必须重新阅读和写作 |
| `analysis` | 结构化 Analysis 对象，含 `summary`，可含带证据的 `key_points`、`chapters`、`tags`、`language` |
| `note_markdown` | 用户请求的笔记正文 |
| `article_markdown` | 用户请求的详细阅读文章正文 |
| `outline_markdown` | 用户请求的独立大纲正文 |

至少提供一项语义输出，只填写本次所需产物。引用当前来源真实存在的 `seg-*` 或 `para-*` 证据 ID；结构化要点使用 `key_points[].evidence`，Markdown 可链接 `context.md#para-ID` 或 `transcript.md#seg-ID`。渲染检查正文指纹和引用的证据，任务恢复额外检查 task/item 身份。CLI 的格式、身份和证据检查不能证明全文覆盖、结论正确或分类合理，这些由 Agent 实读审阅。

摘要或分析直接使用 context，不先写完整文章；详细阅读文章仅在明确要求时生成。自定义写作结构不必挤进摘要 schema，可以选用对应 Markdown 字段。不要强加“三点结论”、固定长度或额外的一份文章。语义取舍和示例见 [LoreLab 内容处理 Skill 引用](../skills/lorelab/references/content.md)。

## 渲染与已有文件

```sh
lorelab content render --bundle /path/to/bundle --analysis /path/to/submission.json
# 已授权替换该包既有语义产物时：
lorelab content render --bundle /path/to/bundle --analysis /path/to/submission.json --force
```

v2 保存所请求的 `analysis.md`、`note.md`、`outline.md` 或 `content.md`，并登记 `analysis.json` 和 manifest；没有请求的产物不以空文件冒充。旧 v1 包继续接受原 Analysis JSON，将阅读结果写到 `content.md`，不需要改写历史包格式。

显式 render 不重写 context、字幕或过滤前原文。覆盖已有语义产物需要明确 `--force`，无效提交不能覆盖。任务接续可复用相同的已提交结果；有未完成任务时优先使用 `content resume --analysis`，独立 render 不代表原任务记录或交付已完成。

采集保留已有语义产物；来源变化可将其标记过时，但不会自动重写。Soota 的旧 `TaskSpec` 语义词/目标字段、`AnalysisManifest` 状态（含 `AnalysisStatus`）及历史产物名只用于数据兼容，没有对应的语义生成、校验或导出实现。

## 导出与知识分类

```sh
lorelab content export --bundle /path/to/bundle --destination /path/to/archive
lorelab content export --bundle /path/to/bundle --vault /path/to/KnowledgeVault --subdir 收件箱
```

选择显式 `--destination`，或 `--vault` 与 `--subdir` 组成的目的地。即使只导出 context 原文包，导出也归 LoreLab content。Soota 的 `--output` / `SOOTA_OUTPUT_DIR` 只指定采集包保存位置，不执行知识库交付。

导出按来源生成稳定目录，保留包内相对附件链接，以历史文件名 `.soota-export.json` 记录受管文件 SHA。已有未登记文件或人工修改导致冲突时保留原文件；采集或渲染的 `--force` 不绕过导出保护。整包复制不等于按主题写成文章，也不等于完成分类、查重或知识合并。

分类由 Agent 先读取指定目的地的 `AGENTS.md`、所引用的本地规则及相关既有笔记，再判断新增、补充、重复或分歧。需要合并已有笔记时，在当前授权内单独审阅修改并回读，保全人工内容，不为避开冲突另存重复主题。CLI 不解释个人规则、不推断分类，也不重组知识库。`knowledge publish` 只接受新路径或字节完全相同的已有文件，不会自动覆盖、合并或更新旧笔记。

## 旧入口与恢复

| 旧入口 | 兼容行为 |
| --- | --- |
| `soota ingest` 带语义目标或 `--destination/--vault/--subdir` | 隐藏兼容桥转交 `lorelab content ingest` |
| `soota jobs resume` 接续旧语义或交付任务 | 隐藏兼容桥转交 `lorelab content resume` |
| `soota render` | 隐藏兼容桥转交 `lorelab content render` |
| `soota knowledge/study` | 隐藏兼容桥转交 `lorelab knowledge/study` |

新操作使用 LoreLab 的正式入口。旧内容 ingest/resume/render 仅动态调用同一 Python 环境中的 LoreLab，不从 PATH 另选可执行文件。独立 Soota 该环境未安装 LoreLab 时，旧语义或交付入口必须明确报告需要安装，并在修改任务、预算或产物前停止。受管安装缺少绑定入口时不替换成其他产品版本。原有任务按原 ID/路径继续，source 证据、预算、已保存产物及知识任务冻结与清理条件保持，不要求搬迁或重建。

采集和原文内容包独立运行，不依赖 LoreLab。兼容字段可读取，不构成在 Soota 重建语义执行的理由。
