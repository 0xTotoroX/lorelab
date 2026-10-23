# 跨工具知识流程

LoreHub 以固定收藏批次连接 Cubox、Soota、知识库 Markdown 和幕布。内容理解、全文审阅和语义写作由外部 Agent 完成；程序校验来源身份、指纹、证据链接、目的地及写入结果，不生成摘要。

## Python 接口

```python
prepare(
    ids_file: Path,
    vault: Path,
    subdir: str,
    mubu_doc: str,
    mubu_parent: str | None = None,
    delete_verified: bool = False,
    state_root: Path | None = None,
    mubu_auth: str = "desktop",
    source_bundles: dict[str, str] | None = None,
) -> dict
submit(job: str, review_file: Path) -> dict
publish(job: str) -> dict
verify(job: str) -> dict
cleanup(job: str, execute: bool = False) -> dict
status(job: str) -> dict
```

`job` 始终为返回的状态目录绝对路径。默认父目录为 `~/.local/state/lorehub/jobs`；`LOREHUB_STATE_DIR` 替换这个父目录，显式 `state_root` 优先。目的地固定为 `vault/subdir`，笔记 `relative_path` 相对该子目录。状态目录与知识库分离；不得把私人状态放进公开仓库或发行包。

所有接口返回 `job`、`status`、`ok`、`sources`、`handoffs`、`pending_source_ids`、`retained_ids` 和 `review_template`。其中 `ok` 表示本次状态可继续，不代表已经发布；只有 `status=verified` 表示知识笔记及幕布完整回读通过，`cleaned` 表示本次删除名单已在 active/archived 中核对不存在。`status()` 只核对本地证据，不联网刷新已保存的云端结论。

契约失败抛 `WorkflowError(RuntimeError)`；runtime 的工具错误原样传播。prepare 失败会在异常中给出已保存的 job 路径。`prepare_failed` 不能发布，应查看回执后以更正输入准备新批次。

产品进程边界是 `lorehub.runtime.run_json(tool, args, receipt=None, acceptable_codes=(0,))`，返回原始 JSON dict/list/null，禁止自动重试。runtime 强制 `SOOTA_AUTO_UPDATE=false`；workflow 不改环境变量、不查服务私有 API。Cubox 输出指定 `-o json`；幕布所有调用均以全局 `--agent --auth desktop` 开头，可显式选择 `password`。

## prepare 与补抓

1. 固定输入 ID，读取 `folder list` 和 `card batch`。错误、跳过和缺正文项保留原状态。GitHub 域名及 GitHub 文件夹的全部后代受保护，不进入提炼或清理。
2. 仅将 `content_status=body_available` 的 `card.content` 原样 UTF-8 保存到 `sources/SHA256/source.txt`。不 trim、不换行归一、不拼入标题、描述或 AI insight。多个相同正文复用同一不可变输入，同时保留各卡片身份。
3. 对有可用来源的非保护项批量调用：

   ```text
   soota ingest --inputs-file source-inputs.json --provider local
     --want context,note,outline --workers 2 --max-cost 0
     --max-items INPUT_COUNT --output bundles --json
   ```

4. 接受退出码 2 的 `waiting_analysis`。严格按 `data.items[].input_index` 映射保存的输入表，再从真实 `analysis-request.json` 绑定 task/item/context 指纹。返回顺序不代替 input_index。失败条目仍为待补。

`body_available`、本地 `scope=full`、文件存在均不证明原帖完整。审阅模板默认 `partial` 或 `missing`，不会自动填写 `complete`。

`source_bundles` 是本批 `card_id → 外部 Soota bundle 目录或 manifest.json` 的映射，适合提前用 `lorehub tool soota ...` 完成补抓。原 Cubox 快照与补抓来源分别保存，卡片原来的 `description_only` 不改成 `body_available`。外部包只读，后续外部 manifest/正文变化会阻止本批发布或清理。首版支持：

