# 四套独立 Skill 插件

LoreLab 插件只分发 `lorelab`、`soota`、`cubox`、`mubu-integration` 四套独立 Skill、引用文档和本地 Agent 安装指引。不包含 CLI 源码、可执行文件、Python wheel 或安装包；不提供云端执行服务。

## 构建与加载

从本仓库已核对的源码生成：

```sh
python3 packaging/build_plugin.py --output-dir dist
```

构建直接读取四套 Skill 的主源和 Markdown 引用闭包，保留各组件许可证，生成 `plugin.json`、`skills/`、文档、`RUNTIME.md` 与 `lorelab-binding.json`。没有第二份手工维护的 Skill。涉及程序文件的引用转到运行指引，由 Agent 在已安装源码中定位。

通过 Agent 宿主支持的本地插件导入流程加载生成的 ZIP。宿主加载四套 Skill 后，首次需要 CLI 时，按照插件 `RUNTIME.md` 获取用户指定仓库并阅读 `docs/agent-install.md`，在本机执行源码安装。插件不会自动执行安装脚本。

插件模式安装和 setup 都加 `--no-skills`，避免另增全局注册；已有外部注册不自动删除。四个 CLI 始终可独立使用。源码安装与账号登录分别处理，不因安装而写入云端或删除收藏。

## 版本与更新

插件绑定源码内容指纹、组件锁 SHA256、四套 Skill 名称及插件文件哈希：

```sh
lorelab doctor --plugin-root /path/to/plugin
```

CLI 使用与插件匹配的源码版本；插件升级由宿主管理，CLI 更新由本地 Agent 运行 `lorelab update`。版本不符时先核对所选版本，不静默降级、不编辑宿主缓存。无远端的本地构建不会把私人路径写入插件，也不会猜仓库地址。

旧的 schema 1 插件绑定检查保留用于历史包；新插件采用 schema 2，需要从源码安装的新运行时。插件包验证与宿主实际导入、Skill 发现、账号可用分别验收。

## 系统与依赖

本地 Agent 必须能执行目标电脑上的命令。macOS 用 `install.sh`，Windows 用 `install.ps1`；同一套 Skill 按系统选择入口。Windows 不依赖 WSL。平台实现和实测范围见[安装说明](installation.md)。

格式依据：[插件结构](https://developers.openai.com/plugins/build/plugins)与[本地执行环境](https://developers.openai.com/plugins/deploy/desktop-only)。
