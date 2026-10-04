# Soota 终端参考教程

所有示例都从项目当前代码运行，避免终端里旧版 `soota` 与源码不一致。

## 1. 检查环境

```bash
cd /path/to/soota
uv sync --extra dev
uv run soota doctor --json
uv run soota runtime status --json
```

OpenCLI 需要 Node.js（上游 README 要求至少 20.18.1）、Chrome 和 Browser Bridge 扩展。你已有的全局 OpenCLI 可以直接复用；无需重新安装。先打开已登录目标网站的 Chrome，再在终端运行：

```bash
opencli doctor
opencli profile list
```

opencli-mcp 当前默认停用，无需安装或连接。

若有多个浏览器 profile，通过 `OPENCLI_PROFILE` 指定 `profile list` 中的别名或 context ID。Soota 不读取或导出浏览器密码。

## 本地转写引擎

Apple Silicon 可安装 `mlx-whisper==0.4.3`，在项目外的 `config.toml` 中选择 MLX：

```toml
[asr]
engine = "mlx-whisper"
model = "base"
mlx_whisper_bin = "/path/to/runtime/bin/mlx_whisper"
mlx_model_path = "/path/to/downloaded/whisper-base-mlx"
```

MLX 使用 Metal GPU 和 FP16，采用 greedy 解码，不使用原 Whisper CLI 的 beam search。`mlx_model_path` 指向含 `config.json` 和权重的模型目录；省略时 `base` 明确映射到 `mlx-community/whisper-base-mlx`，不会使用上游 CLI 的其他默认模型。其他模型需显式指定目录。运行环境和模型放在长期用户目录，不依赖实验或聊天目录。

`doctor --json` 的 `asr_engine`、`asr_model` 和 `mlx_whisper_cli` 可核对选择与命令是否存在。切回原命令行引擎时将 `engine` 改为 `whisper-cli`；`auto` 沿用原来的引擎选择顺序。MLX 命令的临时 JSON 输出在读取后清理，音频与转写缓存仍按现有规则保存。

引擎选择不改变 Provider 的费用策略，也不会自动补齐零预算无字幕下载与转写路径。已有转写缓存继续复用；验证新引擎时使用新的音频或缓存目录。

## 2. 零 API 费用获取最近帖子

将 `USERNAME` 换成 X 用户名，不包含 `@`：

```bash
uv run soota catalog "https://x.com/USERNAME" --provider auto \
  --max-items 50 --max-cost 0 --json
```

JSON 中的 `data.catalog` 是帖子数据文件，`data.content` 是可读 Markdown，`data.job_id` 是任务编号。输出默认在 `~/Documents/Soota/catalogs/任务编号/`。正文位于条目的 `text` 字段。

下次只保留没收录过的帖子：

```bash
uv run soota catalog "https://x.com/USERNAME" --max-items 50 \
  --max-cost 0 --incremental --json
```

这是最近快照：OpenCLI 最多 200 条，完整性未知。不能据此宣称已收齐历史，也不能 `jobs resume` 翻到更早帖子。`--max-cost 0` 禁止转入任何计费请求；浏览器采集仍需要本地运行时间和网络。

## 3. 读取或保存视频元数据

```bash
uv run soota inspect "https://www.bilibili.com/video/BV1M1421t7hT" \
  --provider auto --max-cost 0 --json

uv run soota ingest "https://www.youtube.com/watch?v=dQw4w9WgXcQ" \
  --transcript none --max-cost 0 --json
```

第一个命令返回标题、作者和已有元数据；第二个保存元数据 Markdown 内容包。`none` 只保存元数据；需要字幕时使用默认 `auto`，Bilibili 和 YouTube 都从 OpenCLI 开始。

确实愿意在免费元数据来源不可用时使用 TikHub，可明确给出兜底和费用上限（USD）：

```bash
uv run soota inspect "https://www.bilibili.com/video/BV1M1421t7hT" \
  --provider auto --fallback tikhub --max-cost 0.01 --json
```

TikHub 需要自己的 API Key。登录、验证码、限流和契约错误会停止，不会触发付费兜底。**这个 fallback 示例适用于已接入的元数据，暂不适用于 X 目录。**

