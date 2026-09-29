# 字幕来源选择与推广过滤

默认只采集输入链接对应的视频。B站输入可开启 `--prefer-youtube`；`--no-prefer-youtube` 关闭，本次命令优先于配置。

```bash
soota ingest "B站视频 URL" --prefer-youtube --max-cost 0 --json
soota ingest "B站视频 URL" --no-prefer-youtube --max-cost 0 --json
```

持续开启可设置环境变量 `SOOTA_PREFER_YOUTUBE=true`，或在项目外的 Soota `config.toml` 中配置：

```toml
[content_selection]
prefer_youtube = true
```

## 如何选中 YouTube 视频

通过 OpenCLI 搜索同名频道（最多 5 个结果），读取频道信息，再搜索同一期视频（最多 5 个结果）。同名检索后，自动选中还需要：

- 唯一同名频道，视频的频道 ID 与其一致。
- 标题中的明确集数、期数或数字不冲突，标题相近、发布时间相差不超过 14 天，时长差不超过 120 秒或 B站时长的 20%（取较大者）。

匹配唯一且有字幕才采用 YouTube。跨平台简介链接会记录为补充依据；没有原 B站指向 YouTube 的链接时，`author_crosslink_confirmed=false`，不把名称匹配称为官方身份认证。名称不同、候选不唯一、同一期不匹配或没有字幕时保留 B站来源，并在 `youtube_check` 记录原因。它不是完整频道搜索；标题差异较大时，需要 Agent 确认后直接使用 YouTube 链接。可选 YouTube 搜索发生普通来源错误时记录 `failed` 并继续原 B站字幕，不重试该 YouTube 请求；登录、限流和契约错误仍停止。故障不等于“没有同名账号”。

采用 YouTube 后，内容包放在 `youtube/视频ID/`，字幕保留 YouTube 时间轴；`selection.requested_source` 保留原 B站链接和选择依据。不会把 B站时间戳套到另一版本的视频上。

本开关用于 OpenCLI 免费字幕路径；显式 TikHub 或 `--transcript asr` 会覆盖保存的免费字幕偏好，同时明确传入跨平台/过滤参数则提示不支持；跨平台/过滤任务不会自动转入付费采集。`--transcript none` 只取元数据，不搜索字幕来源。

## 排除推广片段

开启 `--prefer-youtube` 时默认启用推广过滤；也可独立使用 `--exclude-promotions`，或用 `--keep-promotions` 保留全部字幕。

YouTube 使用 SponsorBlock 的 `sponsor` 和 `selfpromo` 社区标注。请求只发送视频 ID 的 SHA-256 前 4 位，在本地匹配完整 ID。没有标注、服务不可用或标注时长不符时会记录状态，**不代表视频没有推广**。B站没有接入自动广告标注。

用户或 Agent 复核后可以补充秒数区间：

```bash
soota ingest "视频 URL" --exclude-promotions --exclude-range 113:208 \
  --exclude-range 900.5:924 --max-cost 0 --output /path/to/new-output --json
```

与区间重叠的整条字幕会被排除，边界可能带走同一句中的少量正文。原文保存为 `transcript.original.md`，筛选结果为 `transcript.md`，片段 ID 和时间戳不重排。Manifest 记录区间、被排除的 ID、标注来源和 `review_required`；摘要只应使用筛选结果，Agent 仍需检查未标注的口播推广。

已有内容包改变过滤结果时，需要新输出目录，或明确使用 `--force` 重建，防止旧总结引用被移除的片段。渲染总结保留原字幕文件的登记。

SponsorBlock 标注数据采用 [CC BY-NC-SA 4.0](https://github.com/ajayyy/SponsorBlock/wiki/Database-and-API-License)，输出保留署名；该数据的非商业和相同方式共享要求不因 Soota 采用 Apache-2.0 而改变。原视频字幕不由此获得新授权。
