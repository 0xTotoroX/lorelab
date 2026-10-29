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

识别仓库时还要核对实际读到的图片、长文和带空格的地址，不能只用正文 URL 正则便宣称已经找全。图片中的地址须由实际视读确认；项目名没有真实地址时不猜仓库。旧地址若跳转到已有收藏，先用 GitHub 返回的仓库身份确认是同一个项目，再复用卡片并保留原标签、文件夹、标题、描述和已读状态。新增项目保存后，用活动及归档清单回读核对，再补入相关来源的交付记录。

- `processed`：非空来源已实读、`complete=true`、`gaps=[]`、至少一个真实输出。
- `reviewed-no-yield`：来源文本非空，`source_sha256` 与 `read_sha256` 一致，`complete=true`、`gaps=[]`、`outputs=[]`，另须非空 `no_yield_reason`。Agent 在 `coverage` 中说明文字及媒体如何核对，例如完整阅读的未获回复投票、重复感叹确无新知识时使用，不为满足产物要求编空文章。无法取得来源、文字截断、关键媒体未读或无法访问时仍须保留缺口，不能使用此状态。CLI 校验字段与指纹，内容价值和媒体覆盖仍由 Agent 实读判断，不以关键词判断。
- `retain`：`complete=false`，保留来源。可以记录部分交付和缺口；要通过全批 ready 仍须有实际文本和相符的 `read_sha256`，不能用 retain 绕过未读来源。retain 永不进入删除集合。
- `confirmed-unavailable`：独立的远端不可用判断，必须 `complete=false`、非空 gaps、`outputs=[]`；不计为正文完整、已总结或有交付。还须附 `unavailable_evidence`：`code` 为 `NotFound/HTTP404/HTTP410`、同帖 `url`、具体 `reason`、带时区 `observed_at`，以及 `files` 的绝对 path/sha256 数组。文件须真实存在于 materials_root。`AuthorizationError`、超时和登录失败不能作为失效依据；有缓存正文时继续读取，否则保留并阻塞 ready。失效语义仍由 Agent 对照原始响应判断。

review 接受前会核对全部当前输出，verify 会再次核对实际文章、仓库以及本批尚未删除的 X 卡片身份。至多 100 个卡片使用 `card batch`；更多卡片使用当前 `card list --all` 与 `card list --archived --all` 的完整分页快照，按固定 ID 核对 URL 和文件夹，避免反复请求已保存的全文。快照中的纯文本收藏可以没有 URL，保留在快照中且不扩大本批范围；目标 X 帖子和仓库输出仍须逐项通过准确 URL 校验。快照读取失败、缺少真实 ID 或文件夹信息、URL 类型错误、ID 重复均停止，不使用旧缓存冒充当前状态，也不把元数据核验当作全文实读。整体 ready 要求每个冻结来源都有有效 review，未读或缺失来源阻塞。程序校验不能证明语义理解或价值覆盖。

status 只读取本地证据，不联网；返回来源数、status 数、待审阅 ID、当前 review 文件、最近 ready 记录、策略版本及清理状态。`reviewed_source_count` 是已登记审阅的数量；`review_counts` 分别统计 processed、retain、confirmed-unavailable、reviewed-no-yield，`pending_source_count` 单列尚未审阅的数量。`retained_sources` 给出保留来源的收藏 ID、status ID、正文路径及原样缺口，不能把已审阅总数当成已提炼或可删除总数。已保存的 ready 仅是上次核对结果；verify/cleanup 必须实时核对。所有任务操作沿用 workflow_state 的锁与原子写入，交付核对沿用共享目的地锁。

清理前复查保留清单：区分真实缺失、采集失败与尚未处理的可读材料。媒体未出现在某读者的交接表，不证明原图或视频不可获取；回查冻结原始记录里的真实媒体地址和已有内容包，能补的先采集并审阅。已有媒体也可能只有低清图、局部抽帧或失败转写，保留具体证据边界。CLI 展示 Agent 的缺口记录，不按关键词自动闭合缺口，也不把文件存在当作已理解内容。

### 并行阅读、合并与后续增量

并行读者各自保存草稿和逐来源语义判断，按实际问题将相关草稿交给一位编辑。交接时冻结输入文件、指纹和来源集合，指定写入者；原读者后续发现的新来源另作增量，不能在编辑期间改掉交接依据。合并稿须将每个来源映射到有实质内容的段落，说明重复部分、其他主题的去向和仍缺的核心证据。编辑完成一项冻结贡献，不自动代表整帖完成；图片、音轨或引用长文的缺口继续由原来源审阅承担。

一份草稿可以按实际问题拆进几篇已有文章，几份草稿也可以归成一篇。记录应保留输入路径与指纹、具体来源 ID、各输出路径及指纹，不能假定一输入只对应一输出。相同内容或同源转述优先复用已有段落并补来源；只因文件名或路径不同不能重复导入，也不能只因出现同一个来源 ID 就丢弃它的另一项实质贡献。

修改旧文章前读取当前正文和指纹，保存可恢复的原件，再核对候选保留原文与人工修改；对全部目标完成预检后才写入。同一文章只有一个写入者。写入前再次比较预期指纹，写后回读实际字节；若原文已变，重新审阅差异，不能强制覆盖或另建同题副本。交付回执记录修改前后指纹和本次新增来源，阅读正文不混入私有台账路径或内部检查编号。

多个 review 可能引用同一篇文章。经过审阅的后续修改会使旧引用指纹失效，这是保护措施；下一次 review 须一并提交所有受影响的来源完整记录。只有实际文件仍与已审阅的新版本一致、且旧版到新版有可核对交付记录时，才更新引用；不要自动接受当前文件的任意新 hash，也不要重写旧 review 文件。集合提交与目标修改串行进行，避免核验期间文件再次变化。

较大批次可由另一位 Agent 逐篇复核新稿与增量，定向回读原始全文，并记录实际读过的文件指纹、发现和修正。复核结果绑定最终候选版本；作者修正后，只对变更稿补读并刷新凭据。主编辑可以据此完成合并与回读，但交付记录必须区分作者阅读、独立复核和主编辑抽查，不能将委派阅读写成自己逐篇读过。纯格式检查、来源计数和生成了草稿都不等于语义验收。

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