视频字幕按已接入能力选择免费来源，零预算即可尝试：

```bash
uv run soota ingest "视频 URL" --max-cost 0 --json
```

以上零预算示例在字幕不存在时保留元数据。省略零预算时，默认 auto 会按付费策略处理 TikHub 兜底；也可显式 `--fallback tikhub --max-cost 0.05`。如需直接选择 TikHub：

```bash
uv run soota estimate "视频 URL" --provider tikhub --json
uv run soota ingest "视频 URL" --provider tikhub --transcript auto \
  --max-cost 0.05 --json
```

这里的 0.05 是示例预算上限，不是固定收费。

B站同作者同一期视频可选 YouTube 优先：

```bash
uv run soota ingest "B站视频 URL" --prefer-youtube --max-cost 0 --json
# 本次关闭跨平台查找：
uv run soota ingest "B站视频 URL" --no-prefer-youtube --max-cost 0 --json
```

开启时默认过滤已标注的推广。没有标注或身份无法确认时会明确报告，详见 [字幕选择与过滤](subtitle-selection.md)。

`--transcript auto` 确认没有字幕轨道后直接下载音频并本地转写；`captions-only` 不转写，`asr` 跳过字幕查询，`none` 只获取元数据。空响应、登录失败和未知状态不会被当成确认无字幕。

