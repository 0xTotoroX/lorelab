# 节点编辑（fork 新增）

本 fork 基于 liuboacean/mubu-integration，保留原有文档管理命令；新增节点编辑先面向个人串行使用。不要同时在网页、手机、桌面端修改同一篇文档。

## 运行

Agent 统一加 `--agent`，执行时必须提供预览版本；JSON 字段与错误处理见 [Agent 调用约定](agent-usage.md)。以下保留原 CLI 用法。

在仓库根目录创建独立 Python 环境：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/mubu_api.py --auth desktop list --json
.venv/bin/python scripts/mubu_api.py --auth desktop nodes DOC_ID --json
```

`--auth desktop` 只读复用本机幕布桌面端已有登录，不保存 Token 副本。macOS App Store 和普通版、Windows 数据目录均有探测逻辑；本次仅 macOS App Store 实机验证。遇登录失效请在幕布桌面端重新登录；不自动接管登录。桌面端无需持续运行。凭据读取依赖当前 RxDB/LevelDB 存储格式，格式变化或压缩可能导致无法发现记录。

默认认证仍为上游密码/JWT 模式。全局参数放在子命令之前；数据目录可用 `--data-root PATH` 或 `MUBU_DATA_ROOT` 指定。`--auth desktop` 不改变原有 `save` 的整体覆盖语义，节点编辑不会调用或回退到 `save`。

## 预览和执行

以下 `DOC_ID`、`NODE_ID` 和 `VERSION` 均替换为 `nodes` 的返回值。

```sh
# 预览，不发送写请求
.venv/bin/python scripts/mubu_api.py --auth desktop node-update DOC_ID \
  --node-id NODE_ID --text '新的正文' --json

# 确认同一文档版本后提交；若版本变了先重新读取、审核
.venv/bin/python scripts/mubu_api.py --auth desktop node-update DOC_ID \
  --node-id NODE_ID --text '新的正文' --expect-version VERSION --execute --json

# 描述与正文分别修改；替换整个字段，原字段加粗/链接等格式不保留
.venv/bin/python scripts/mubu_api.py --auth desktop node-update DOC_ID \
  --node-id NODE_ID --field note --text '新的描述' --execute

# 在父节点下插入子节点；index 从 0 开始，省略时追加
.venv/bin/python scripts/mubu_api.py --auth desktop node-create DOC_ID \
  --node-id PARENT_ID --text '子节点' --note '描述' --index 0 --execute

# 默认只预览；删除包含目标的全部后代
.venv/bin/python scripts/mubu_api.py --auth desktop node-delete DOC_ID --node-id NODE_ID
```

节点命令始终输出 JSON，`--json` 是显式别名。`nodes --query TEXT` 筛选单篇文档的正文和描述。旧发布版的 `node-create` 需要父节点；1.4.0 新增 `--root` 顶层创建，见下文。

## 状态与失败处理

| 状态 | 意义 | 退出码 |
| --- | --- | --- |
| `preview` | 仅生成计划，未写云端 | 0 |
| `unchanged` | 内容已相同，未发送写请求 | 0 |
| `verified` | 读回版本前进一次，目标变化及其他节点内容匹配 | 0 |
| `conflict` | 预览版本或发送前快照不同，未写入 | 2 |
| `rejected` | 服务端明确拒绝，读回文档未变化 | 3 |
| `uncertain` | 请求已发送，但读回失败或整体内容/版本不符 | 3 |

参数、认证和读取错误退出 1（argparse 用法错误为 2）。`uncertain` 不表示没有写入；不要自动重试创建/删除。先运行 `nodes`、检查网页和本次 `operation_id`。写后保存记录失败时返回 `record_warning`，不会把已确认的写入变成“未执行”。

每次真实操作在 `~/.local/state/mubu-cli/operations/` 保存原始快照、事件与读回结果，目录权限 700、文件权限 600；可用 `MUBU_STATE_DIR` 指定位置。记录可能含完整文档内容，但不含 Token/请求头。未实现自动回滚：恢复前须比对当前云端版本，不要盲目覆盖旧快照。

## 并发与保真边界

服务器在真实测试中接受了“旧版本 + 新 memberId”的更新，并改变目标正文。`--expect-version` 和发送前二次读取只能降低竞争概率，**不是服务端原子比较交换（CAS）**。写后读取也无法排除其后的其他客户端修改。因此第一版只用于串行编辑，不能承诺协同写入安全。

正文/描述按纯文本替换，转义 `<>&` 和换行。兄弟节点、子节点、另一字段及未知属性不进入更新 payload，读回还会检查整篇 definition。服务端省略叶子空 children/默认 taskStatus，以及受影响节点 modified 的变化，被视为等价。旧发布版仅做图片/未知字段离线保留测试。1.4.0 已在含图片、加粗正文、链接及文档附件的合成文档中验收局部替换与图片追加；不能推广为所有格式的无损编辑。

没有隐式全树覆盖、批量修改既有节点、自动撤销、任意富文本格式编辑或 MCP。批量新增分支见下文。

## 批量追加大纲分支

`node-import` 读取 JSON 大纲，将多个根及其完整子树作为一个 `create` 事件提交。输入只含纯文本 `text`、可选 `note` 和 `children`，不接受已有节点 ID、HTML、图片或其他字段。示例见 [outline.json](../examples/outline.json)。

```sh
# 在目标父节点下追加，默认预览；--root 表示文档顶层
.venv/bin/python scripts/mubu_api.py --agent --auth desktop node-import DOC_ID \
  --node-id PARENT_ID --file outline.json
