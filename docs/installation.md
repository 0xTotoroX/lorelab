# 安装与构建

## 安装发行包

当前构建目标为 **macOS Apple Silicon（arm64）**。发行 tar.gz 包含产品、三个组件的独立源码、预构建 Cubox、完整 Skills，以及固定版本的 Python 依赖 wheel。终端用户不需要 Go、npm 或预装 Python；首次安装需要联网获取 uv（若未安装）和 Python 3.12.12。

解压可信来源的发行包，并在解压目录执行：

```sh
sh install.sh --prefix "$HOME/.local/share/lorehub"
"$HOME/.local/share/lorehub/bin/lorehub" doctor
```

若发布者提供 `.sha256`，可先在压缩包所在目录运行 `shasum -a 256 -c <文件名>.sha256`。包内清单用于检测损坏、遗漏及源码与二进制错配，不代替对发行来源的信任或签名。

只在需要注册到 Agent 时显式指定 Skills 目录：

```sh
sh install.sh --prefix "$HOME/.local/share/lorehub" \
  --skills-dir "$HOME/.agents/skills"
```

注册名称为 `lorehub`、`cubox`、`soota`、`mubu-integration`。同名非 LoreHub 目录、文件或其他符号链接会使安装停止，原内容保持不变。可以另选一个空目录。没有 `--skills-dir` 时，完整 Skills 仍位于 release 内，但不会向 Agent 全局目录注册。

安装器不修改 shell profile、不执行 `npm install`，也不替换已有全局 CLI。可以一直使用完整命令路径；需要时自行为当前终端设置：

```sh
export PATH="$HOME/.local/share/lorehub/bin:$PATH"
```

已有 Python 3.12+ 时也可直接调用 Python 安装入口，它仍会用 uv 创建私有 Python 环境：

```sh
python3 packaging/install.py --prefix "/path/with spaces/LoreHub" \
  --skills-dir "/path/to/agent skills"
```

## 安装布局和事务

```text
PREFIX/
  .install.lock
  current -> releases/ID
  bin/{lorehub,cubox-cli,soota,mubu-cli} -> ../current/bin/NAME
  releases/ID/
    source/          # 产品、组件、Skills、固定依赖与 bundle 清单
    venv/            # 该 release 的 Python 包
    toolchain/python/# uv 管理的 Python 3.12.12，位于此 release 内
    bin/             # 四个固定入口
    runtime.json
    skills/
      lorehub -> ../source/skills/lorehub
      cubox -> ../source/modules/cubox-cli/skills/cubox
      soota -> ../source/modules/soota/skills/soota
      mubu-integration -> ../source/modules/mubu-cli
```

幕布 Skill 指向整个组件根目录，保留它引用的 `docs/`、`scripts/` 和其他资源。其余 Skills 也保留完整目录，组件完整源码同时留在 `source/modules/`。

安装顺序为：校验 bundle 文件清单及哈希 → 调用 `lorehub.components.verify(root)` → 检查目标冲突 → 建立新 release → 安装已打包的 wheel → `uv pip check` → 四个命令的离线 help/version 检查及再次组件校验 → 原子替换 `current`。终端安装不会重新解析依赖版本，也不会编译 Cubox。并行安装由 prefix 内的文件锁拒绝。

安装过程失败时不切换 `current`，清除本次未完成 release；旧 release 保留。已有命令和注册 Skills 都间接指向 `current`，升级后一起切换。原子切换失败会移除本次新建的链接。强制断电或 `SIGKILL` 可能留下未启用 release，`current` 仍指向切换前或已完整检查的新版本。

环境含绝对路径，不支持把安装后的 prefix 或 release 直接搬到其他目录。需要换位置时重新安装。

## 产品运行时接口

`release/bin/lorehub` 设置 `LOREHUB_ROOT=release/source`、`LOREHUB_RUNTIME_FILE=release/runtime.json`，然后使用该 release 的 `venv/bin/python -I -B -m lorehub.cli`。入口屏蔽外部 `PYTHONPATH/PYTHONHOME`，设置 `SOOTA_AUTO_UPDATE=false`；Cubox 更新提示在产品调用环境中关闭。

`runtime.json` 的命令元素全部使用安装后的绝对路径，结构如下（`/prefix/releases/ID` 是占位路径）：

```json
{
  "schema_version": 1,
  "product": "lorehub",
  "release_id": "ID",
  "components_lock_sha256": "<sha256>",
  "tools": {
    "cubox": ["/prefix/releases/ID/bin/cubox-cli"],
    "soota": ["/prefix/releases/ID/venv/bin/soota"],
    "mubu": [
      "/prefix/releases/ID/venv/bin/python",
      "/prefix/releases/ID/source/modules/mubu-cli/scripts/mubu_api.py"
    ]
  }
}
```