音频默认用 yt-dlp。可显式添加 `--audio-provider downie`，或选择经费用授权的 `tikhub`；Downie 不参与字幕查询。Downie 必须先设置下载完成脚本，具体步骤及流程图见 [Provider 路由](providers.md#downie-可选音频接入)。`download_pending` 表示继续检查原 Downie 任务，不能重复提交下载。

安装好 yt-dlp 后，YouTube/Bilibili 自动尝试 OpenCLI → yt-dlp。可单独使用 yt-dlp 方案：

```bash
uv run soota ingest "YouTube 或 B站视频 URL" --provider yt-dlp --transcript captions-only --max-cost 0 --json
```

默认读取 Chrome Cookie；用 `SOOTA_YTDLP_COOKIES_BROWSER` 选择浏览器/profile，设为空关闭。`SOOTA_YTDLP_BINARY` 可指定程序。JSON 返回实际 provider，内容包记录实际字幕语言和轨道类型。不会下载视频。

## 4. 三个外部 Provider 的自动更新

在线采集和接口调用前默认检查最新发布包，有新版就安装，通过入口验证后使用。无需每次手动操作。MCP 更新后仍停用；TikHub 的付款方式不受更新影响。首次安装需要 npm、Node.js 和 uv。yt-dlp Provider 适配代码随本项目更新，yt-dlp 程序由原安装工具维护。

```bash
# 立即检查并安装三个 Provider 的最新发布包
soota updates apply --json
# 暂时关闭自动更新；重新启用时改成 true
export SOOTA_AUTO_UPDATE=false
```

可以在用户配置 `config.toml` 中设置检查间隔：

```toml
[updates]
enabled = true
interval_seconds = 0  # 每次在线任务检查；3600 表示一小时
```

帮助、预估、离线预览和渲染不触发更新，Soota 退出后也没有后台更新任务。显式指定外部 binary 的 Provider 交由用户管理。自动更新会报告安装或兼容性错误；查看 `runtime_updates` 和 warnings，不要把检查完成当作全部安装成功。下列命令只读查询版本与仓库变化：

```bash
uv run soota updates check --json
```

结果分别给出本机版本、npm／PyPI 最新包版本和上游主分支相对本机版本标签的提交关系。`package_update_available` 表示有较新的包版本；主分支 `ahead` 只表示有新提交，`diverged` 表示提交历史已分叉，都不能直接当作可安装的新版本。网络查询失败会返回 partial 和退出码 2；命令不会安装更新，也不会同步私有备份。

OpenCLI 仍可单独升级和回滚：

```bash
uv run soota runtime check-update --json
# 省略版本号，即查询并安装最新稳定版。
uv run soota runtime update --json
uv run soota runtime connect --json
uv run soota runtime status --json
# 如需恢复：
uv run soota runtime rollback --json
```

更新安装在 Soota 自己的数据目录，不覆盖你现有全局 OpenCLI 或其中的本地补丁。自动更新可切换空闲 daemon；若仍有任务会延期。手动升级后版本不同则停止采集，先等已有采集结束，再运行 `soota runtime connect` 切换空闲 daemon，或直接 rollback。升级检查通过只证明 CLI 契约兼容，还应执行一次零预算 `inspect` 检查网站与扩展。

完整边界和配置见 [Provider 与运行时](providers.md)，可续跑的 TikHub 视频目录见 [目录说明](catalog.md)。

## 查询任务能力与设置付款方式

```bash
# 查阅上游 OpenCLI
opencli list -f json
uv run soota features list --site bilibili --json
uv run soota features show twitter.profile --json
uv run soota features call twitter.profile --param username=jack --json
uv run soota policy show --json
uv run soota policy set --mode ask
# 下面两个是可选设置，不要一起执行：
uv run soota policy set --mode auto --min-balance 5
uv run soota policy set --mode auto --no-balance-limit
```

ask 是初始默认值：按能力先试 OpenCLI，轮到 TikHub 收费前在终端询问 y/N。auto 只改变 TikHub 的付费授权，不改来源顺序；预估扣费后余额触及阈值即暂停，或明确选择不限制余额。`--max-cost` 是额外上限，不会取消 ask 确认。现有业务入口和 TikHub 封装见 [功能入口与费用策略](features.md)。

## 个人资料与知识库规则

个人路径、浏览器 profile 和凭据通过环境变量传入。终端会话或项目外的私人 shell 配置保存实际值；不要将这些值写入仓库、共享 Skill、日志或聊天。下列示例只有占位值：

```bash
export SOOTA_OUTPUT_DIR="/path/to/private-vault/收件箱/Soota"
# 仅在需要覆盖默认路径或选择浏览器上下文时设置：
export SOOTA_CONFIG_DIR="/path/to/private-soota-config"
export OPENCLI_PROFILE="PROFILE_ALIAS"
```

还支持 `SOOTA_CACHE_DIR`、`SOOTA_DATA_DIR`、`SOOTA_OPENCLI_BINARY`、`SOOTA_OPENCLI_MCP_BINARY`。TikHub 凭据使用 `TIKHUB_API_KEY`；不要把真实值写在共享示例中。已有项目外的 `config.toml` 继续兼容，环境变量优先覆盖对应字段。

个人关注名单和执行规则是结构化资料，应保存在项目外的私人文件中；环境变量只保存需要传递的路径或配置值，不把整份名单塞入环境变量。当前 Soota 尚没有名单管理、定时追踪或规则执行命令，不会自动读取名单文件。

Obsidian 中的 `AGENTS.md` 可引用本地处理规则和 prompt，约定文章整理、分析格式、分类、引用和落盘位置。Soota Skill 指导 Agent 在处理前读取这些文件，并在明确要求分析或文章处理时读取所选 prompt 的最新内容；CLI 不解释这些文件。个人名单、规则正文、私人知识库路径与账号资料不写入共享 Skill。面向阅读的来源名称可自定义，命令标识和 CLI 管理的内容包路径仍遵循原有契约。

项目外不等于不会上传：知识库、用户配置或云盘若另外开启同步，需要在各自的同步/Git 配置中排除私人名单、状态和采集结果。Git 忽略规则不会清除已经提交过的历史内容。

## Context 与可选文章

视频 ingest 默认输出 `context.md`、`transcript.md` 和 `manifest.json`，不调用模型润色，也不生成阅读文章。JSON 的 `data.context` 是正文路径；旧 `data.content` 在 ingest 中指向同一路径。目录命令不受此变更影响。

只要求采集时到 context 结束。要求分析／总结时，Agent 直接使用 context；明确要求详细文章阅读时才整理完整文章。标准 Analysis JSON 可用 `soota render` 排版为 `content.md`，已有文件需明确 `--force` 才替换，源 context 与字幕保持不变。格式能力与优先级见 [字幕格式与 context](subtitle-formats.md)。
