# 文章整理与学习交付

Soota 的显式知识任务将选定的 Cubox 收藏或现有内容包整理为完整、连贯的文章，写入 Obsidian 或用户明确指定的 Markdown 知识目录并回读后结束。文章可以综合多个来源，讲清关系、适用条件和证据；完整以足够理解和使用为准，不要求长篇、固定结构或每篇都列要点。无需把内容强制拆成短笔记与主题文章、保存双份或建立两套目录，已有笔记继续保留。

内容理解、全文审阅和语义写作由外部 Agent 完成；程序校验来源身份、指纹、证据链接、目的地及写入结果。用户以后明确要求学习或复习时，使用独立 `study` 任务从选定的现有文章制作幕布大纲。文章完成不会自动触发大纲或定时同步，不建立幕布返回 Obsidian 的索引。

普通 `soota ingest` 仍默认停在未加工的 `context.md`；下载、聊天总结或分析不隐含知识归档。只有明确请求整理、保存知识或制作学习大纲时，才进入本文流程。CLI 不调用语言模型，Agent 负责实读、写作和语义审核。

## 默认文章流程

```sh
soota knowledge init --vault /path/to/KnowledgeVault --subdir 知识
soota knowledge prepare --ids-file /path/to/card-ids.txt
soota knowledge submit /path/to/job --file /path/to/review.json
soota knowledge publish /path/to/job
soota knowledge verify /path/to/job
```