独立命令 `mubu-cli` 保留组件原生参数，Agent 调用时按组件约定显式传入 `--agent`。缺少受管可执行文件时直接失败，不会去 PATH 查找同名 CLI。Skills 注册本身不会改写组件文档的命令示例。

## 从本地源码构建

构建者需要 Python 3.12+、Go（以组件 `go.mod` 为准）、macOS 命令行构建工具，以及下载 Python/Go 依赖的网络。uv 可复用已有安装；缺失时以固定版本 0.9.26 引导，校验固定安装脚本 SHA256，并使用 `UV_UNMANAGED_INSTALL` 禁止修改 profile。Python 版本固定为 3.12.12。

对应官方参数见 [uv 安装选项](https://docs.astral.sh/uv/reference/installer/) 和 [Python 存放目录](https://docs.astral.sh/uv/reference/environment/#uv_python_install_dir)。

```sh
python3 packaging/build_release.py --output-dir /path/to/release-output
```

`--root DIR` 可显式指定完整源码树。Git checkout 仅选取索引中的文件内容，因此新增发行源码需先 `git add`；工作区中已跟踪文件的修改会被读取。构建不修改组件锁，也不自动拉取远端源码。缺少产品 CLI、`components.py`、任一 Skill 或依赖锁时停止。

源码选择限定为产品根文件（包括 `NOTICE.md` 和根 `uv.lock`）、`src/`、`skills/`、`packaging/`、`docs/`、`tests/`、许可证和三个明确的 `modules/` 目录。排除 `.private`、`private`、`dist`、`.git`、缓存、虚拟环境、私密环境文件、日志和运行数据；拒绝源码符号链接。复制后和构建后均调用组件校验，防止遗漏组件源码或悄悄改变来源。

Cubox 从 `modules/cubox-cli` 执行 `go build -mod=readonly -trimpath -buildvcs=false`，使用当前 `go.mod` 中的 module 名和 `cmd.Version` 注入锁定组件版本。不会调用原作者 npm 下载器。

Python 的构建依赖和运行依赖均使用带哈希的锁。发布者先构建依赖 wheel 和产品/Soota wheel，全部打入 tar.gz，再由 `packaging/bundle.json` 绑定每个文件的 SHA256、模式、平台、组件锁和内容 release ID。压缩包固定归档时间与归属信息，不包含构建者的账号、缓存、venv 或本机运行时路径。不同工具链重建不承诺字节相同；同一份包安装使用相同的 wheel。

源码 checkout 也支持 `sh install.sh --prefix ...`，此路径会现场执行上述构建，需要 Go 和构建工具。发行包有预构建 payload 却缺少 bundle 清单时直接拒绝，不降级成源码构建。

维护者更新依赖锁时执行（正常构建和安装不执行这些命令）：

```sh
uv --no-config pip compile pyproject.toml modules/soota/pyproject.toml \
  modules/mubu-cli/requirements.in --generate-hashes --python-version 3.12 \
  --no-header --no-annotate -o packaging/requirements.lock
uv --no-config pip compile packaging/build-requirements.in \
  --generate-hashes --python-version 3.12 --no-header --no-annotate \
  -o packaging/build-requirements.lock
```

## 验证、恢复与限制

```sh
python3 -B -m unittest discover -s tests -p 'test_install*.py' -v
"$HOME/.local/share/lorehub/bin/lorehub" doctor
"$HOME/.local/share/lorehub/bin/cubox-cli" version
"$HOME/.local/share/lorehub/bin/soota" --help
"$HOME/.local/share/lorehub/bin/mubu-cli" --agent --help
```

这些检查验证安装和本地入口，不登录账号、不写入云端，也不代表站点、媒体下载、可选 ASR、ffmpeg 或其他平台工具已完成配置。当前不提供其他 CPU/系统的发行包，也不是完全离线安装包：Python 和缺失的 uv 仍需下载。

重新运行安装命令会生成新 release，保留旧版本。需要回退时，在确认旧 release 仍完整后，创建指向旧 `releases/ID` 的临时符号链接，再用 `os.replace` 原子替换 `PREFIX/current`；不要搬动旧 release。删除 prefix 前先移除指向该 prefix 的显式 Skill 注册链接，勿删除同名用户目录。卸载不会清理组件在其他位置保存的用户配置或资料。
