# 图片、文档附件与认证检查（1.4.0）

这些命令随 1.4.0 准备发布，尚未包含在既有发布包中。通过 `scripts/mubu_api.py` 运行；下文以已登录的桌面会话为例。命令默认 JSON 输出。

## 图片与附件的区别

- `image-upload`：上传 PNG/JPEG/GIF，追加到一个节点的 `images` 列表。保留原图片、正文、描述及其他属性，不自动压缩或转换。
- `attachment-upload`：上传文件，绑定到**文档级附件列表**；不接受节点 ID。幕布网页标题附近的文件入口可查看附件。
- 两种操作都需要 `--execute` 才上传。预览只读取本地文件、文档与必要的附件列表；不会上传文件或申请上传凭据。

```sh
# 只读检查，不打印 Token
.venv/bin/python scripts/mubu_api.py --auth desktop auth-status

# 图片预览，返回文件名、尺寸、SHA-256 与文档版本
.venv/bin/python scripts/mubu_api.py --auth desktop image-upload DOC_ID \
  --node-id NODE_ID --file diagram.png

# 按预览版本执行；上传期间版本变化会停止节点绑定
.venv/bin/python scripts/mubu_api.py --auth desktop image-upload DOC_ID \
  --node-id NODE_ID --file diagram.png --expect-version VERSION --execute

# 附件预览与执行
.venv/bin/python scripts/mubu_api.py --auth desktop attachment-upload DOC_ID --file reference.pdf
.venv/bin/python scripts/mubu_api.py --auth desktop attachment-upload DOC_ID \
  --file reference.pdf --expect-version VERSION --execute

.venv/bin/python scripts/mubu_api.py --auth desktop attachments DOC_ID
```

## 上传依赖

- [火山引擎 TOS Python SDK](https://github.com/volcengine/ve-tos-python-sdk)：幕布的文档附件使用 TOS 对象存储。SDK 用幕布返回的临时凭据完成签名和上传，无需用户另开火山引擎账号或配置自己的云密钥；不用于图片上传，也不调用 AI 模型。
- [Pillow](https://github.com/python-pillow/Pillow)：在本地校验图片格式、读取宽高，拦截损坏或异常尺寸的图片，不上传图片、不自动压缩或改图。

两者随 `requirements.txt` 安装；这里只说明实现用途，CLI 的操作方式不受影响。

## 大小、权限和格式

CLI 单文件上限为 50 MiB，这是本地明确限制，不代表服务端一定接受所有文件。图片还受 Pillow 像素安全检查限制；没有复刻网页版的自动压缩或会员画质处理。账户权限、容量、附件数量限制由幕布服务端决定，不绕过限制。

附件后缀采用当前官方前端列表：

`pdf doc docx wps wpt dot ppt pptx txt rtf md xls xlsx csv pages numbers keynote mm opml xmind epub mobi mp3 m4a wav aac flac ogg mp4 mov webm avi mkv psd ai sketch eps fig drawio vsdx zip rar 7z tar gz`

支持列表不代表每种格式都已实测。PNG/JPEG 图片与 TXT 附件已完成当前账号的真实上传验证；GIF 和其余附件格式只有相同协议与本地格式检查支持，尚未逐项验收。

## 阶段、失败与恢复

上传不是单次原子操作。图片先上传，再通过节点事件绑定；附件先上传到对象存储，再绑定文档。操作记录沿用 `~/.local/state/mubu-cli/operations/`（可用 `MUBU_STATE_DIR` 改位置），包括原文档快照、文件 SHA-256、已知的资源标识和阶段，不包含文件原始字节、幕布 Token 或 TOS 临时凭据。

| 状态/阶段 | 意义 |
| --- | --- |
| `preview` | 没有上传 |
| `conflict`，`executed: false` | 上传前检测到变化，没有上传 |
| `uploading` | 已记录 TOS 对象 key，上传已准备/尝试；实际结果需核实 |
| `uploaded_unbound` | 上传响应成功，尚未进入绑定步骤 |
| `binding` | 绑定已准备/尝试；不能由此认定已绑定或未绑定 |
| `bound` | 附件绑定返回 ID，正在核对列表和下载内容 |
| `verified` | 图片节点整篇读回通过；或附件列表和下载 SHA-256 核对通过 |
| `uncertain` | 已进入上传流程但没有完整核验，可能留有上传资源或已绑定内容 |

`uncertain` 退出 3，不能当成“没上传”。先看操作记录、`nodes --include-html`、`attachments` 和幕布网页。图片记录保存可用的图片引用与节点操作 ID；附件上传前即记录对象 key。图片上传接口在响应丢失时可能无法取得服务端生成的引用，这仍是恢复限制。

没有自动重试上传/绑定，没有自动回滚、删除孤立文件或附件删除命令。修改本地文件后重新上传是另一次操作，不会自动替换旧资源。操作日志写入失败会停止未开始的下一步，或在已完成后给出警告，不能因此盲目重试。

客户端版本检查不是服务端锁。附件绑定也没有原子版本条件；只用于个人串行操作。

## 认证边界

`--auth desktop` 复用本机登录。实测服务端对无效会话返回 `code: 2 / Login Expired`，现在会明确提示在幕布桌面端重新登录。测试使用了独立客户端内的合成无效 Token，没有使用户真实会话失效；因此这验证了真实拒绝响应及提示，不代表真实重新登录全过程已验收。

`auth-status` 会实际发起只读请求；密码模式可能按上游逻辑用已有凭据重新登录。它不会打印 Token，也不会为你接管桌面登录。

## 协议依据和验证

- 图片：官方编辑器公开资源中的 `upload_img_base64` 流程，返回引用后追加节点 `images`。
- 附件：官方网页的 TOS 临时凭据和文档附件 v4 API；使用官方 [TOS Python SDK](https://github.com/volcengine/ve-tos-python-sdk)，关闭其自动重试。
- 原始证据：[DocEditor](https://assets.mubu.com/DocEditor-995fdd7071535976.js)、[Outliner](https://assets.mubu.com/Outliner-c06bc304cb81108b.js)、[App](https://assets.mubu.com/app-a10e6d5460e3486a.js)。资源可能更新，不能当成稳定公开接口契约。
- 实机测试仅使用独立验收文档和合成图片/TXT 文件。已核验上传、挂接、附件下载 SHA-256、图片和链接网页显示；已有文字节点未变化。
- 自动化：178 项在 Python 3.12 和 3.9 下通过；lint 与文档一致性检查通过。macOS 自带 Python 3.9 使用 LibreSSL，会产生 urllib3 兼容警告；联网实机验收使用独立 Python 3.12 环境。
- Mubu Sync 如何下载新图片或附件、Obsidian 中的显示和跨设备链接打开，本轮没有验证。

实现入口：`media.py` 处理上传和分阶段记录，`media_cli.py` 提供命令；`client.py` 保持同一幕布主机的 v3/v4 请求和鉴权，`desktop.py` 提供桌面失效提示。
