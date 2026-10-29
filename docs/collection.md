# X 导出集合的逐帖知识整理

`knowledge collection` 保存来源、Agent 决策、实际交付和策略版本，适合已经取得一批 X 导出、需要按 Cubox 收藏 ID 管理的任务。CLI 不生成全文、不调用模型、不推断帖子类型。普通 `knowledge prepare --source-bundles` 已能绑定 Cubox 与 Soota v2 补抓包；它仍适用于由 LoreLab 发布文章的批次，严格来源门槛不变。collection 补充的是开放决策、外部交付登记和整批完成检查，不要求每帖建立 Soota job。

## 命令与准备

```text
lorelab knowledge collection prepare --file /private/materials/manifest.json --state-root /private/state/collections
lorelab knowledge collection review JOB --file /private/materials/review.json
lorelab knowledge collection verify JOB
lorelab knowledge collection status JOB
lorelab knowledge collection feedback JOB --file /private/materials/feedback.json
lorelab knowledge collection authorize JOB --file /private/materials/authorization.json
lorelab knowledge collection cleanup JOB
lorelab knowledge collection cleanup JOB --execute
```

`submit` 是 `review` 的别名，`ready` 是 `verify` 的别名。源码环境在仓库根目录使用 `.venv/bin/python -m lorelab.cli ...`，或 `uv run python -m lorelab.cli ...`；前者要求已有依赖，后者可能同步环境。未更新的安装版不会自动使用工作区改动。

prepare 完全离线，读取 JSON 清单、UTF-8 原文和原始文件，返回绝对 JOB 和 `review-template.json`。示例中的路径和 ID 均为占位：

```json
{
  "schema_version": 1,
  "destination": "/private/knowledge",
  "materials_root": "/private/materials",
  "sources": [{
    "id": "1001",
    "status_id": "2001",
    "url": "https://x.com/example/status/2001",
    "availability": "collected",
    "text_file": "/private/materials/2001.txt",
    "raw_files": [{"path": "/private/materials/export.jsonl", "sha256": "原始文件SHA256"}]
  }]
}
```

`id` 是真实 Cubox 卡片 ID，`status_id` 是 X 数字 ID。重复 Cubox ID 拒绝；同一帖的多个卡片可共用相同 `status_id`、`text_file` 和 `raw_files`，清理仍按卡片逐一授权。URL 必须指向该 status，接受 X/Twitter 的 `/user/status/id` 与 `/i/web/status/id` 形式；非 status URL、GitHub URL 和没有真实 Cubox 身份的增量帖子不能成为本集合来源或删除目标。全批 ready 只覆盖 prepare 冻结的集合，不能证明遗漏在清单外的收藏已处理。

`availability` 为 `collected` 或 `missing`；后者的 `text_file` 必须为 null，原始导出/失败文件仍须登记。`collected` 只表示取得了非空文本，不能证明原帖或长文完整。Agent 必须实读，并按授权补齐链接、长文或缓存正文，不能以描述和摘要冒充。目标目录必须已存在；材料和状态与知识目录、产品仓库分离，不能使用符号链接。材料默认位于 manifest 所在目录，可显式设置其共同 `materials_root`，manifest 也须位于其中。

清单、正文、原始导出及后续 review 均保存指纹。共享原始导出在每次核对中仅 hash 一次。来源内容改变须准备新集合，旧任务不降级。补充资料应先完成再冻结，或者以完整证据准备后继集合；不要删除原始任务或改写已冻结证据。

## 开放 review 与实际交付

review 文件为 `{"schema_version":1,"sources":[...]}`，可以只包含本轮实读的来源子集。每项完整提交；重复/越界 ID 拒绝。同一 ID 的更正新增不可变 review 文件并切换当前指针，历史不覆盖。字段如下：

```json
{
  "id": "1001",
  "source_sha256": "prepare返回的text_sha256",
  "read_sha256": "Agent实际读过的同一文本指纹",
  "decision": "processed",
  "strategy": "本帖实际采用的处理方法",
  "rationale": "为什么这样处理",
  "coverage": "原帖各部分、长文和链接的实际去向与边界",
  "complete": true,
  "gaps": [],
  "outputs": [
    {"kind":"article","path":"主题/文章.md","sha256":"实际文章SHA256"},
    {"kind":"repository","url":"https://github.com/example/repo","cubox_id":"9001"}
  ]
}
```

`strategy/rationale/coverage` 是开放文字，`gaps` 是文字数组。一帖可对应多文章、多仓库，多帖可共用一篇文章。文章由 Agent 按目标规则编写或合并后登记；collection 仅在固定 destination 内回读真实 Markdown 和 hash，不改写目标。仓库必须提供直接 GitHub 仓库 URL 与真实 Cubox 卡片 ID，经 Cubox 当前数据核对存在和 URL；标题提及 GitHub、只有链接或没有保存的卡片均不能算仓库交付。仓库卡片不允许与来源 ID 重叠。

