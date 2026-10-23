# cubox-cli

[License: MIT](https://opensource.org/licenses/MIT)
[Go Version](https://go.dev/)

[English](./README.md) | [中文版](./README.zh.md)

LoreHub 维护的 Cubox CLI 二次开发版。收藏、搜索、阅读，并借助 AI 使用你读过的内容。让你的个人阅读记忆，真正被用起来。

[安装](#安装) · [认证](#认证) · [命令](#命令) · [AI Agent](#ai-agent-快速开始) · [示例](#示例) · [开发](#开发)

## 功能


| 类别  | 能力                                 |
| --- | ---------------------------------- |
| 收藏夹 | 列出和浏览文件夹                         |
| 标签  | 列出和浏览标签层级；重命名、批量删除、合并标签              |
| 卡片  | 按收藏夹、标签、星标/已读/标注/归档状态、关键词、精确网址、时间范围过滤和搜索卡片 |
| RAG  | 自然语言语义搜索（基于意图的智能检索）                 |
| 详情  | 查看卡片全文（Markdown）、标注、AI 洞察（摘要 + 问答） |
| 保存  | 保存网页，支持标题/描述，批量 JSON 输入            |
| 更新  | 星标/取消星标、已读/未读、移动收藏夹、管理标签              |
| 归档  | 批量归档收藏卡片，或恢复（取消归档）到指定收藏夹           |
| 删除  | 按 ID 删除收藏卡片，支持 dry-run 预览          |
| 标注  | 列出和搜索所有卡片的标注，包含高亮和高亮笔记                     |


## 安装

### 前置要求

- LoreHub 发行包使用产品安装器，无需单独安装 Node.js 或 Go。
- 独立源码构建需要 Go 1.23+；只有使用本地 npm 包装器时才需要 Node.js 16+。

### 快速开始（人类用户）

> **AI Agent 请跳转：** [AI Agent 快速开始](#ai-agent-快速开始)

#### 安装

优先使用 LoreHub 产品安装器，成套安装匹配的 CLI 与 Skill。独立导出的组件可在其目录中安装：

```bash
cd /path/to/exported-cubox-cli
make install
```

也可在同一目录执行 `npm install -g .`，它会构建随包 Go 源码。把完整的 `skills/cubox` 目录注册到 Agent 的 Skill 目录，保留引用文件，不只复制 `SKILL.md`。本组件是私有源码包，更新同样从 LoreHub 导出和构建，不安装公共 npm 包或原作者发行版。

#### 登录

```bash
cubox-cli auth login
```

CLI 会引导你完成以下步骤：

1. **登录 Cubox 网页版** — 根据您的 Cubox 所在地区，打开对应的扩展设置页面：
   - .pro 用户：[https://cubox.pro/web/settings/extensions](https://cubox.pro/web/settings/extensions)
   - .cc 国际用户：[https://cubox.cc/web/settings/extensions](https://cubox.cc/web/settings/extensions)
2. **启用 API 扩展** — 在扩展中心页面找到「API 扩展」，启用并复制链接（如 `https://cubox.pro/c/api/save/abcd12345`）。
3. **粘贴链接** — CLI 会自动提取 token 和服务器信息。

#### 开始使用

```bash
# 列出收藏夹
cubox-cli folder list

# 列出标签
cubox-cli tag list

# 浏览最近的卡片
cubox-cli card list --limit 5 -o pretty

# 阅读一篇文章
cubox-cli card detail --id CARD_ID
```

### AI Agent 快速开始

> 以下步骤适用于 AI Agent 帮助用户设置 cubox-cli。

**步骤 1：安装**

使用 LoreHub 安装器与 `lorehub skills list`，或遵照上面的独立源码安装方式；CLI 和完整 Skill 来自同一导出版本。

**步骤 2：认证**

引导用户获取 API 链接：

1. 请根据您的 Cubox 所在地区，登录对应的网页版：
   - .pro 用户：`https://cubox.pro/web/settings/extensions`
   - .cc 国际用户：`https://cubox.cc/web/settings/extensions`
2. 在扩展中心页面找到「API 扩展」，启用并复制链接（如 `https://cubox.pro/c/api/save/abcd12345`）。

Agent **不要**让用户把 token 粘贴到对话里，也不要把 token 拼接进命令行 argv。请指引用户自行在终端运行以下任意一种：

```bash
# 交互式（推荐给人类用户）
cubox-cli auth login

# Agent / CI 无落盘模式 —— token 仅存在于 shell 环境变量中
export CUBOX_SERVER=cubox.pro
export CUBOX_TOKEN=... # 也可以是完整的 API 链接 URL
cubox-cli folder list

# 非交互式持久登录 —— token 通过 stdin 传入，不进入 argv / ps / history
printf '%s' "$TOKEN" | cubox-cli auth login --server cubox.pro --token-stdin
```

旧式 `--token TOKEN` 参数仍然可用，但会把 token 泄漏到 shell history 和 `ps`，仅建议在受控环境使用。

**步骤 3：验证**

```bash
cubox-cli auth status
```

**步骤 4：使用**

```bash
cubox-cli folder list
cubox-cli card list --limit 10
```

## 认证


| 命令                                                                               | 说明                                                  |
| ------------------------------------------------------------------------------- | --------------------------------------------------- |
| `cubox-cli auth login`                                                          | 交互式登录（选择服务器 + 输入 token）                             |
| `printf '%s' "$TOKEN" \| cubox-cli auth login --server cubox.pro --token-stdin` | 从 stdin 读取 token 的非交互式登录（推荐 Agent 使用）                |
| `CUBOX_SERVER=cubox.pro CUBOX_TOKEN=... cubox-cli ...`                          | 纯环境变量模式，不落盘（推荐 CI / 沙箱场景）                           |
| `cubox-cli auth login --server cubox.pro --token TOKEN`                         | 旧式 argv 写法，会泄漏到 shell history / ps，尽量避免             |
| `cubox-cli auth status`                                                         | 显示当前服务器、脱敏 token、连接测试                               |
| `cubox-cli auth logout`                                                         | 删除已保存的凭证                                            |


凭证保存在 `~/.config/cubox-cli/config.json`。设置 `CUBOX_TOKEN` / `CUBOX_SERVER` 环境变量会覆盖配置文件；当配置文件不存在时，单独使用这两个环境变量即可登录。

## 命令

### 输出格式

所有命令都接受 `-o` / `--output` 参数。大多数数据类命令会按该参数输出：


| 参数          | 说明                   |
| ----------- | -------------------- |
| `-o json`   | 紧凑 JSON（默认，适合 Agent） |
| `-o pretty` | 格式化 JSON             |
| `-o text`   | 人类可读的文本/树形输出         |


注意：`save`、`update` 和部分 `auth` 成功路径目前即使选择 `-o json` 也会输出纯文本。

### `cubox-cli version`

显示当前安装的 CLI 版本。

```bash
cubox-cli version
```

### `cubox-cli folder list`

列出所有收藏夹。

```bash
cubox-cli folder list
cubox-cli folder list -o text
```

**JSON 输出字段：** `id`, `nested_name`, `name`, `parent_id`, `uncategorized`

### `cubox-cli tag list`

列出所有标签。

```bash
cubox-cli tag list
cubox-cli tag list -o text
```

**JSON 输出字段：** `id`, `nested_name`, `name`, `parent_id`

### `cubox-cli tag update`

按 ID 重命名标签。新名称仅影响叶子段，嵌套的子标签会自动跟随到新路径下。

```bash
cubox-cli tag update --id TAG_ID --new-name NEW_NAME
```

| 参数                | 说明                                       |
| ----------------- | ---------------------------------------- |
| `--id ID`         | 要重命名的标签 ID（必填）                          |
| `--new-name NAME` | 新的叶子名称（必填；不能包含 `/`）                     |

### `cubox-cli tag move`

将现有标签移动到另一标签下，保留原标签 ID 和卡片关联。命令会检查目标、同名冲突及循环层级，并在执行后核对父标签。

```bash
cubox-cli tag move --id TAG_ID --parent PARENT_TAG_ID
```

`--id` 和 `--parent` 都使用 `tag list` 返回的标签 ID，均为必填。此命令使用 Cubox 客户端登录凭据，与 fork 的其他 web/app 命令相同。

### `cubox-cli tag topic`

根据卡片正文，按核心议题提炼 0～3 个主题。优先匹配 Cubox 中 `主题` 的直属子标签（已审核词表）；新概念先进入候选清单，由内容提炼，无需事先手写完整词表。已审核主题与新候选合计最多 3 个。文件夹只提供背景，不会被复制成标签层级。

```bash
export CUBOX_TOPIC_API_URL=https://你的模型服务/v1/chat/completions
export CUBOX_TOPIC_MODEL=模型名
# 远程模型服务还需在本机设置 CUBOX_TOPIC_API_KEY；不要把密钥放入命令参数或分享给 Agent。

cubox-cli tag topic --id CARD_ID          # 只预览
cubox-cli tag topic --id CARD_ID --apply  # 仅追加缺少的已审核主题标签
```

正文无法解析时，仅在描述足够充分的情况下最多建议 1 个主题；只有标题或证据不足时不打标。模型提出的新词只会出现在 `suggested_new_topics` 中，须人工审核后才可建标签。`--apply` 会重新核对词表、卡片与写入结果，保留 `来源`、`处理`、`skill`、`笔记` 等原有标签和文件夹。卡片正文与描述会发往所配置的模型接口；默认不写入 Cubox。

批量流程按“收集候选 → 审核词表 → 建立审核通过的标签 → 预览回填 → 明确执行”进行：

```bash
cubox-cli tag topic collect --id CARD1,CARD2 --out topic-plan.json
cubox-cli tag topic review --plan topic-plan.json --name MCP --decision approved
cubox-cli tag topic review --plan topic-plan.json --name "MCP工具" --decision merged --target MCP
cubox-cli tag topic review --plan topic-plan.json --name "过宽的词" --decision rejected

cubox-cli tag new --name 主题                   # 若尚无主题根标签
cubox-cli tag new --name MCP --parent 主题ID   # 仅创建审核通过的新词
cubox-cli tag topic backfill --plan topic-plan.json          # 只预览
cubox-cli tag topic backfill --plan topic-plan.json --apply  # 才追加标签
```

`collect` 逐帖读取正文，在本地计划文件中汇总候选词、涉及的卡片及理由，不修改 Cubox。手动路径下，`review` 只修改该文件；所有候选词都须标为 `approved`、`merged` 或 `rejected`，且通过或合并后的目标词须已存在于 `主题/*`，回填才会继续。合并词会提示模型使用审核后的目标词，拒绝词不会再次出现在候选输出中。回填会依据卡片**当前**内容重新判断，不直接照搬收集阶段的卡片建议；内容不足仍不打标。计划文件不保存完整正文，但包含卡片标题、ID 和模型理由；理由可能摘录正文，应妥善保管。批量写入没有事务；若 `--apply` 中途失败，先前成功的卡片不会自动回滚，命令会报告已验证成功的数量，并提示当前失败的卡片可能也发生了变化。

可选自动模式沿用同一份计划文件：

```bash
cubox-cli tag topic collect --id CARD1,CARD2 --out topic-plan.json
cubox-cli tag topic auto-review --plan topic-plan.json
cubox-cli tag topic backfill --plan topic-plan.json --auto          # 预览拟建标签和逐帖结果
cubox-cli tag topic backfill --plan topic-plan.json --auto --apply  # 建标签并追加到卡片
```

`auto-review` 会把候选词与现有审核词、其他候选词做严格近义合并。一个新词只有在**至少两篇不同卡片的充分正文**里获得模型确认，才自动批准；只出现一次、仅有描述、正文不足或模型不确定时保留为 `pending`。同一篇文章里的两个近义词也会合并为一个待定词，合并本身不等于批准。它只修改本地计划文件。`backfill --auto` 容许这些待定词继续留在清单；默认预览使用临时标签 ID，不写入 Cubox。`--auto --apply` 使用 Cubox App 登录凭据创建缺失的 `主题` 根标签和已批准的直属子标签，再基于当前正文重新判断并追加标签；现有标签和文件夹保留。建标签与批量回填没有事务，出错时查看返回的 `created`、`applied` 和失败信息后再处理。模型会读取候选卡片的正文摘录用于合并判断，真实语义准确度仍需实际模型验证。

### `cubox-cli tag delete`

按 ID 批量删除标签。被删除标签关联的卡片本身保留，仅解除标签关联。

```bash
cubox-cli tag delete --id TAG_ID[,ID2,...]
```

### `cubox-cli tag prune-empty`

针对已经空了的标签按名称或 ID 检查，默认只预览；`--apply` 才删除。必须同时没有普通卡片、归档卡片和子标签。`来源`、`处理`、`skill`、`笔记`、`主题` 这五个根标签受保护。

```bash
cubox-cli tag prune-empty --name PICSED          # 只预览
cubox-cli tag prune-empty --name PICSED --apply  # 再检查并删除
```

CLI 删卡时也会自动检查**本次被删卡片原来使用过的标签**，只清理删卡后变空的叶子标签；已审核的 `主题/*` 词表和 `处理/*` 流程标签会保留，不会遍历、删除其他已有空标签。Cubox 客户端内的删除操作不会触发 CLI；这类旧空标签用上述命令单独检查。

| 参数            | 说明                              |
| ------------- | ------------------------------- |
| `--id ID,...` | 要删除的标签 ID（逗号分隔，必填）            |

### `cubox-cli tag merge`

将一个或多个源标签合并到目标标签。源标签关联的卡片会重新挂到目标标签下，随后源标签被删除。

```bash
cubox-cli tag merge --source SRC_ID[,ID2,...] --target TARGET_ID
```

| 参数                | 说明                                |
| ----------------- | --------------------------------- |
| `--source ID,...` | 要合并的源标签 ID（逗号分隔，必填）             |
| `--target ID`     | 合并到的目标标签 ID（必填）                  |

### `cubox-cli card list`

过滤和搜索收藏卡片。支持关键词搜索、按精确网址查询（使用页码分页）和浏览模式（使用游标分页）。

```bash
cubox-cli card list [flags]
```


| 参数                  | 说明                                           |
| ------------------- | -------------------------------------------- |
| `--folder ID,...`   | 按收藏夹 ID 过滤                                   |
| `--tag ID,...`      | 按标签 ID 过滤                                    |
| `--starred`         | 仅星标卡片                                        |
| `--read`            | 仅已读卡片                                        |
| `--unread`          | 仅未读卡片                                        |
| `--annotated`       | 仅有标注的卡片                                      |
| `--archived`        | 仅归档卡片（默认仅返回未归档卡片）                              |
| `--keyword TEXT`    | 关键词搜索                                        |
| `--url URL`         | 按卡片网址精确匹配                                    |
| `--start-time TIME` | 按收藏开始时间过滤（如 `2026-01-01T00:00:00:000+08:00`） |
| `--end-time TIME`   | 按收藏结束时间过滤                                    |
| `--limit N`         | 每页数量（默认 50）                                  |
| `--last-id CARD_ID` | 浏览模式的游标分页（非搜索）                               |
| `--page N`          | 搜索模式的页码（从 1 开始，配合 `--keyword` 或 `--url` 使用） |
| `--all`             | 自动翻页获取全部结果                                   |


**分页规则：** 使用 `--keyword` 或 `--url` 时，用 `--page` 翻页；否则用 `--last-id` 游标分页。

### `cubox-cli card detail --id ID`

获取卡片完整详情，包含文章全文（Markdown）、作者、标注和 AI 洞察（摘要 + 问答）。

```bash
cubox-cli card detail --id 7247925101516031380
cubox-cli card detail --id 7247925101516031380 -o pretty
```

使用 `-o text` 仅输出 Markdown 内容。

### `cubox-cli card batch`（fork）

```bash
cubox-cli card batch --id CARD1,CARD2 --workers 2
cubox-cli card batch --ids-file card-ids.txt -o pretty
```

用一个 Client 批量读取详情，所有 worker 共享 500 ms 节流。默认 2 个 worker，允许 1..4。
文件每行一个 ID；先合并 `--id`，再合并文件，去重保序。始终输出顶层
`schema_version: 1`、`kind: "cubox_card_batch"`、`items`、`counts` JSON，
`-o text` 也不改变这一契约。部分失败先输出完整批次结果，再以退出码 1 结束。
连续三次完成结果为错误后停止新请求，保留已发请求的结果及未启动原因。
`body_available` 仅说明保存了正文文本，不能证明原帖完整。命令不写入、不重试、不跟随跳转，也不抓取原站。

详见[批量输入、JSON 契约和正文分类边界](skills/cubox/references/card-batch.md)。

### `cubox-cli card rag --query TEXT`

通过 RAG（检索增强生成）进行自然语言语义搜索。与关键词搜索不同，RAG 理解查询意图，即使精确词汇不匹配也能返回概念相关的卡片。

```bash
cubox-cli card rag --query "Java实现数据库图片上传功能"
cubox-cli card rag --query "如何构建带认证的 REST API" -o pretty
```

| 参数            | 说明                   |
| ------------- | -------------------- |
| `--query TEXT` | 自然语言查询文本（必填） |

**何时用 RAG vs 关键词 vs 网址：**

- **`card list --url`** — 按卡片存储的完整网址精确查找
- **`card list --keyword`** — 精确词汇、已知标题、域名、短语
- **`card rag --query`** — 提问、主题探索、概念性或模糊查询

### `cubox-cli save`

保存一个或多个网页为书签。支持三种输入方式。

```bash
# 简单模式 — URL 参数
cubox-cli save https://example.com
cubox-cli save https://a.com https://b.com --folder "阅读清单"

# 单个带元数据
cubox-cli save https://example.com --title "我的页面" --desc "有趣的文章"

# 批量 JSON 输入
cubox-cli save --json '[{"url":"https://a.com","title":"标题A"},{"url":"https://b.com"}]' --tag 技术,AI/LLM
```

| 参数               | 说明                                                             |
| ---------------- | -------------------------------------------------------------- |
| `--title TEXT`   | 页面标题（单 URL 模式）                                          |
| `--desc TEXT`    | 页面描述（单 URL 模式）                                          |
| `--json JSON`    | 批量卡片 JSON 数组 `[{"url","title","description"}]`             |
| `--folder NAME`  | 目标收藏夹名称（如 `"父级/子级"`）                                |
| `--tag NAME,...` | 标签名称（逗号分隔，支持嵌套如 `"父级/子级"`）                     |

### `cubox-cli update`

更新卡片属性。

```bash
cubox-cli update --id CARD_ID [flags]
```


| 参数                     | 说明                                                      |
| ---------------------- | ------------------------------------------------------- |
| `--star` / `--unstar`  | 星标/取消星标                                               |
| `--read` / `--unread`  | 已读/未读                                                  |
| `--folder NAME`        | 按名称移动到收藏夹（如 `"父级/子级"`；`""` = 未分类）           |
| `--tag NAME,...`       | 按名称替换全部标签（逗号分隔，支持嵌套如 `"父级/子级"`）           |
| `--add-tag NAME,...`   | 在原有标签基础上新增标签                                     |
| `--remove-tag NAME,...`| 仅移除指定的标签                                             |
| `--title TEXT`         | 更新标题                                                   |
| `--description TEXT`   | 更新描述                                                   |


> 归档/取消归档为批量操作，已拆分为独立命令——见下方 [`cubox-cli archive`](#cubox-cli-archive)。

### `cubox-cli archive`

按 ID 批量归档收藏卡片。归档后的卡片不会出现在默认的 `card list` 中（使用 `card list --archived` 查看归档列表）。

```bash
cubox-cli archive --id CARD_ID[,ID2,...]
```

| 参数            | 说明                              |
| ------------- | ------------------------------- |
| `--id ID,...` | 要归档的卡片 ID（逗号分隔，必填）            |

### `cubox-cli unarchive`

通过将归档卡片移动到一个非归档收藏夹，批量恢复归档的收藏卡片。**目标收藏夹为必填**。

```bash
cubox-cli unarchive --id CARD_ID[,ID2,...] --folder NAME
```

| 参数              | 说明                                                                  |
| --------------- | ------------------------------------------------------------------- |
| `--id ID,...`   | 要恢复的卡片 ID（逗号分隔，必填）                                              |
| `--folder NAME` | 目标收藏夹名称（必填；`""` 表示未分类；嵌套写法 `"父级/子级"`）                       |

收藏夹名称会先通过 `folder list` 在客户端解析为 `folder_id`；如果名称无法匹配现有收藏夹，命令会以可读错误终止。

### `cubox-cli delete`

删除一个或多个收藏卡片。支持 `--dry-run` 预览将要删除的内容。

```bash
cubox-cli delete --id CARD_ID [flags]
```


| 参数            | 说明                 |
| ------------- | ------------------ |
| `--id ID,...` | 要删除的卡片 ID（逗号分隔，必填） |
| `--dry-run`   | 预览将要删除的卡片，不实际执行删除  |
| `--keep-empty-tags` | 删卡后保留空标签，不执行自动清理 |


**Dry Run：** 建议始终先使用 `--dry-run` 预览。输出会列出预计随删卡变空的标签，不写入 Cubox；删除 ≤ 3 张卡片时还会显示标题和 URL，更多卡片不逐张显示。实际删卡前会读取目标卡片与标签；无法确认标签对应关系时会在删卡前停止。删卡后再查普通与归档卡片、子标签，确认空了才清理，并复查删除结果。删卡与删标签不是事务；若后续清理失败，卡片可能已删除，命令会明确报告。

```bash
# 预览
cubox-cli delete --id 7435692934957108160,7435691601617225646 --dry-run

# 确认后执行
cubox-cli delete --id 7435692934957108160,7435691601617225646
```

### `cubox-cli annotation list`

列出和搜索所有卡片的高亮标注。

```bash
cubox-cli annotation list [flags]
```


| 参数                  | 说明                                                |
| ------------------- | ------------------------------------------------- |
| `--color COLOR,...` | 按颜色过滤：`Yellow`, `Green`, `Blue`, `Pink`, `Purple` |
| `--keyword TEXT`    | 搜索标注                                              |
| `--start-time TIME` | 按开始时间过滤                                           |
| `--end-time TIME`   | 按结束时间过滤                                           |
| `--limit N`         | 每页数量（默认 50）                                       |
| `--last-id ID`      | 游标分页                                              |
| `--all`             | 自动翻页获取全部结果                                        |


## 示例

### 搜索文章（关键词）

```bash
cubox-cli card list --keyword "机器学习" --page 1 -o pretty
```

### 按精确网址查找卡片

```bash
cubox-cli card list --url "https://example.com/article" -o pretty
```

### 语义搜索（RAG）

```bash
cubox-cli card rag --query "如何用 Java 实现数据库图片上传并在前端展示" -o pretty
```

### 浏览特定收藏夹的卡片

```bash
cubox-cli folder list -o text
cubox-cli card list --folder 7230156249357091393 --limit 10
```

### 阅读文章并查看 AI 洞察

```bash
cubox-cli card detail --id 7247925101516031380 -o pretty
```

### 保存链接并加星标

```bash
cubox-cli save https://example.com --title "示例网站"
cubox-cli update --id CARD_ID --star --read
```

### 归档与恢复卡片

```bash
# 批量归档
cubox-cli archive --id 7444025677600260245,7443973659296793971

# 浏览归档列表
cubox-cli card list --archived --limit 10

# 批量恢复（移动到非归档收藏夹）
cubox-cli unarchive --id 7444025677600260245,7443973659296793971 --folder "阅读清单"
```

### 整理标签（重命名 / 删除 / 合并）

```bash
# 重命名标签（仅修改叶子；子标签自动跟随）
cubox-cli tag update --id 7295070793040398540 --new-name 链接

# 批量删除标签（卡片本身保留）
cubox-cli tag delete --id 7444025677600260245,7443973659296793971

# 合并标签（源标签的卡片转移到目标标签，源标签随后被删除）
cubox-cli tag merge --source 7342187912403881105,7342187917722258501 --target 7247925099053977508
```

### 删除卡片（带 dry-run）

```bash
cubox-cli delete --id 7435692934957108160 --dry-run -o pretty
cubox-cli delete --id 7435692934957108160
```

### 导出所有标注

```bash
cubox-cli annotation list --all -o pretty
```

### 游标分页（浏览模式）

```bash
cubox-cli card list --limit 5
# 使用最后一张卡片的 ID 获取下一页
cubox-cli card list --limit 5 --last-id 7433152100604841820
```

### 搜索分页

```bash
cubox-cli card list --keyword "AI" --page 1
cubox-cli card list --keyword "AI" --page 2
```

## 开发

### 从源码构建

```bash
cd /path/to/exported-cubox-cli
make build        # 为当前平台构建
make build-all    # 交叉编译所有平台
make release      # 创建发布包
```

### 项目结构

```
cubox-cli/
  main.go                 # 入口
  cmd/                    # cobra 命令
    root.go               # 根命令，--output 参数
    auth.go               # auth login/status/logout
    folder.go             # folder list
    tag.go                # tag list/update/delete/merge
    card.go               # card list/detail/rag
    card_batch.go         # 只读批量详情命令与固定顺序 JSON
    save.go               # save 保存网页
    update.go             # update 更新卡片
    archive.go            # 批量归档 / 恢复归档
    delete.go             # delete 删除卡片（支持 dry-run）
    annotation.go         # annotation 标注列表
    version.go            # version
  internal/
    client/               # HTTP 客户端 + API 类型
      card_batch.go       # 有界并发、锁存停止、回传 ID 校验
      card_content.go     # 保守判断保存的正文证据
    config/               # 配置文件管理
    timefmt/              # 灵活时间解析
    update/               # npm 更新检查
  scripts/                # npm 分发包装
  skills/cubox/           # AI Agent Skill
  .github/workflows/      # CI/CD
```

## 许可证

[MIT](LICENSE)