`prepare` 返回实际 JOB 和 `review_template`；Agent 阅读来源后填写模板，审核通过再提交。示例路径、ID 和 hash 均为占位符，必须替换为本次真实产物。默认不删除收藏；有适用的明确授权才启用 `--delete-verified`，再执行[清理](#清理门禁)。

## Python 接口

```python
prepare(
    ids_file: Path | None,
    vault: Path,
    subdir: str,
    mubu_doc: str | None = None,
    mubu_parent: str | None = None,
    delete_verified: bool = False,
    state_root: Path | None = None,
    mubu_auth: str = "desktop",
    source_bundles: dict[str, str] | None = None,
    with_outline: bool = False,
    cleanup_after: str = "article",
    bundles_file: Path | None = None,
) -> dict
submit(job: str, review_file: Path) -> dict
publish(job: str) -> dict
verify(job: str) -> dict
cleanup(job: str, execute: bool = False) -> dict
status(job: str) -> dict
```

Python 接口位于 `soota.knowledge.workflow`，学习接口位于 `soota.knowledge.study`。

`job` 始终为返回的状态目录绝对路径。新任务默认保存在 Soota 数据目录下的 `knowledge/jobs`，数据根可由 `SOOTA_DATA_DIR` 指定。显式 `state_root` / `--state-root` 优先，其后依次读取 `SOOTA_KNOWLEDGE_STATE_DIR`、`LORELAB_STATE_DIR`、`LOREHUB_STATE_DIR`；这些任务目录变量直接替换 jobs 父目录。旧任务继续按返回的绝对路径打开，不搬动或改写冻结产物。目的地固定为 `vault/subdir`，笔记 `relative_path` 相对该子目录。状态目录与知识库分离；不得把私人状态放进公开仓库或发行包。

这些 knowledge 批次接口返回 `job`、`status`、`ok`、`delivery`、`sources`、`handoffs`、`pending_source_ids`、`retained_ids` 和 `review_template`。`delivery` 为 `article` 或 `article-and-outline`。`ok` 表示本次状态可继续，不代表已经发布；`status=verified` 表示本批选定交付已回读通过：文章模式核对实际文章和来源，组合模式还须核对幕布。`cleaned` 表示本次删除名单已在 active/archived 中核对不存在，不表示所有输入都已删除。`status()` 只核对本地证据，不联网刷新已保存的云端结论。

契约失败抛 `WorkflowError(RuntimeError)`；runtime 的工具错误原样传播。prepare 失败会在异常中给出已保存的 job 路径。`prepare_failed` 不能发布，应查看回执后以更正输入准备新批次。

流程的进程边界返回 CLI 的 JSON 结果，不自动重试。独立运行时通过当前 Python 解释器的 `-m soota.cli` 调用 Soota；Cubox 和幕布使用已配置或发现的各自 CLI。受管安装只使用当前 release 绑定的入口，强制 `SOOTA_AUTO_UPDATE=false`，缺失时不退回 PATH。知识模块不查服务私有 API。Cubox 输出指定 `-o json`；幕布所有调用均以全局 `--agent --auth desktop` 开头，可显式选择 `password`。

## 配置、独立组件与兼容入口

`soota knowledge init` 保存知识目的地、可选幕布目标及删除意图。读取配置的顺序如下：

1. `SOOTA_KNOWLEDGE_CONFIG_FILE` 有值时使用该文件。
2. 否则，`SOOTA_CONFIG_DIR` 有值时使用其中的 `knowledge.json`。显式指定的文件即使不存在，也不回退到私人旧配置。
3. 否则先找 `$XDG_CONFIG_HOME/soota/knowledge.json`，再按顺序找 `lorelab/config.json`、`lorehub/config.json`；`XDG_CONFIG_HOME` 未设置时以 `~/.config` 为根。
4. 都不存在时，新配置写到上述 Soota 路径。已经找到的旧配置原位沿用，不静默复制或扩大删除授权。

独立 Soota 可以通过 `SOOTA_CUBOX_COMMAND`、`SOOTA_MUBU_COMMAND` 指定外部 CLI 的 **JSON argv 数组**；未指定时分别发现 `cubox-cli`、`mubu-cli`。数组第一项必须是可执行文件的绝对路径，后续项是固定参数；不接受 shell 命令文本，不放账号口令。显式入口无效时停止，不退回 PATH。Cubox 只在收藏输入或对应清理中需要，幕布只在实际选择大纲交付时需要。读取内容包、发布文章不要求安装这两个服务 CLI。

LoreLab 成套安装绑定自己的组件入口。`lorelab init`、`lorelab batch …`、`lorelab study …` 分别转到本页的 `soota knowledge init`、`soota knowledge …`、`soota study …`。旧 `lorehub` 命令、Python 兼容包和 Skill 已移除；旧任务可直接把原 JOB 路径交给 Soota 或上述 LoreLab 路由，旧配置原位读取。历史 prefix、配置、环境变量与共享锁目录名称保留用于数据兼容，不构成旧入口依赖。既有 `soota ingest/jobs/render` 命令及其任务继续使用，不需要改名。

## 交付选择与旧任务

新批次的 `spec.json` 记录 `kind=batch`、布尔值 `with_outline` 和 `cleanup_after=article|outline`。API 默认 `with_outline=false`、`cleanup_after=article`、`delete_verified=false`。CLI `init` 不再要求幕布目标，默认保存 `cleanup_after=article`，删除仍须显式选择。

| 选择 | 交付与清理条件 |
| --- | --- |
| `knowledge prepare` 不传 `--with-outline` | 只交付文章；即使配置中有幕布目标，也不生成大纲，publish/verify/cleanup 均不调用幕布。 |
| `knowledge prepare --with-outline --mubu-doc DOCUMENT_ID` | 用户明确选择同批交付文章和大纲；幕布目标可来自配置，两处均核对通过才算本批交付完成。 |
| `--cleanup-after article` | 在本批交付已核对的前提下，以完整来源覆盖和文章写入回读作为清理条件；不单独要求额外学习任务。 |
| `--cleanup-after outline` | 额外要求本批幕布交付已核对；文章模式仍可完成，但不能据此清理。 |
| `--delete-verified` / `--no-delete-verified` | 本批启用或关闭删除意图；不等于已经满足清理条件。未传时沿用配置，新配置默认关闭。 |

内容包输入记录 `source_kind=bundle`，强制 `delete_verified=false`；缺少 `source_kind` 的旧任务仍按 Cubox 来源恢复。

CLI 的 `--cleanup-after` 覆盖配置。旧配置缺少该字段时按 `outline` 处理，防止曾经要求两处核对的删除授权被升级扩大；即使新批次默认只写文章，也保留该清理门槛。用户明确改为文章完成即可清理后，准备新批次时显式传 `--cleanup-after article`，不修改已冻结的任务。

旧持久化任务缺少新字段时，仍按 `with_outline=true`、`cleanup_after=outline` 恢复，保持原有组合交付语义。独立 `study` 的结果不会回填或放宽旧批次的删除条件。

## Cubox 输入与补抓

1. 固定输入 ID，读取 `folder list` 和 `card batch`。错误、跳过和缺正文项保留原状态。GitHub 域名及 GitHub 文件夹的全部后代受保护，不进入提炼或清理。
2. 仅将 `content_status=body_available` 的 `card.content` 原样 UTF-8 保存到 `sources/SHA256/source.txt`。不 trim、不换行归一、不拼入标题、描述或 AI insight。多个相同正文复用同一不可变输入，同时保留各卡片身份。
3. 对有可用来源的非保护项批量调用：

   ```text
   soota ingest --inputs-file source-inputs.json --provider local
     --want context,note --workers 2 --max-cost 0
     --max-items INPUT_COUNT --output bundles --json
   ```

   只有 `with_outline=true` 时才改为 `--want context,note,outline`。

4. 接受退出码 2 的 `waiting_analysis`。严格按 `data.items[].input_index` 映射保存的输入表，再从真实 `analysis-request.json` 绑定 task/item/context 指纹。返回顺序不代替 input_index。失败条目仍为待补。

`body_available`、本地 `scope=full`、文件存在均不证明原帖完整。审阅模板默认 `partial` 或 `missing`，不会自动填写 `complete`。

`source_bundles` 是 Cubox 批次的 `card_id → 外部 Soota bundle 目录或 manifest.json` 的映射，适合提前用 `soota ingest ...` 完成补抓。原 Cubox 快照与补抓来源分别保存，卡片原来的 `description_only` 不改成 `body_available`。外部包只读，后续外部 manifest/正文变化会阻止本批发布或清理。补抓支持：

- **Soota v2 正文包**：`source.url` 和 `canonical_url` 均须对应卡片原 URL，`content.source` 身份必须一致；`body.md`、`context.md` 必须已登记、hash/字节数匹配，context 指纹匹配。Twitter/X 别名按账号和精确帖子 ID 对应；其他站点不猜测重定向或 URL 等价性。原样 body.md 作为新的本地 source 输入。明确 `scope=excerpt` 的包不能申报完整。
- **Soota v2 原生 `opencli.twitter.thread` 数据包**：限定 `source.platform=native`、`kind=query`、两个 URL 字段均为该操作；已登记的 `data.json` 必须是 `provider=opencli` 的 hash 验证产物。对象数组中须有且只有一个精确目标帖子 ID，该行 URL 对应原收藏且 `text` 非空。当前 Soota manifest 不保存查询参数，因此不假称校验了请求参数；若 manifest 提供 `native.params`，其中 `tweet-id` 也必须匹配。保存**整份 data.json 原始字节**为 source.txt，再走本地 ingest，既不挑出其他帖子冒充目标，也不做语义改写。来源完整性保持 unknown，图片、引用帖和线程覆盖仍需 Agent 审阅。

其他 native/query、数据 hash 不符、缺目标 ID、错 URL、空正文或不可识别的包会拒绝。没有提供有效补抓包的项保留，不影响其他来源提交。CLI 路由层可将 `--source-bundles JSON_FILE` 读为上述映射传入；该参数解析不属于 workflow 模块。

## 现有内容包输入

网页、视频、音频或本地文件先走已有 `soota ingest`，按用户请求取得正文或字幕 context；随后把待整理的 **Soota v2 内容包**写成 JSON 路径数组：

```json
["./bundles/webpage", "./bundles/video/manifest.json"]
```

清单可以混合包目录和 `manifest.json` 路径，相对路径以清单文件所在目录为基准。随后执行：

```sh
soota knowledge prepare --bundles-file /path/to/source-bundles.json \
  --vault /path/to/KnowledgeVault --subdir 知识
```

`--bundles-file` 与 `--ids-file` 互斥；`--source-bundles` 专用于 Cubox ID 的补抓映射，不能把这两种参数互换。内容包必须有已登记并校验的 `context.md`，并至少有已验证的 `body.md` 或 ready 状态的 `transcript.md`。后续分析输入使用完整的已校验 `context.md`；同包同时含正文与字幕时，两者都保留在分析输入中，不只选取 body。仅数据、媒体、空包或缺少正文证据的包不能冒充可读来源。

原包只读。任务保存来源快照、原包 manifest 与所有登记产物的 hash；外部包后来改变会拒绝继续，不以新内容偷偷替换已冻结的来源。只有正文时沿用 `content.scope`；含字幕时完整范围为 `unknown`，但正文明确为 `excerpt` 时继续保留 `excerpt`。审阅覆盖不会自动填成 complete，Agent 仍须审阅原包、context 和实际媒体范围：文件完整、下载成功或 hash 匹配都不证明原始帖子或视频内容完整。

内容包批次不调用 Cubox，`delete_verified` 固定为 false，即使通用配置启用了删除；不删除原包或原始媒体。GitHub URL 仍受保护，不借内容包入口绕过保护。来源 ID 和分析交接取自 `prepare` 返回值，不假造 Cubox ID。其后提交、文章发布和核验使用相同 schema，可把多个包的相关材料合成一篇文章；未覆盖的部分明确保留缺口。

## Agent 审阅 schema

Agent 必须实际阅读 `sources[].source_path`、补抓的原包及其媒体、`handoffs[].context`、知识目录适用的 AGENTS.md/其引用规则和相关既有笔记。`review_notes` 记录具体审阅结论与完整性依据；程序不能证明 Agent 已阅读全文或所有语义都被覆盖。

`review-template.json` 是可编辑草稿。文章模式的提交示例如下；对外字段仍是 `notes` 和 `markdown`，没有 `article_markdown` 字段：

```json
{
  "sources": [{
    "id": "CARD_ID",
    "source_sha256": "SHA256_OF_EXACT_SOURCE_BYTES",
    "coverage": "complete",
    "all_valuable_parts_handled": true,
    "gaps": [],
    "review_notes": "实际阅读范围、全文与媒体覆盖依据、目标规则及既有笔记核对结论",
    "submission": {
      "task_id": "ACTUAL_TASK_ID",
      "item_id": "ACTUAL_ITEM_ID",
      "context_fingerprint": "ACTUAL_CONTEXT_SHA256",
      "note_markdown": "# 来源分析\n\n基于本来源的结论与适用条件。[证据](context.md#para-ACTUAL)"
    }
  }],
  "notes": [{
    "title": "主题",
    "relative_path": "主题.md",
    "source_ids": ["CARD_ID"],
    "markdown": "# 主题\n\n围绕问题展开的文章正文，说明结论之间的关系、证据和适用条件。\n\n[来源](https://example.org/original)\n",
    "body_sha256": "SHA256_OF_EXACT_MARKDOWN_UTF8",
    "evidence": {"CARD_ID": ["/absolute/job/bundles/BUNDLE/context.md#para-ACTUAL"]}
  }]
}
```

`sources` 必须逐一列出 prepare 返回的所有来源 ID，包括待补项。缺失/受保护项使用 `coverage=missing`、`all_valuable_parts_handled=false`、非空 `gaps`、`submission=null`。partial 项必须说明缺口；complete 不得有 gaps，明确节选不能标 complete。无知识落点不能声称有价值内容全部处理。原始 source hash 不得更改。

每个源 submission 的 `note_markdown` 都须引用**自己的 context**中的真实证据 ID；指向另一源的路径会拒绝。这些来源分析产物保存在私有状态区，不要求在知识库另存一份短笔记。最终文章由 `notes[]` 描述，可合并多个来源。

文章模式的模板不含 `submission.outline_markdown`，最终 `notes[]` 也不接受 `outline`；自行添加这些字段会拒绝。只有组合模式才在每个有效 submission 增加 `outline_markdown`，在每份最终文章增加 `outline`，例如：

```json
{"text": "主题", "children": [{"text": "确认没有字幕轨道后才获取音频并本地转写；获取失败仍需排查。"}]}
```

这个对象放在 `notes[].outline`，根 `text` 必须等于该项 `title`。`outline_markdown` 同样必须引用对应来源自己的 context 证据；最终树从定稿文章组织概念、关系或问题，不按句子机械拆节点。示例层级不构成固定模板。

最终文章推荐通过独立的 `notes[].evidence` 逐一映射 `source_ids`，每项至少一个真实 `context路径#证据ID`。映射按对应来源单独校验，不能把另一源的有效证据挂到本源名下。映射与 ID、路径、审阅状态仅进入冻结台账；**知识库文件只写 `markdown` 字段**，不会自动附加私有路径、审计信息或来源区。正文来源按目的地规则使用原始 URL。

为了兼容已有提交，可省略 evidence，改用正文内联 context 链接；此时每个来源仍必须有真实证据。支持普通 Markdown 链接及 `<含空格的路径>`，相对链接从最终文章目录解析。新工作流应优先使用独立 evidence，不把私有 job 路径写进用户文章。来源与文章的语义对应关系，以及启用大纲时的文章与树的对应关系，均由 Agent 审阅。

`body_sha256` 是最终 `markdown.encode("utf-8")` 的 SHA-256，保留全部换行。启用大纲时，节点仅接受 `text`、可选 `note`、`children`；整个提交合计遵守幕布 500 节点、32 层和 512 KiB 限制，不自动分批写入。这些是容量上限，不是写作时要凑齐的数量。

submit 先冻结 candidate，再写按 item 分开的 submissions 并调用 `soota jobs resume TASK --analysis DIRECTORY --max-cost 0 --json`。所有被最终文章引用的 item 必须真实返回 completed，并通过 `context.md`、`note.md`、`analysis.json` 的登记 hash 和字节数核验，连同 manifest 保存完成产物指纹；其他待补 item 可继续 waiting_analysis。通过后冻结 `approved.json` 和完成产物 hash。文章模式不要求 `outline.md`，也不生成 `outline.json`；组合模式额外核验 `outline.md` 并冻结 `outline.json`。重试 submit 只接受同一份冻结内容，不覆盖已有 Soota 分析，不用 `--force`。

## 发布、核验和恢复

knowledge publish 先检查来源、approved 和已完成 Soota 产物；Cubox 批次对用到的卡片再次 batch 比对原快照，内容包批次复核只读原包的登记产物。所有文章只在固定 vault/subdir 内写入，拒绝 `..`、绝对路径、符号链接、隐藏路径及 AGENTS.md/CLAUDE.md。

已有同路径文件只有**字节 hash 相同**才能复用；不同则拒绝并要求 Agent 独立审阅合并。不会覆盖手写内容，当前没有自动合并或更新已有文章的功能。新文件以独占创建方式写入并 fsync，每份文章实读 hash 后登记；中途崩溃留下不同内容时停止，不自动修复或覆盖。

文章模式按目的地使用写入锁；publish/verify/cleanup 只走文章及来源核对，不读取或写入幕布。文章回读通过即可完成选定交付。下列幕布规则仅适用于显式组合交付和独立 `study` 任务。

幕布按文档 ID 取得同进程锁和 OS 文件锁（共享位置为 `$XDG_STATE_HOME/lorehub/locks`，默认 `~/.local/state/lorehub/locks`），Soota 与 LoreLab 沿用历史共享位置，保持升级前后的写入互斥；目录名称不表示仍提供旧命令。读取不裁剪的全树和 HTML，拒绝目标父级下的同名主题根。preview 版本必须等于当前版本；保存原树与写入意图并 fsync 后才允许 execute。

**一个 job 最多派发一次 node-import execute。** 返回未知、uncertain、冲突、拒绝或调用前后崩溃，都不重新导入。verify/publish 恢复只读取：

- 优先使用执行回执的 root_ids；预览 ID 永不当作执行 ID。
- 只有已记录 operation_id 时，可通过 `operation-status --verify` 的 `whole_document` 证明恢复；不凭标题或文本猜测成功。
- 校验所有新后代的文字、说明、层级和顺序；旧节点的 ID、路径、正文/说明 HTML、图片、顺序须保全。目标父级只允许预期 child_count 增加。全树不得多出其他新节点，版本必须恰好增加一次。
- 若根 ID 和操作证据都丢失，即使肉眼看见同名主题也保持 `publish_uncertain`。需人工查原操作回执，不能用新批次盲重发。

该锁不控制幕布网页/手机/其他机器。版本检查不是服务端 CAS；后续其他编辑会使严格核验失效。CLI 全树接口可见字段由 Soota 知识流程回读核对，组件内部另有完整 definition 验证；不宣称未知未来字段均由知识流程单独证明。

## 清理门禁

只有 prepare 记录适用的明确授权 `delete_verified=true`，且来源 complete、有价值内容全处理、gaps 空、非 protected、已关联实际文章、Soota item completed、本批选定交付回读通过，才进入候选名单。`cleanup_after=article` 的文章模式到此已经满足交付条件，无需幕布；`cleanup_after=outline` 还要求本批幕布回读通过。组合模式仍须两处交付均核对通过，不能用清理选项跳过其大纲交付。

来源覆盖与文章写入回读是可清理的依据；产品默认关闭删除。用户针对当前范围的授权可复用，不能把另一批次或旧的两处核对授权静默改成文章完成即可删除。资料不全、获取失败、冲突、未核对和 GitHub 项目保留。内容包来源不进入删除候选，也不调用 Cubox。独立 study 无 cleanup，也不改变本批清理状态。

cleanup 默认只预览：再次读取文件夹保护范围，batch 比对卡片原快照，执行 `cubox delete --id ... --keep-empty-tags --dry-run -o json`。只有 `execute=True` 才在重新核验后持久化删除意图并发起真实删除。

删除后对每个原 URL 使用 `card list --url URL --all`，分别读取 active 和 `--archived`；以目标 **ID 不存在** 判断，允许同 URL 的其他收藏继续存在。保留项再次 batch 比对未变；最初读取失败项仅能核对失败状态，另列 `retained_unreadable_ids`，不宣称正文已核验。

**一个 job 最多派发一次 delete。** 重复 cleanup（包括 execute=True）只读对账；已删一部分、超时或仍观察到目标 ID 时保持 uncertain，不能重删。文章、来源、approved 或本批启用的大纲被改动会拒绝清理。删除前源内容变化会停止，不自动接受新版本。

## 独立学习任务 study

只在用户明确请求学习或复习时启动；输入是已经存在于选定 vault 内的 Markdown 文章，不必由 Soota 生成，也不依赖 Cubox 收藏仍然存在。

```sh
soota study prepare --article /path/to/KnowledgeVault/知识/主题.md \
  --article /path/to/KnowledgeVault/知识/相关主题.md \
  --vault /path/to/KnowledgeVault --mubu-doc DOCUMENT_ID
soota study submit /path/to/study-job --file /path/to/study-review.json
soota study publish /path/to/study-job
soota study verify /path/to/study-job
soota study status /path/to/study-job
```

`--article FILE` 可重复，必须明确选择文章；`--vault`、`--mubu-doc`、`--mubu-parent` 和 `--mubu-auth desktop|password` 可从配置取默认值，认证默认 desktop。可用 `--state-root` 指定与 vault 分离的任务状态目录。没有目标配置时显式传入，不从文章内容猜测文档 ID。

prepare 读取文章的实际 Markdown，保存不可变快照与字节 hash。模板使用 `articles`，每项的 `relative_path` 相对 vault，`body_sha256` 绑定原文章，`outline.text` 取文章实际 H1，无 H1 时用文件名：

```json
{
  "articles": [{
    "relative_path": "知识/主题.md",
    "body_sha256": "SHA256_OF_EXACT_ARTICLE_BYTES",
    "review_notes": "",
    "outline": {"text": "主题", "children": []}
  }]
}
```

这是待填写模板。提交必须逐一覆盖所选文章，不增加、遗漏或重复；保留实际路径、hash 和 H1，填写非空的语义审阅说明，并从文章内容组织学习树。审阅要说明概念关系、实用条件和重要例外的去向。每个节点是完整可理解的知识单元，直接相关的简短条件和参数可放在同一节点；只有真实上下位关系才增加子层级，不要求一叶一操作或判断，也不强制层级或数量。树沿用[大纲校验](#agent-审阅-schema)的节点字段以及每次提交合计 500 节点、32 层、512 KiB 上限。

submit 冻结审阅和大纲；后续操作继续核对源文章与快照。原文改变、缺失或发生路径冲突就停止，不以旧快照重建文章，也不重写原文。`study` 不调用 Cubox 或重新摄取来源，不要求 source/task/item 证据映射，不生成另一份文章，不提供收藏清理命令。其 `status` 只检查本地状态；云端结果通过 `verify` 实际回读。

发布复用[单一幕布写入者与恢复规则](#发布核验和恢复)：同一文档串行化，预览版本检查，写入前持久化意图，一个 job 最多一次 `node-import execute`，不确定时只读对账；保全旧树并核对新树的文字、说明、层级和顺序。目标父级下同名主题冲突须人工审阅合并，不自动追加副本或更新原主题。该任务独立完成，不安排文章到幕布的自动同步。

## 模块与验证

| 文件 | 职责 |
| --- | --- |
| `cli.py` | knowledge/study 命令与 LoreLab 参数路由 |
| `runtime.py` | 配置优先级、独立/受管 CLI 绑定与私有回执 |
| `bundles.py` | 现有 v2 内容包只读快照、全部登记产物核验与来源身份 |
| `workflow.py` | knowledge 批次公共接口、选定交付结果与运行时注入点 |
| `workflow_state.py` | 原子持久化、锁、路径与不可变 hash |
| `workflow_sources.py` | Cubox 与内容包快照、保护范围、补抓及分析交接 |
| `workflow_review.py` | 审阅 schema、证据校验、Soota resume、冻结 |
| `workflow_publish.py` | 新文章、共享幕布单写入者、全树对账 |
| `workflow_cleanup.py` | 授权删除门禁、预览与只读恢复 |
| `study.py` | 现有文章快照、学习审阅与独立幕布交付，不改源文章或清理收藏 |

上述实现位于 `src/soota/knowledge/`，由 Soota 独立维护；LoreLab 的 `init/batch/study` 只作参数路由。工作流契约测试替换工具 CLI 并使用合成数据；各命令的实际覆盖以当前测试与运行结果为准。历史组合流程测试不代表文章模式或 study 已完成真实验收；mock 契约测试、文档检查均不等于账号、真实站点或真实云写入验收。
