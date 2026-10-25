# 组件单主源同步与统一发布

Cubox、Soota、幕布的源码和完整 Skill 只在 LoreLab 的对应 `modules/` 目录修改。三个独立仓库保留各自历史并接受单向生成的提交；独立安装和 LoreLab 成套安装使用相同组件。源码同步覆盖三个组件，配对版本发布仍只覆盖 LoreLab 与 Soota，不自动发布 Cubox 或幕布的标签、Release 或 npm 包。

## 日常修改与自动同步

1. 修改 `modules/cubox-cli/`、`modules/soota/` 或 `modules/mubu-cli/` 内的源码、测试、文档和 Skill，运行受影响检查。
2. 运行 `lorelab components refresh --source /path/to/lorelab`，审查 diff 后提交。显式指定开发主源，避免把已安装的受管快照当作编辑入口；刷新指纹不代表发布新版本。
3. 启用 GitHub 工作流后，推送 `main` 中相关改动会运行组件、Skill、同步边界与对应组件测试，通过后执行 `components sync NAME`。主源必须是干净、已提交且指纹一致的 LoreLab checkout。

手动执行同一个入口可预览或恢复；预览获取远端状态并创建临时 Git 对象，不写入目标仓库或用户工作区：

```sh
lorelab components sync cubox --source /path/to/lorelab
lorelab components sync mubu --source /path/to/lorelab
lorelab components sync soota --source /path/to/lorelab
# NAME 为 cubox、mubu 或 soota；已授权写入时：
lorelab components sync NAME --source /path/to/lorelab --execute
```

默认目标与导入基线来自 `components.lock.json.components[NAME]`。`--repository` / `--branch` 可指向隔离验收仓库；默认分支为 `main`，也可在组件条目的 `sync.branch` 设置。需要调整首次基线时显式审阅并记录 `sync.initial_revision`，不改写历史导入 `revision`。

源文件必须实际属于当前提交。导出复用组件文件闭包，附带 `lorehub-provenance.json`：原导入提交、当前组件指纹、主源提交、各文件 hash/mode 和 Skill 路径。提交以对应组件的原历史为父，使用普通快进推送；不 force push、不创建第二套采集实现、不改独立 checkout。未改组件的产品提交不产生额外同步提交。

后续同步核对组件名称、前次回执、文件、权限和主源祖先关系，防止把一种组件写入另一种组件的受管仓库。独立仓库出现直接修改、并发分歧或较旧流水线试图覆盖新来源时停止，保留现状。先审阅并把有效修复带回主源，再处理发行分支；不要通过重新设置首次基线或删除回执跳过检查。

## 一次准备两包版本

LoreLab 与 Soota 可采用不同版本号。以下数字为示例：

```sh
lorelab release prepare --source /path/to/lorelab --version 0.2.0 --soota-version 0.1.1
```

该命令更新两个 `pyproject.toml`、两个 Python 版本入口、两个 uv 锁中的对应本地包版本，以及组件锁的版本和指纹。组件原始导入版本可保存在 `import_version`，`revision` 始终保留导入来源。它不更新依赖、不提交、不推送、不安装；非法版本、倒退或原有元数据不一致时停止，写入失败恢复本轮修改。只接受 `X.Y.Z`，不要求两包升到同一个数字。

审查并验证后提交；开发中可以只同步源码，正式发布前必须确保改变过的已发行组件使用新版本。已存在的标签不得指向另一份内容。

## 配对发布与恢复

先将已审阅的 LoreLab 提交推送到它的发行分支，再预览配对发布：

```sh
lorelab release publish --source /path/to/lorelab --repository LORELAB_GIT_URL
# 确定发布范围后使用同一参数加 --execute
lorelab release publish --source /path/to/lorelab --repository LORELAB_GIT_URL --execute
```

主源、Python 版本、uv 锁、组件锁以及两个目标标签须全部通过预检。然后同步 Soota 并在同一次 Git 原子推送中创建其分支/`vX.Y.Z` 标签，回读通过后创建 LoreLab 的对应标签。JSON 回执绑定两包版本、LoreLab 提交、Soota 提交和组件指纹。

两个仓库之间没有原子事务。一边完成后另一边失败，重跑同一提交、相同版本和目标：已有提交及标签会核对复用，继续未完成部分。Soota 标签已建立后，即使后续开发使两个主分支前进，恢复也按固定标签核对旧源码与 Skill，只补缺失标签，不回退分支；原 LoreLab 提交须仍是发行分支的祖先。不要删标签、强推、自动回滚已经发布的仓库或另升一版来掩盖未知结果。若远端状态与预期不符，先只读核对。

