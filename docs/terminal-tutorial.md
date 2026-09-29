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

## 4. 检查三个 Provider 的更新

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

更新安装在 Soota 自己的数据目录，不覆盖你现有全局 OpenCLI 或其中的本地补丁。若新程序与正在运行的 daemon 版本不同，Soota 会停止采集；先等已有采集结束，再运行 `soota runtime connect` 切换空闲 daemon，或直接 rollback。升级检查通过只证明 CLI 契约兼容，还应执行一次零预算 `inspect` 检查网站与扩展。

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

Obsidian 中的 `AGENTS.md` 可约定摘要格式、分类、引用和落盘位置，由 Agent 在写笔记前读取；Soota CLI 不解释该文件。通用 Skill 只说明工具使用方式，不能内置个人名单、私人知识库路径或账号资料。

项目外不等于不会上传：知识库、用户配置或云盘若另外开启同步，需要在各自的同步/Git 配置中排除私人名单、状态和采集结果。Git 忽略规则不会清除已经提交过的历史内容。