- **Soota v2 正文包**：`source.url` 和 `canonical_url` 均须对应卡片原 URL，`content.source` 身份必须一致；`body.md`、`context.md` 必须已登记、hash/字节数匹配，context 指纹匹配。Twitter/X 别名按账号和精确帖子 ID 对应；其他站点不猜测重定向或 URL 等价性。原样 body.md 作为新的本地 source 输入。明确 `scope=excerpt` 的包不能申报完整。
- **Soota v2 原生 `opencli.twitter.thread` 数据包**：限定 `source.platform=native`、`kind=query`、两个 URL 字段均为该操作；已登记的 `data.json` 必须是 `provider=opencli` 的 hash 验证产物。对象数组中须有且只有一个精确目标帖子 ID，该行 URL 对应原收藏且 `text` 非空。当前 Soota manifest 不保存查询参数，因此不假称校验了请求参数；若 manifest 提供 `native.params`，其中 `tweet-id` 也必须匹配。保存**整份 data.json 原始字节**为 source.txt，再走本地 ingest，既不挑出其他帖子冒充目标，也不做语义改写。来源完整性保持 unknown，图片、引用帖和线程覆盖仍需 Agent 审阅。

其他 native/query、数据 hash 不符、缺目标 ID、错 URL、空正文或不可识别的包会拒绝。没有提供有效补抓包的项保留，不影响其他来源提交。CLI 路由层可将 `--source-bundles JSON_FILE` 读为上述映射传入；该参数解析不属于 workflow 模块。

## Agent 审阅 schema

Agent 必须实际阅读 `sources[].source_path`、补抓的原包及其媒体、`handoffs[].context`、知识目录适用的 AGENTS.md/其引用规则和相关既有笔记。`review_notes` 记录具体审阅结论与完整性依据；程序不能证明 Agent 已阅读全文或所有语义都被覆盖。

`review-template.json` 是可编辑草稿；提交只接受以下字段：

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
      "note_markdown": "# 来源笔记\n\n观点 [证据](context.md#para-ACTUAL)",
      "outline_markdown": "- 观点 [证据](context.md#para-ACTUAL)"
    }
  }],
  "notes": [{
    "title": "主题",
    "relative_path": "主题.md",
    "source_ids": ["CARD_ID"],
    "markdown": "# 主题\n\n可直接阅读的知识正文。\n\n[来源](https://example.org/original)\n",
    "body_sha256": "SHA256_OF_EXACT_MARKDOWN_UTF8",
    "evidence": {"CARD_ID": ["/absolute/job/bundles/BUNDLE/context.md#para-ACTUAL"]},
    "outline": {"text": "主题", "children": [{"text": "观点"}]}
  }]
}
```

`sources` 必须逐一列出所有选定 ID，包括待补项。缺失/受保护项使用 `coverage=missing`、`all_valuable_parts_handled=false`、非空 `gaps`、`submission=null`。partial 项必须说明缺口；complete 不得有 gaps，明确节选不能标 complete。无知识落点不能声称有价值内容全部处理。原始 source hash 不得更改。

每个源 submission 的 note/outline 都须引用**自己的 context**中的真实证据 ID；指向另一源的路径会拒绝。这些来源产物保存在私有状态区。

最终主题笔记推荐通过独立的 `notes[].evidence` 逐一映射 `source_ids`，每项至少一个真实 `context路径#证据ID`。映射按对应来源单独校验，不能把另一源的有效证据挂到本源名下。映射与 ID、路径、审阅状态仅进入冻结台账；**知识库文件只写 `markdown` 字段**，不会自动附加私有路径、审计信息或来源区。正文来源按目的地规则使用原始 URL。

为了兼容已有提交，可省略 evidence，改用正文内联 context 链接；此时每个来源仍必须有真实证据。支持普通 Markdown 链接及 `<含空格的路径>`，相对链接从最终笔记目录解析。新工作流应优先使用独立 evidence，不把私有 job 路径写进用户知识正文。正文和大纲的语义对应关系仍由 Agent 审阅。

`body_sha256` 是最终 `markdown.encode("utf-8")` 的 SHA-256，保留全部换行。大纲根 `text` 必须等于 title；节点仅接受 text、可选 note、children。单批遵守幕布 500 节点、32 层和 512 KiB 限制；不自动分批写入。

submit 先冻结 candidate，再写按 item 分开的 submissions 并调用 `soota jobs resume TASK --analysis DIRECTORY --max-cost 0 --json`。所有被最终笔记引用的 item 必须真实返回 completed，并通过 note/outline/analysis/context 的登记 hash 核验；其他待补 item 可继续 waiting_analysis。通过后冻结 approved.json、大纲及完成产物 hash。重试 submit 只接受同一份冻结内容，不覆盖已有 Soota 分析，不用 `--force`。

