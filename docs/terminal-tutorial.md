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

这是最近快照，最多 200 条，完整性未知。不能据此宣称已收齐历史，也不能 `jobs resume` 翻到更早帖子。`--max-cost 0` 禁止转入任何计费请求；浏览器采集仍需要本地运行时间和网络。

## 3. 读取或保存视频元数据

```bash
uv run soota inspect "https://www.bilibili.com/video/BV1M1421t7hT" \
  --provider auto --max-cost 0 --json

uv run soota ingest "https://www.youtube.com/watch?v=dQw4w9WgXcQ" \
  --transcript none --max-cost 0 --json
```

第一个命令返回标题、作者和已有元数据；第二个保存元数据 Markdown 内容包。`none` 只保存元数据；需要字幕时使用默认 `auto`，会先通过 OpenCLI 获取字幕。

确实愿意在免费元数据来源不可用时使用 TikHub，可明确给出兜底和费用上限（USD）：

```bash
uv run soota inspect "https://www.bilibili.com/video/BV1M1421t7hT" \
  --provider auto --fallback tikhub --max-cost 0.01 --json
```

TikHub 需要自己的 API Key。登录、验证码、限流和契约错误会停止，不会触发付费兜底。**这个 fallback 示例适用于已接入的元数据，暂不适用于 X 目录。**

视频字幕默认优先 OpenCLI，零预算即可尝试：

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

## 4. 更新 OpenCLI，不更新 Soota

```bash
uv run soota runtime check-update --json
# 按查询结果选择明确版本；此处 1.8.7 是本轮核实过的示例。
uv run soota runtime update --version 1.8.7 --json
uv run soota runtime status --json
# 如需恢复：
uv run soota runtime rollback --json
```

更新安装在 Soota 自己的数据目录，不覆盖你现有全局 OpenCLI 或其中的本地补丁。若新程序与正在运行的 daemon 版本不同，Soota 会停止采集；先等已有采集结束，再手动切换 daemon，或直接 rollback。升级检查通过只证明 CLI 契约兼容，还应执行一次零预算 `inspect` 检查网站与扩展。

完整边界和配置见 [Provider 与运行时](providers.md)，可续跑的 TikHub 视频目录见 [目录说明](catalog.md)。

## 查询全部功能与设置付款方式

```bash
uv run soota features list --site bilibili --json
uv run soota features show twitter.profile --json
uv run soota features call twitter.profile --param username=jack --json
uv run soota policy show --json
uv run soota policy set --mode ask
# 下面两个是可选设置，不要一起执行：
uv run soota policy set --mode auto --min-balance 5
uv run soota policy set --mode auto --no-balance-limit
```

ask 是初始默认值：OpenCLI 优先，每次 TikHub 收费前在终端询问 y/N。auto 会将省略 provider 时的默认来源改为 TikHub；预估扣费后余额触及阈值即暂停，或明确选择不限制余额。`--max-cost` 是额外上限，不会取消 ask 确认。完整能力范围、11 个重叠映射及原生功能操作见 [双运行时功能映射与费用策略](features.md)。
