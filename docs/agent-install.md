# 本地 Agent 安装指引

本页是 Agent 安装和更新 LoreLab 的操作入口。使用用户提供的本仓库地址和选择的版本，安装其绑定的四个 CLI / 四套 Skill。仓库没有地址时先取得实际地址；不要猜公开 URL 或分别安装原作者同名包。

## 首次安装

1. 检查 Windows / macOS、CPU 架构、Git 以及已有 `lorelab` 的实际路径。已有安装先运行 `lorelab doctor`，沿用原 prefix，不能为改名迁移它。插件安装先看[插件规则](plugins.md)。
2. 在用户可写、源码与配置分离的位置克隆仓库：`git -c core.autocrlf=false clone REPOSITORY CHECKOUT`。两个占位符替换为实际仓库和目录；不要重用非空目录、覆盖别人的 checkout 或关闭 Git 安全检查。用户指定 tag/commit 时检出该版本。Git 尚未安装时使用该系统官方安装渠道，登录或系统授权由用户完成。
3. 阅读目标仓库规则，核对组件锁。macOS 执行 `sh install.sh`；Windows 执行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1`。PowerShell 的执行策略参数仅影响此次进程，不改系统策略。
4. 安装器自动准备 uv、固定 Python 及需要的 Go，构建本地版本并注册四个入口。安装目录可用 `--prefix DIR` 指定；Skill 目录用宿主真实支持的位置，通过 `--skills-dir DIR` 显式传入。遇到同名外部内容停止并说明冲突，不能删除或强制覆盖。默认 `.agents/skills` 是否由当前宿主发现需要核对。
5. 用安装输出的绝对路径执行 `lorelab setup --non-interactive`。已有配置不用重填；新知识库仅在用户明确提供实际目录时添加 `--vault DIR --subdir 知识`。不要从私人开发路径推断目的地。插件模式安装和 setup 均加 `--no-skills`，不重复注册。
6. 执行 `lorelab doctor`、`lorelab skills list`，以及四个 CLI 的帮助/版本检查。再用临时本地文本运行 Soota context，核对原文与产物。命令成功与宿主发现 Skill、账号成功分别报告。

Git / 网络不可用时明确报错，不换到原作者发行包。不要为了安装自动写入幕布、操作收藏或修改现有任务。可选 yt-dlp、FFmpeg、字幕/转写工具由具体采集任务按 Soota Skill 准备；Downie 只在 macOS 可用。

## 更新与修复

正常更新：先 `lorelab update --check`，然后 `lorelab update`。这使用记录的仓库/分支，缓存 Git 对象并检出独立快照，不对用户 checkout 执行 pull/reset/clean。首次无来源记录时显式指定 `lorelab update --from CHECKOUT`，或 `lorelab update --repo REPOSITORY --ref REF`；采用明确选定的提交可用完整 commit SHA。

已有旧安装器不认识源码更新时，从新 checkout 再运行本机安装脚本并指定原 `--prefix`；现有注册目录从原安装记录读取。这是原位升级，不搬动已有 venv、配置或任务。

同一份源码重复执行会检查并复用，不重新下载或构建。`--force` 用于已确认的安装损坏，在新 release 修复。构建或检查失败保留原版本；保存具体错误并修复该问题，不能删配置或任务“重装”。

插件版本不符时先核对用户要采用的仓库版本；CLI 和插件需同版。使用宿主支持的刷新方式，不直接修改宿主缓存。插件目录中的程序链接用于定位已安装源码，不能把插件当作 CLI 运行包。

## 验证与交付

报告实际 OS/架构、来源提交/内容指纹、安装位置、四个 CLI / Skill、配置与任务保留情况。首次安装、重复安装、升级和失败恢复分别记录。macOS 的成功不等于 Windows 已实测；单元测试或交叉编译同样不能替代 Windows 安装运行。具体布局和恢复见[安装说明](installation.md)。