- `processed`：非空来源已实读、`complete=true`、`gaps=[]`、至少一个真实输出。
- `reviewed-no-yield`：来源文本非空，`source_sha256` 与 `read_sha256` 一致，`complete=true`、`gaps=[]`、`outputs=[]`，另须非空 `no_yield_reason`。Agent 在 `coverage` 中说明文字及媒体如何核对，例如完整阅读的未获回复投票、重复感叹确无新知识时使用，不为满足产物要求编空文章。无法取得来源、文字截断、关键媒体未读或无法访问时仍须保留缺口，不能使用此状态。CLI 校验字段与指纹，内容价值和媒体覆盖仍由 Agent 实读判断，不以关键词判断。
- `retain`：`complete=false`，保留来源。可以记录部分交付和缺口；要通过全批 ready 仍须有实际文本和相符的 `read_sha256`，不能用 retain 绕过未读来源。retain 永不进入删除集合。
- `confirmed-unavailable`：独立的远端不可用判断，必须 `complete=false`、非空 gaps、`outputs=[]`；不计为正文完整、已总结或有交付。还须附 `unavailable_evidence`：`code` 为 `NotFound/HTTP404/HTTP410`、同帖 `url`、具体 `reason`、带时区 `observed_at`，以及 `files` 的绝对 path/sha256 数组。文件须真实存在于 materials_root。`AuthorizationError`、超时和登录失败不能作为失效依据；有缓存正文时继续读取，否则保留并阻塞 ready。失效语义仍由 Agent 对照原始响应判断。

review 接受前会核对全部当前输出，verify 会再次核对实际文章、仓库以及本批尚未删除的 X 卡片身份。至多 100 个卡片使用 `card batch`；更多卡片使用当前 `card list --all` 与 `card list --archived --all` 的完整分页快照，按固定 ID 核对 URL 和文件夹，避免反复请求已保存的全文。快照中的纯文本收藏可以没有 URL，保留在快照中且不扩大本批范围；目标 X 帖子和仓库输出仍须逐项通过准确 URL 校验。快照读取失败、缺少真实 ID 或文件夹信息、URL 类型错误、ID 重复均停止，不使用旧缓存冒充当前状态，也不把元数据核验当作全文实读。整体 ready 要求每个冻结来源都有有效 review，未读或缺失来源阻塞。程序校验不能证明语义理解或价值覆盖。

status 只读取本地证据，不联网；返回来源数、status 数、待审阅 ID、当前 review 文件、最近 ready 记录、策略版本及清理状态。已保存的 ready 仅是上次核对结果；verify/cleanup 必须实时核对。所有任务操作沿用 workflow_state 的锁与原子写入，交付核对沿用共享目的地锁。

## 策略反馈与分类演进

```json
{"schema_version":1,"base_version":0,"strategy":"调整后的策略","rationale":"真实交付为什么支持调整","source_ids":["1001"],"rollback_to":null}
```

反馈必须引用已 `processed` 且输出当前可核验的来源，保存对应 review 文件/hash 和交付证据。`base_version` 必须等于当前版本；新版本单调递增，旧版本保留。回退时填当前 base_version、历史 `rollback_to`，strategy 必须与目标历史策略相同。集合策略只存私有任务区，不自动改全局规则。分类调整继续使用 [`knowledge library evolve`](library.md)，本入口不改分类、目录或文章。

## 授权清理与恢复

```json
{"schema_version":1,"reason":"当前用户明确授权的范围","delete_ids":["1001"],"unavailable_ids":[],"no_yield_ids":[]}
```

授权只接受固定集合内已经审阅的精确 ID。失效来源必须另列于 `unavailable_ids`，且该数组须精确等于 delete_ids 中的失效子集；默认缺失、retain 和未声明授权的来源全部保留。CLI 保存的是调用者提交的授权记录，不能代替人类授权。

`reviewed-no-yield` 只有另列在 `no_yield_ids` 中才允许删除，且该数组必须精确等于 `delete_ids` 中此 decision 的子集，不能缺少、重复或夹带其他 ID。`no_yield_ids` 可省略，旧契约省略时按 `[]` 校验，不重写历史授权；若旧授权后续把 review 改成无新知识，cleanup 会停止，须按适用的人类授权重新提交精确名单。此状态可通过全批 ready，但不是文章或仓库交付，也不能用于策略 feedback；feedback 仍只接受有真实输出的 `processed`。

cleanup 先要求全批 ready、核对当前 X 身份及 GitHub 目录保护，再对精确 ID 执行 `delete --dry-run --keep-empty-tags` 并校验完整 ID 列表。`--execute` 再实时核对，fsync 保存不可变意图后仅派发一次删除。不删仓库输出卡片，不清理标签，不清空回收站，不删除原始材料。

删除回执成功后仍分别用 `card list --all` 与 `--archived` 完整读取活动/归档列表，按固定 ID 对账，并核对保留来源和全部交付。完整列表由 Cubox CLI 自动分页；不以旧 URL 查无代替 ID 已删除，避免卡片改 URL 后误报。超时、中断、部分结果或读回失败标记 uncertain；后续 cleanup 只读对账，绝不重发。删除意图形成后冻结 review、策略与授权，不得通过更正数据另发删除。`cleaned` 仅表示固定删除名单已查无，不表示集合所有来源都被删除。测试和本地回执验证不代表真实内容交付。