## 发布、核验和恢复

publish 先检查来源、approved 和已完成 Soota 产物；对用到的 Cubox 卡片再次 batch 比对原快照。所有文件只在固定 vault/subdir 内写入，拒绝 `..`、绝对路径、符号链接、隐藏路径及 AGENTS.md/CLAUDE.md。

已有同路径文件只有**字节 hash 相同**才能复用；不同则拒绝并要求 Agent 独立审阅合并。不会覆盖手写内容。新文件以独占创建方式写入并 fsync，每份笔记实读 hash 后登记；中途崩溃留下不同内容时停止，不自动修复或覆盖。

幕布按文档 ID 取得同进程锁和 OS 文件锁（共享位置为 `$XDG_STATE_HOME/lorehub/locks`，默认 `~/.local/state/lorehub/locks`），同机 LoreHub 写入串行化。读取不裁剪的全树和 HTML，拒绝目标父级下的同名主题根。preview 版本必须等于当前版本；保存原树与写入意图并 fsync 后才允许 execute。

**一个 job 最多派发一次 node-import execute。** 返回未知、uncertain、冲突、拒绝或调用前后崩溃，都不重新导入。verify/publish 恢复只读取：

- 优先使用执行回执的 root_ids；预览 ID 永不当作执行 ID。
- 只有已记录 operation_id 时，可通过 `operation-status --verify` 的 `whole_document` 证明恢复；不凭标题或文本猜测成功。
- 校验所有新后代的文字、说明、层级和顺序；旧节点的 ID、路径、正文/说明 HTML、图片、顺序须保全。目标父级只允许预期 child_count 增加。全树不得多出其他新节点，版本必须恰好增加一次。
- 若根 ID 和操作证据都丢失，即使肉眼看见同名主题也保持 `publish_uncertain`。需人工查原操作回执，不能用新批次盲重发。

该锁不控制幕布网页/手机/其他机器。版本检查不是服务端 CAS；后续其他编辑会使严格核验失效。CLI 全树接口可见字段由 LoreHub 回读核对，组件内部另有完整 definition 验证；不宣称未知未来字段均由 LoreHub 单独证明。

## 清理门禁

只有 prepare 明确 `delete_verified=true`，且来源 complete、有价值内容全处理、gaps 空、非 protected、已关联实际笔记、Soota item completed、知识笔记和幕布回读全部通过，才进入候选名单。

cleanup 默认只预览：再次读取文件夹保护范围，batch 比对卡片原快照，执行 `cubox delete --id ... --keep-empty-tags --dry-run -o json`。只有 `execute=True` 才在重新核验后持久化删除意图并发起真实删除。

删除后对每个原 URL 使用 `card list --url URL --all`，分别读取 active 和 `--archived`；以目标 **ID 不存在** 判断，允许同 URL 的其他收藏继续存在。保留项再次 batch 比对未变；最初读取失败项仅能核对失败状态，另列 `retained_unreadable_ids`，不宣称正文已核验。

**一个 job 最多派发一次 delete。** 重复 cleanup（包括 execute=True）只读对账；已删一部分、超时或仍观察到目标 ID 时保持 uncertain，不能重删。笔记、来源、approved 或大纲被改动会拒绝清理。删除前源内容变化会停止，不自动接受新版本。

## 模块与验证

| 文件 | 职责 |
| --- | --- |
| `workflow.py` | 六个公共接口、结果与 runtime 注入点 |
| `workflow_state.py` | 原子持久化、锁、路径与不可变 hash |
| `workflow_sources.py` | Cubox 快照、保护范围、补抓及 Soota handoff |
| `workflow_review.py` | 审阅 schema、证据校验、Soota resume、冻结 |
| `workflow_publish.py` | 新笔记、幕布单写入者、全树对账 |
| `workflow_cleanup.py` | 授权删除门禁、预览与只读恢复 |

测试用 `lorehub.workflow.run_json` 替换三工具 CLI，所有数据为合成数据。运行 `python -m pytest -q tests/test_workflow*.py`。覆盖主链、native 补抓与缺失对照、路径越界、伪完整、保护与授权、串行锁、部分来源保留、跨源引用、冻结修改、笔记冲突、写入超时和恢复不重复。mock 契约验收不等于账号/真实站点/真实云写入验收。
