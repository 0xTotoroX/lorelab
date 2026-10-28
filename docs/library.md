# 自适应分类

分类从实际文章和使用反馈中形成。默认从空分类开始，名称短、边界清楚、一层优先；只有内容混杂或查找确有困难时才拆分。分类不是学科全表，也不靠增加类别数量证明改进。

当前 Agent 负责读文章、理解反馈和决定归属；LoreLab 自动分配稳定编码与显示序号，检查影响，应用调整并保存回退证据。整个流程不另调语言模型，不默认运行后台任务。自动化发生在 Agent 的实际整理任务中，不是一个无人运行也会自行学习的进程。

## 开始使用

```sh
lorelab knowledge library init --vault /path/to/vault --subdir 知识
lorelab knowledge library tree
lorelab knowledge library catalog --query 记忆
```

已有 knowledge 目的地配置时可省略 vault/subdir。init 新建空的 schema v2 `分类体系.json`，已有分类原样保留；不会覆盖人工修改，不创建空类别目录，不搬旧文。`--taxonomy FILE` 只供明确采用已有方案时使用。旧 schema v1 固定分类仍可读取，不自动迁移旧任务。

分类身份、显示名称、排序和文件路径独立：

- `K0001` 等稳定编码由程序分配，不随改名或排序改变，退役编码不重用。
- `分类编号.json` 保存已分配范围，回滚分类也保留它，避免旧任务误认新类别；迁移知识库时一并保留，不手动回退或删除。
- `01`、`02` 等显示序号按当前排列自动生成，不写进文件名。
- 类别使用短名，例如“工具”“学习”“饮食”；具体边界用 scope 说明。
- 新类别的目录使用语义名称。既有目录路径保持稳定；旧文通过文章归属映射重新编目，文件及链接不搬动。

这个分离参考 [SKOS 对概念、标签、编码、关系和有序集合的区分](https://www.w3.org/TR/skos-reference/)，不要求引入 RDF 数据库，也不宣称实现完整 SKOS 标准。

## 反馈闭环

遇到新主题、未归类文章、找不到资料、类别混杂或用户纠正时，Agent 主动执行：

```sh
lorelab knowledge library evolve prepare --feedback '分类简短，按实际需要组织'
# JOB 为实际返回路径；Agent 实读 observed.json、相关正文并填写 review-template.json
lorelab knowledge library evolve preview JOB --file /path/to/review.json
lorelab knowledge library evolve apply JOB --file /path/to/review.json
lorelab knowledge library evolve status JOB
# 需要撤回且没有后续冲突时：
lorelab knowledge library evolve rollback JOB
```

新来源尚未归档时，prepare 可加 `--context /path/to/source-or-draft.txt`，将本批材料冻结为分类依据。反馈和任务证据默认留在知识库外的 LoreLab 状态目录；`--state-root` 可明确指定其他私有位置。

每轮先观察真实文章清单、文件 hash、当前分类及用户反馈。Agent 提交类别、排序和归属调整，说明实际理由；程序不根据关键词假装完成语义分类。没有新需求或问题时不改分类，不为执行闭环而强行改名、拆分或重排。

审阅 schema：

```json
{
  "rationale": "现有文章集中于工具操作，先建立一层短分类。",
  "categories": [
    {"key": "new:tools", "name": "工具", "parent": null,
     "scope": "软件和设备的使用方法", "evidence": ["旧目录/文章.md"]}
  ],
  "assignments": [
    {"path": "旧目录/文章.md", "category": "new:tools", "reason": "正文主要是操作方法"}
  ],
  "unassigned": []
}
```

categories 是本轮完整类别表，数组顺序表达排序。已有类别用当前 K 编码作为 key，新类别用 `new:短名`，parent 引用同表 key 或 null。每类 evidence 须引用本次观察中的文章路径，或实际提供过的 `@feedback`、`@context`。条目少不强制合并，条目多也不强制拆分，应以检索用途和内容边界判断。

assignments 和 unassigned 是增量调整，不重复填写未变归属。unassigned 项只含 path/reason，在共享表中保存为空归属，优先于旧目录推断，后续审阅继续保留。退役类别仍有文章时，必须明确给出新归属或暂不归类理由，不能悄悄丢失分类。合并与拆分类别不合并、拆分或删除文章正文；正文编辑仍走原有授权及校验流程。

## 应用、恢复与评价

preview 显示分类数、归类覆盖、变更量和目录树，不修改共享文件。apply 更新共享分类及 `图书馆目录.md` 的文章导航，逐项核对并回读；不移动正文、不创建软链接、不删来源。原文集合、内容、分类或导航被其他人修改时停止，保护现场。

每轮保留应用前后内容和冻结方案。重复 apply 不重写相同文件，不重复分配编码；中途失败后用同一 JOB 的 apply（省略 --file）恢复。不同审阅不能替换已冻结方案。rollback 按原字节恢复本轮分类及导航文件（包括换行与 BOM），保留编号分配记录；若后续修改已发生则停止，不覆盖它们。status 是本地检查，不联网、不自动重试。

无实际分类变化时不增加分类版本。覆盖数只能证明有多少文章已归类，不能证明分类质量；应用后由 Agent 用真实查找问题检查是否容易找、是否边界混淆，并把后续纠正带入下一轮。没有实际使用记录时不得编造“高频主题”或“检索效率提升”。

## 与文章归档衔接

knowledge prepare 继续冻结分类及书目。schema v2 的分类任务允许后续新增类别或调整显示顺序；提交时读取当前有效分类，检查所用类别未退役、既有存放路径未改变。新文章写到类别目录，已有文章按归属映射保留原路径。旧 v1 任务保持原有严格冻结语义。

notes 必须提供稳定的 `category`，可选 `related_categories`，其他来源、正文及证据字段沿用知识流程。同标题跨目录、同批相同正文和人工修改保护继续有效；同主题不同标题仍由 Agent 实读判断。整理完成后检查有无新分类反馈；没有问题就结束，不另加周期任务。

分类调整不更改 Cubox 删除授权、来源完整性门槛或幕布流程。个人偏好维护在目标知识目录；通用功能缺口才按实际需要迭代 LoreLab 代码、测试及 Skill。