.venv/bin/python scripts/mubu_api.py --agent --auth desktop node-import DOC_ID \
  --node-id PARENT_ID --file outline.json --expect-version VERSION --execute
```

`--index` 从 0 开始，省略为末尾。预览返回 `node_count`、`root_ids` 和完整事件；执行返回实际新建 ID。预览与执行会重新生成 ID，调用方应使用执行结果。两次使用同一份已审核输入文件；版本改变时重新读取和预览。

客户端每批限制 500 个节点、32 层、512 KiB 输入；这些不是服务端容量保证。超过限制先按分支拆批，每批成功回读后才处理下一批。同一文档仍只允许一个写入者。

执行沿用原有日志、二次快照检查、单次发送和整篇回读；`verified` 要求全部新增后代、旧节点和文档字段符合预期，且版本恰好增加一次。超时也会尝试只读核验；`uncertain` 时用 `operation-status OPERATION_ID --verify` 排查，不能直接重发。它是追加命令，同一份输入再次绑定新版本执行会新增重复节点。

实机验证覆盖空文档的两个根与三层树、在已有父节点指定位置批量插入、保留兄弟节点、过期版本拒绝。每批一条写请求、一次版本增量；最大容量和各客户端视觉呈现未据此声称已验收。

## 实现与证据

- `scripts/mubu/desktop.py`：数据目录发现和只读登录记录解析。
- `scripts/mubu/nodes.py`：节点 ID 定位、事件计划和数据完整性比较。
- `scripts/mubu/node_service.py`：快照、预览、单次发送、读回及操作记录。
- `scripts/mubu/node_cli.py`：节点命令与 JSON 输出。
- `tests/test_nodes.py`：定位、保真、失败与认证的行为测试。

协议研究参考 [CLI-Anything 的幕布实现](https://github.com/HKUDS/CLI-Anything/blob/main/mubu/agent-harness/mubu_probe.py) 和幕布网页实际网络请求；没有引入 CLI-Anything 运行时依赖。该仓库的代码是 Apache-2.0，本 fork 沿用其原有 MIT 许可；本轮新增实现独立编写，协议形状按现场观察验证。

2026-09-26 核验的网页资源 `https://assets.mubu.com/DocEditor-995fdd7071535976.js` 中，`tb()` 使用客户端随机数生成 `[1000, Number.MAX_SAFE_INTEGER)` 范围内的 `memberId`。CLI 同样为一次独立写入生成随机标识，不复用网页标识。上游文档中“memberId 必须手工抓取”的限制不适用于本 fork 的节点命令；其原有整篇 `save` 未在本轮改造。

验证命令：

```sh
.venv/bin/python -m pip install -r requirements-dev.txt ruff
PYTHONPATH=scripts .venv/bin/python -m pytest -q
.venv/bin/ruff check scripts
```

实机验收：桌面未启动时，读取、正文更新、描述更新、嵌套新增、指定位置插入、删除子树、旧预览拒绝均通过；新增后删除的测试子树已清理，独立验收文档保留供人工查看。上游旧的文档管理能力只运行回归测试，不据此宣称全部重新实测。

## 1.4.0 新增：分支、结构与保留格式

下列命令随 1.4.0 准备发布，尚未包含在既有发布包中。

```sh
# 分支根为相对深度 0；输出包含祖先路径和图片引用
.venv/bin/python scripts/mubu_api.py --auth desktop nodes DOC_ID \
  --node-id NODE_ID --depth 2 --include-html

# 顶层新增（--root 与 --node-id 二选一）；默认预览
.venv/bin/python scripts/mubu_api.py --auth desktop node-create DOC_ID --root --text '新主题' --index 0

# 移动完整子树，保留 ID、内容和图片；目标为父节点或顶层
.venv/bin/python scripts/mubu_api.py --auth desktop node-move DOC_ID \
  --node-id NODE_ID --parent-id PARENT_ID --index 0
.venv/bin/python scripts/mubu_api.py --auth desktop node-move DOC_ID --node-id NODE_ID --root --index 1

# 替换唯一的文字片段，保留该片段所在格式标签
.venv/bin/python scripts/mubu_api.py --auth desktop node-update DOC_ID \
  --node-id NODE_ID --replace '原文字' --text '新文字'

# 保留原描述并另起一行追加
.venv/bin/python scripts/mubu_api.py --auth desktop node-update DOC_ID \
  --node-id NODE_ID --field note --append --text '新增说明'

# 默认在描述中追加链接；可用 --field text 追加到正文
.venv/bin/python scripts/mubu_api.py --auth desktop node-link DOC_ID \
  --node-id NODE_ID --url 'https://mubu.com/help/124' --label '来源'
```

写命令执行仍需 `--execute`，可配合 `--expect-version`。同级排序也使用 `node-move`；`--index` 按**移除目标子树后的**目标列表计算，省略为末尾。拒绝移动到自己或后代节点下。移动使用官方 `structureChanged` 单事件，不是删除后重建。

`--replace` 仅允许原文字在一个文本格式片段内唯一匹配；跨加粗/链接等标签的匹配、多处匹配或空搜索词会拒绝。它不提供任意 HTML 注入、全面样式编辑或正则替换。`--append` 和 `node-link` 保留原字段并追加。链接支持完整 HTTP、HTTPS、Obsidian URL；Obsidian 链接能否在具体幕布客户端打开尚未实机验收。

实机新增验收：顶层创建、跨父节点/顶层往返移动、原节点 ID 保持、链接显示、带加粗正文/图片/文档附件时的局部文字替换与追加图片。认证失效用合成无效凭据得到真实拒绝响应，未执行真实账号登出再登录。上传命令及更多边界见 [媒体说明](media.md)。
