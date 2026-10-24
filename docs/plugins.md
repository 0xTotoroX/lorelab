# 插件分发与安卓使用边界

LoreLab 可打包为一个本地插件，保留四个独立的 Skill：`lorelab`、`soota`、`cubox`、`mubu-integration`。各 Skill 的名称、触发条件和组件 CLI 保持独立。插件是分发入口，内容语义仍由 Agent 处理，服务操作仍通过对应 CLI。

## 生成与安装

从已经构建并校验的完整发行包生成：

```sh
python3 packaging/build_plugin.py --bundle /path/to/lorelab-release.tar.gz --output-dir dist
```

生成一个 ZIP，包含 `plugin.json`、`skills/`、所需引用文件、运行约定和同版 `runtime.tar.gz`。安装包以 tar.gz 嵌入，避免部分 ZIP 解包器丢失可执行权限。四套 Skill 从现有主源生成，重写相对链接，不另维护插件专用正文。插件引用和运行包留在归档内，不依赖开发者的私人路径。

通过所用 Agent 宿主支持的本地插件导入流程加载 ZIP。包生成与静态验证不代表宿主已安装、启用或加载 Skill；不同宿主的导入和刷新行为需实际验证。本仓库的构建脚本不上传插件、不修改宿主市场或云端账号。

插件声明需要本地执行环境，onboarding 使用已有的 LoreLab Skill。宿主调用设置流程时先检查 CLI，缺少时按插件内 `RUNTIME.md` 执行：

```sh
sh /path/to/plugin/install.sh --no-skills
"$HOME/.local/share/lorelab/bin/lorelab" setup --no-skills
lorelab doctor --plugin-root /path/to/plugin
```

`--no-skills` 避免在宿主已经加载插件 Skill 时另增全局注册，不移除旧有注册。用户已有其他同名 Skill 时，由用户选择保留方式，安装器不会覆盖。独立 CLI 仍可直接使用。

## 版本匹配与更新

`lorelab-binding.json` 记录产品版本、安装包内容 ID、组件锁和插件文件哈希。`doctor --plugin-root` 检查四套 Skill 与已装 CLI 是否同版，并检查插件文件是否被修改。它不是发行者签名，也不证明账号鉴权或云端操作成功。

插件更新由宿主管理，CLI 更新由 `lorelab update` 管理。两者需采用同次构建；版本不匹配时检查会失败。用户明确选择采用插件配套版本时：

```sh
lorelab update --from /path/to/plugin/runtime.tar.gz
lorelab doctor --plugin-root /path/to/plugin
```

当前不自动改写宿主插件缓存，也不在后台替换运行中的插件。四套普通 Skill 注册则随安装目录的 current 与 CLI 一同切换。

## 安卓

| 使用方式 | 当前状态 |
| --- | --- |
| Android / Termux 本机运行整套产品 | 不支持；当前二进制、Python wheel 和安装校验针对 macOS arm64 |
| 在手机直接运行本地插件 | 插件需要桌面执行器，下载 Skill 不会提供桌面 CLI 或本机幕布登录资料 |
| 安卓连接运行 LoreLab 的 Mac | 可使用支持远程连接的宿主；需在线 Mac、匹配的账号/工作区与配对，实际可用性受宿主开放范围影响 |

幕布桌面鉴权读取的是 Mac 上已有的登录记录；Android 幕布登录不等于该来源。组件还支持密码模式，但这不证明 Termux 的依赖、下载、鉴权与知识库交付已经通过验收。本产品没有新增云端执行服务，也未宣称完成安卓实机验收。

格式与能力依据：[插件包与 onboarding](https://developers.openai.com/plugins/build/plugins)、[需要本地执行器的插件](https://developers.openai.com/plugins/deploy/desktop-only)、[移动端远程连接](https://learn.chatgpt.com/docs/remote-connections)。
