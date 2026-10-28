# 知识图书馆与分类编码

知识图书馆把已提炼文章按主题归档。LoreLab 提供共享分类表、目录树、只读书目和归档校验；Agent 阅读来源与旧文，决定分类和合并。CLI 不调用模型，不用关键词替代语义判断。

## 初始化与检索

```sh
lorelab knowledge library init --vault /path/to/vault --subdir 知识
lorelab knowledge library tree --vault /path/to/vault --subdir 知识
lorelab knowledge library catalog --vault /path/to/vault --subdir 知识
lorelab knowledge library catalog --vault /path/to/vault --subdir 知识 --query 记忆
lorelab knowledge library catalog --vault /path/to/vault --subdir 知识 --category 06
```

已有 `knowledge init` 配置时可省略 vault/subdir。这三个命令不改目的地配置或删除授权。`init` 只新建 `分类体系.json`，不预建空目录、不移动旧文。重复运行保持相同文件的字节和修改时间；已有不同配置时停止。`--taxonomy FILE` 可选择首次初始化模板；现有分类调整由 Agent 审阅后编辑共享文件并递增 `version`。

默认模板有 12 个大类、62 个细分类，是可编辑的通用起点，不是 DDC 或中图法的正式分类号。层级设计参考 [DDC 介绍](https://www.loc.gov/aba/dewey/faq.html) 与 [LCC 学科大纲](https://www.loc.gov/aba/cataloging/classification/lcco/)，不复制完整分类表。

`tree` 返回分类表、编码对应的相对路径和文本树。`catalog` 返回文章标题、路径、类别、SHA-256、未编目文章、重复标题和跳过的软链接。`--query` 是文件名及正文的字面检索，`--category` 包含下级；不是语义搜索。旧目录的文章仍参与检索查重，不自动改动。隐藏目录、规则文件和配置排除的导航文件不作文章；不跟随软链接读取外部内容。

## 分类表

目的地的 `分类体系.json` 是共享分类正文。所有 Agent 读同一份；内置模板只用于首次初始化，升级不覆盖个人分类。

```json
{
  "schema_version": 1,
  "id": "my-library",
  "version": 1,
  "title": "知识图书馆",
  "exclude_files": ["知识索引.md", "图书馆目录.md"],
  "categories": [
    {"code": "06", "name": "计算机与人工智能", "scope": "计算、AI 与数字工具"},
    {"code": "06.04", "name": "人工智能与智能体"}
  ]
}
```

编码是字符串，每级两位数字，最多三级；父类别必须存在，编码不得重复，名称须能作跨平台目录名。编码表示类别，不是文章顺序号，已用编码不改作另一主题。目录按完整类别链生成，通常两级，按实际内容再细分。一篇文章只选一个主类别，跨学科关联通过正文链接、标签和 `related_categories` 表达，不复制正文。

按文章解决的问题分类：AI 辅助诊断的临床证据归医学，模型结构与训练归 AI。来源不全或尚未阅读时，“已归类”不表示“已完整提炼”。

## 文章流程接入

`knowledge prepare` 自动发现分类表，冻结到 `spec.json`，并保存 `library-catalog.json` 书目快照。回执 `library` 提供分类、路径与快照位置。Agent 实读规则、书目和相关正文，再填写原有 sources/notes 模板；未配置分类表时兼容原流程。

启用分类的批次中，notes 必须增加 `category`，可选 `related_categories`。以下仅是新增字段示例，不是完整 review：

```json
{
  "title": "多工具之间怎样增量同步记忆",
  "category": "06.04",
  "related_categories": ["00.01"],
  "relative_path": "06 计算机与人工智能/06.04 人工智能与智能体/多工具之间怎样增量同步记忆.md"
}
```

路径的父目录须与类别一致，文件名和正文标题须与 title 一致。Agent 提供正文并计算 body_sha256；CLI 不偷偷改写正文或属性。关联类别留在冻结审阅中，读者需要看到的关联仍写进文章。

提交和发布前重新读取现有文章：同标题或相同内容已在其他路径时停止；相同路径继续执行原有 hash 和独占创建检查。语义相似但标题不同的内容仍需 Agent 判断，不能宣称自动语义去重。受管写入者沿用目的地锁，人工及其他工具仍须遵守单一写入者约定。

准备后分类表发生变化时停止该任务，保留冻结证据，按新分类重新准备；没有绑定分类的历史任务按原契约恢复。分类校验不扩大删除范围，Cubox 清理仍需原有授权、完整性和交付回读门槛。初始化与导航生成不触发采集、删除、幕布或后台任务。

## 使用顺序

1. 读目标规则和分类表，检索相关旧文并实读。
2. 按问题选类别，多条来源可合成一篇，独立问题可拆文。
3. 使用 prepare → submit → publish → verify，首次归档才创建类别目录。
4. 已有同主题文章先审阅合并，保留人工内容，不换名绕过冲突。
5. 符合明确授权和完整性条件后才执行 Cubox cleanup，原始抓取文件不随卡片删除。

个人类别改共享配置，通用校验与工作流能力按实际需求迭代 LoreLab。升级不重导来源、不重建旧软链接、不重置人工分类。
