# 从仓库安装、更新与恢复

LoreLab 由本地 Agent 从用户选择的 Git 仓库安装。四个 CLI 与四套 Skill 都来自本仓库和 `components.lock.json`，不要求维护者发布安装包。Agent 的完整步骤见[安装指引](agent-install.md)。

## 入口与平台

| 平台 | 源码目录中的入口 | 运行布局 |
| --- | --- | --- |
| macOS arm64 / x64 | `sh install.sh` | shell 入口、venv/bin、符号链接 |
| Windows x64 / arm64 | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1` | 原生 exe、venv/Scripts、目录 junction |

安装器按本机 OS / CPU 构建，不能把 Mac 的二进制或 venv 搬到 Windows。Windows 入口无需 WSL、管理员 symlink 权限或开发者模式；本地文件系统须支持目录 junction。macOS 使用现有原子 current 切换；Windows 在安装锁内更名 junction，切换失败恢复旧入口，切换瞬间其他调用可能需要重新执行。

源码首次安装与升级已在 macOS arm64 实跑。Windows 分支与原生命令交叉编译已检查，尚未在真实 Windows 或 Intel Mac 完成安装验收；仓库提供 Windows / macOS 的 CI 验证入口。账户登录另行验证。Downie 仍仅适用于 macOS；Windows 外部 yt-dlp 下载和 FFmpeg 转换当前因无法保证硬文件字节上限而停止，详见 [Soota 平台边界](../modules/soota/docs/providers.md#windows-运行)。

```sh
sh install.sh --prefix /path/to/lorelab --skills-dir /path/to/agent-skills
```

Windows 使用相同的 `--prefix`、`--skills-dir`、`--bin-dir`、`--no-skills`、`--no-bin`、`--force` 参数。默认 prefix 是用户目录下 `.local/share/lorelab`，命令注册至 `.local/bin`，Skill 注册至 `.agents/skills`。指定目录不覆盖外部同名内容。`--no-skills` / `--no-bin` 跳过新增外部注册，不撤销已有注册。

## 工具链与重复执行

入口复用已有 uv / Go；缺失时从固定官方地址下载到 prefix/toolchain 并校验 SHA256。固定 Python 为 3.12.12，uv 引导版本为 0.9.26，Go 引导版本为 1.27.3；已装 Go 满足组件 go.mod 最低版本时复用。Git 用于获取仓库，需要由本地 Agent 按系统已有安装方式准备。引导不更改系统 Python、Go 或 shell 配置。

Python 依赖使用跨平台、带哈希的版本锁，在本机构建 wheel；产品和 Soota 始终从本地源码构建，Cubox 按本机目标执行 Go build。crcmod 等依赖允许源码构建及其纯 Python 回退。下载、pip wheel、Go module/build 缓存归 toolchain，多 release 共用；每个 release 使用独立 venv。

相同源码内容会先校验已装源码和四个 CLI，再复用 current、补齐记录中的缺失注册，不下载或重新构建。新内容在独立 release 构建，通过依赖检查、帮助/版本调用和组件指纹核对后激活。失败保留旧 current、配置、任务和 release。

安装记录保存已登记命令/Skill 目录和 Git 来源。不要单独删除 toolchain/python，新版 venv 依赖它；不要搬动已安装 prefix 或 release，其中含绝对路径。

## 首次设置

按安装输出的完整路径调用：

```sh
lorelab setup
lorelab setup --non-interactive --vault /path/to/KnowledgeVault --subdir 知识
lorelab doctor
lorelab skills list
```

setup 原位沿用知识配置，仅合并显式字段，保留未知字段、原删除授权和旧任务门槛。没有变化就不改配置字节或修改时间。更换幕布文档会清除旧父节点绑定；`--mubu-parent` 可显式指定新节点，空字符串为根节点。新配置默认保留收藏。

macOS setup 向 zsh `.zshrc` 或 bash `.bash_profile` 追加带标记 PATH；Windows 更新当前用户的 PATH，并生成 `env.ps1` 供当前 PowerShell 加载，不改机器级 PATH。已有其他配置保留；`--shell-profile none` 跳过路径设置。Windows 设置成功后通知桌面进程，现有终端或 Agent 仍可使用完整路径，或加载 `env.ps1`。

账号检查需显式 `--check-accounts`，只读 Cubox 文件夹及已配置幕布的认证状态，不登录、不打印凭据、不执行云端写入。安装成功与账号成功分别报告。

## 从仓库更新

```sh
lorelab update --check
lorelab update
lorelab update --from /path/to/selected-checkout
lorelab update --repo REPOSITORY --ref REF
```

普通 update 使用首次源码安装记录的仓库与分支；独立 Git 缓存位于 prefix/toolchain/repositories。获取候选提交后导出临时源码快照，不对用户工作区执行 pull/reset/clean。`--check` 获取和核对源码，不构建、不切换。指定本地 checkout 时使用其当前受追踪文件内容；未纳入 Git 的新源码文件须先 git add。

`--repo` 接受实际 HTTPS / SSH 或本地 Git 仓库，凭据交给 Git 凭据管理器。`--ref` 可为分支、标签、提交；未传时沿用记录。未配置来源则明确报错，不猜发布 URL。无远端的开发仓库会记录实际本地路径，其他电脑需取得自己的可访问仓库地址。

新安装器随仓库更新，使用受信候选源码的安装器完成本次升级。相同内容复用，`--force` 在新 release 修复；旧版本和用户数据保留。普通 Skill 注册随 current 切换；插件 Skill 由宿主更新，须通过 `doctor --plugin-root` 核对同版，见[插件说明](plugins.md)。

## 旧安装与恢复

旧版只认识 tar.gz 更新时，从新 checkout 再执行安装脚本并指定**原 prefix**。它会读取旧注册记录，在原位置创建新 release；无需搬迁配置和任务。`lorelab update --from 旧安装包.tar.gz` 与旧 `setup --update-feed` 接口保留兼容，已配置的旧 feed 仍可显式使用 `--feed`；新安装默认采用仓库来源。

旧发行包工具 `packaging/build_release.py` 继续保留供已有流程使用，不是普通用户安装前提。历史 schema 1 bundle 仍校验平台、文件哈希和模式；新插件不携带此类包。

失败先检查错误、工具链和网络，不删配置或重建任务。回退选择 prefix/releases 中核对完整的旧版本：macOS 通过临时链接和 os.replace 切回 current；Windows 持安装锁把 current junction 更名备用，创建目标 junction，失败恢复原 junction。旧 release 内绝对路径不变。已经写入的知识和云端内容不随软件回退。

### 从 LoreHub 升级

历史 prefix 名称和数据路径保留；`lorehub` 命令与 Skill 已移除。旧知识任务继续用 `lorelab knowledge/study` 和原 JOB 路径；旧 `soota knowledge/study` 仅转发到已安装 LoreLab。新旧运行时变量一致注入，配置优先级见[知识流程](knowledge.md#配置独立组件与兼容入口)。升级不放宽历史清理授权，也不恢复旧名称命令。

## 维护者验证

修改组件及 Skill 后核对并刷新组件锁；新增源码先纳入 Git。安装器校验源码指纹，不会自动刷新锁来掩盖差异。

```sh
uv run --frozen pytest -q tests
uv run python -m lorelab.cli components verify
python3 packaging/build_plugin.py --output-dir dist
```

运行依赖锁采用 `uv pip compile --universal --generate-hashes --python-version 3.12`，输入为产品 pyproject、Soota pyproject 与幕布 requirements.in，并 `--no-emit-package soota`，产品和 Soota 另从源码构建。具体安装、重复执行、升级和数据保留须通过独立用户目录验证；单元测试不代表账号或真实云端交付。

独立用户目录验收入口为 `python tests/integration_source_install.py --workdir acceptance --system-path`；Windows 可再加 `--windows-code-page 936`。它保留系统工具和 Git，排除预装 uv / Go，以包含中文、空格和特殊字符的路径实跑安装、重复执行、本地 context、Git 升级与失败恢复，并比较配置和任务文件。输出留在指定的新目录，不操作真实账号。`.github/workflows/source-install.yml` 在 macOS 和 Windows 运行此流程；未实际运行的 CI 不作为通过证据。

实现依据：[uv 私有安装](https://docs.astral.sh/uv/reference/installer/)、[Python venv 平台布局](https://docs.python.org/3.12/library/venv.html)、[Windows 文件锁](https://docs.python.org/3.12/library/msvcrt.html)、[Go 官方安装](https://go.dev/doc/install)。