GitHub 的 **Publish LoreLab and Soota** 工作流在选定提交上运行验证、构建纯 Skill 插件、调用配对标签入口，再根据两份已审阅说明创建两个 GitHub Release。插件附件只进入 LoreLab Release；Soota 通过独立源码/tag 继续安装。不存在运行安装包或自动 PyPI 发布。

已有 Release 的标题、正文、标签和附件必须一致，不能覆盖；草稿通过有权限的 Release 列表回读，尚未完成的草稿或缺失附件可以继续。插件必须匹配回执的已提交主源、源码指纹、组件锁与版本，同一版本已有其他指纹的插件时停止。ZIP 使用固定文件时间与权限，同一源生成相同字节，便于恢复时比对。JSON 回执作为 workflow artifact 保存；本地回执写到仓库外，避免污染干净源码。

## 首次接线

- 为 LoreLab 配置真实可访问的 Git 远端，不从产品名猜测发布地址。
- 首次组件目标可以等于导入基线，或是该基线的祖先。后者要求原历史已完整接入 LoreLab 提交图，才能保留原仓库尚未推送的提交。先审查历史内容，在干净源码上 fetch 原仓库后用 `git merge --strategy=ours --allow-unrelated-histories --no-ff` 保留其历史；核对合并前后产品 tree 完全相同。仅在首次迁移且基线已核实时这样处理，不能拿它吞掉后续独立修改。
- 工作流 `checkout` 使用完整历史。主源中现存的 `sync-soota.yml` 与 `release.yml` 共用 `soota-distribution` 并发组，不中断执行中的发布。 `sync-components.yml` 分别运行 Cubox 与幕布任务，各有独立的并发组和密钥；一个任务失败不取消另一组件，已成功的提交不回滚。两组件相关路径或组件锁变化时会检查两者，组件未变则复用已有提交。
- 源码同步为三个仓库分别设置 `CUBOX_SYNC_SSH_KEY`、`SOOTA_SYNC_SSH_KEY`、`MUBU_SYNC_SSH_KEY`：分别生成专用 SSH 密钥，把公钥作为允许写入的 Deploy key 加到对应独立仓库，私钥作为 Actions Secret 加到 LoreLab 仓库。不要在多个仓库复用同一部署密钥；SSH 同步要求组件锁中的目标使用 SSH Git 地址。这把密钥只授权目标仓库；工作流核验 GitHub 主机公钥，结束后删除临时私钥文件。GitHub 更换主机公钥时，须经官方渠道核实后更新固定值。
- Soota 同步仍兼容 `SOOTA_SYNC_TOKEN`（Soota 仓库的 Contents 写权限），SSH Secret 存在时优先使用 SSH。统一发布工作流仍使用 `SOOTA_SYNC_TOKEN`，且需两个仓库的 Contents 写权限；仅配置部署密钥不会启用统一发布。若组件新增 `.github/workflows`，令牌按 GitHub 要求增加对应工作流写权限。私钥和令牌只放 GitHub Secrets，不写源码、地址、日志或 Skill，也不复制本机登录令牌。原生 `GITHUB_TOKEN` 不承担跨仓库写入。
- 如分支保护要求 PR 或禁止该身份直接写入，先配置允许的自动化身份/发行分支，不禁用保护来绕过拒绝。未提供认证时工作流明确失败，不报告已经同步。

主分支推送只同步源码，不创建 Release。正式发布由带审阅说明的 workflow dispatch 触发。首次远端创建、权限配置及在线工作流必须另有实际验收证据，本地测试不能代替它们。

## 验证

```sh
uv run pytest tests/test_component_sync.py tests/test_releases.py tests/test_release_versions.py tests/test_github_release.py
python tests/integration_component_release.py --workdir /path/to/new-acceptance-directory
```

集成脚本在隔离 HOME 和本地 Git 仓库中完成：保留原历史、修改唯一组件与 Skill、准备版本、同步、配对打标、独立安装升级以及 LoreLab 成套升级，核对两边源码/Skill 和已有配置任务；不会推送 GitHub 或写入 Cubox/幕布。Windows 原生验证以该平台实际运行结果为准。

实现采用 Git 的[指定父提交](https://git-scm.com/docs/git-commit-tree)与[普通快进和单仓库原子推送](https://git-scm.com/docs/git-push)，复用已有组件导出以保留源码/Skill 闭包。跨仓库权限参照 [GitHub Actions 认证说明](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token)。
