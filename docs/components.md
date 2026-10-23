# 组件维护与独立导出

LoreLab 的产品源码是维护主源。组件在 `modules/` 保留构建文件、独立入口、Skill、引用文档、测试与许可证；原作者仓库只用于人工选择补丁。组件维护命令不访问远端，不自动合并、不 push，也不安装原作者发行包。

## 指纹和来源

`components.lock.json` 的每个组件记录 `path`、`skill.name/path`、`repository`、`revision`、`version` 和 `tree_sha256`。`revision` 是导入来源提交，`version` 是当前构建的组件标记；更新标记时可用 `import_version` 保留原导入值。它们不证明修改后的源码仍与导入提交完全相同，当前内容由 `tree_sha256` 绑定。刷新指纹不改写来源和版本字段，也不是发布新组件版本。

指纹使用组件根目录内每个有效文件的相对 POSIX 路径，包含点文件、源码、依赖锁、构建定义、许可证、文档、测试和 Skill。文件内容按原始字节计算 SHA-256，再对整个映射计算 SHA-256：

```python
files = {relative_path: sha256(file_bytes).hexdigest(), ...}
tree_sha256 = sha256(
    json.dumps(files, sort_keys=True, separators=(',', ':')).encode('utf-8')
).hexdigest()
```

这里沿用 `json.dumps` 默认的 `ensure_ascii=True`。不按换行、平台或 JSON 排版归一化文件，不把绝对路径、时间或文件权限加入指纹；导出会保留文件权限。指纹不依赖 Git 索引或 `.gitignore`，因此新增、未跟踪、甚至被 Git 忽略的有效源码仍会影响结果。

只排除以下明确生成物与运行数据，校验和导出共用同一规则：

- 任意层级的 `.git`、`.venv`、`__pycache__`、`.pytest_cache`、`.mypy_cache`、`.ruff_cache`、`.cache`、`node_modules`、`dist`、`build`、`htmlcov`、`*.egg-info`。
- 组件根的 `.private`、`.local`、`output`、`tmp`、`.config`、`.state`，以及 `docs/private`、`PLAN.md`、`PLAN.zh-CN.md`。
- `.DS_Store`、Python 字节码、coverage 数据、`.mubu_token`、`.mubu_trash.json`、`.env` 及 `.env.*`；保留以 `.example`、`.sample`、`.template` 结尾的环境示例。
- Cubox 的已知构建输出 `cubox-cli`、`cubox-cli.exe`、`bin/cubox-cli`、`bin/cubox-cli.exe`；`bin/` 内其他源码仍纳入指纹。

不要把有效源码放进保留的运行目录。排除规则不是任意秘密文件扫描器：个人配置、真实账号数据、原始收藏、日志和草稿仍应放在项目外的用户状态目录，导出前检查文件清单。兼容文件名 `lorehub-provenance.json` 继续作为导出的保留文件名；源组件已有同名文件时拒绝覆盖。

组件路径必须是产品根内规范的相对路径，Skill 路径必须位于对应组件内；绝对路径、`..`、反斜线、控制字符、组件/Skill 路径中的符号链接都会被拒绝。非排除区内的符号链接与非常规文件也会报错，避免闭包依赖仓库外文件；不会静默跳过有效源码链接。Skill 入口必须存在且确实纳入指纹。

## 校验和刷新

```text
lorelab components verify
lorelab components refresh
lorelab components verify
```

修改源码或 Skill 后先审查 diff，再显式 refresh；不能把 refresh 当成对未知变化的自动认可。`verify` 只读，任何组件指纹不匹配即 `ok=false`，同时保留能计算出的实际指纹。`refresh` 先验证所有路径及 Skill 入口，全部有效才用临时文件和原子替换更新 lock 中的所有 `tree_sha256`。失败不写入部分组件，也不修改源码或导入 revision。操作期间保持组件源码静止；若源码并发变化，最终复核可能失败，应先停止其他写入再检查。

组件 lock 变化后需要重建并安装对应的受管 runtime，不能沿用绑定旧 lock 的运行时。doctor 展示绑定 CLI、四套 Skill 和 `lorehub` 兼容别名，`lorelab skills list` 给出源码入口；这些是本地检查，不证明账号、站点或云端写入已通过验收。

## 独立导出

```text
lorelab components export cubox /path/to/new-cubox-source
lorelab components export soota /path/to/new-soota-source
lorelab components export mubu /path/to/new-mubu-source
```

所有组件须通过 lock 校验，目标必须不存在，且不能位于任何组件源码目录内部。导出复制文件，不生成硬链接或指向主仓库的符号链接。保留构建与 Skill 引用闭包、依赖声明、源码、测试及许可证，排除上述运行数据。导出过程中再次核对内容，变化或复制失败会清理本次创建的未完成目标，不覆盖已有目录。

导出根目录附加 `lorehub-provenance.json`，包含组件名、来源仓库、`recorded_revision`、`revision_role: import_source`、版本标记、当前 `tree_sha256`、组件内的 Skill 相对路径和每个源文件的 SHA-256。它不包含私人源目录路径或运行记录；provenance 自身不计入该源码指纹。独立副本之后的改动不会影响主仓库，provenance 记录的是导出时内容；重新核对其文件映射可发现后续篡改。

| 组件 | 导出后的独立入口与闭包 |
| --- | --- |
| Cubox | `go.mod` / `go.sum`、Go 源码、Makefile、npm 源码安装器、`skills/cubox/`。在组件根运行 `node scripts/install.js` 从随包源码构建，使用 `node scripts/run.js --help`；需要满足 `go.mod` 的 Go 工具链。 |
| Soota | `pyproject.toml` / `uv.lock`、`src/soota/`、`skills/soota/` 及其引用。在组件根使用 `uv run soota --help`。 |
| 幕布 | `requirements.txt`、`scripts/`、根 `SKILL.md`、README 和 `docs/`。在隔离 Python 环境安装依赖后运行 `python scripts/mubu_api.py --help`。 |

Cubox 的本地 npm 包为 private，仅提供随包源码构建，不假设任何自有 Release 或 npm 发布已存在。Go import path 中保留上游模块名用于现有依赖兼容，不能据此安装上游发行包。版本标记含历史 `+lorehub` 的自有构建关闭原作者版本查询与替换安装提示；更新从 LoreLab 源码重新构建，独立导出也保留这一规则。

安装四套 Skill 与 `lorehub` 兼容入口时允许用户指定 `--skills-dir`。安装器应保留真实 source 入口及相对引用闭包，不能只复制孤立的 `SKILL.md`；Agent 通过 `lorelab skills list` 定位 source。LoreLab Skill 只负责安装、组件维护和路由，需要同份源码中的 `docs/` 与组件 Skill。`lorehub` Skill 是兼容入口。文章流程、schema 和写作提示词仅在 Soota 组件内维护；独立 Soota 导出保留 `docs/knowledge.md`、`skills/soota/references/{process,prompts}.md` 及全部引用，不依赖产品包或其他 Skill 目录。三个组件仍分别保留独立入口。

## Python 接口

实现在 [`src/lorelab/components.py`](../src/lorelab/components.py)，供 CLI/runtime 复用：

- `verify(root: Path) -> dict`：始终返回 `ok`、`errors: list[str]`、`components: dict`。每个可读取组件包含 `ok`、`path`、`skill`、`recorded_revision`、`locked_tree_sha256`、实际 `tree_sha256` 和 `file_count`。无效组件仍有 `ok=false`，无法计算时 `tree_sha256=null`。
- `refresh(root: Path) -> dict`：成功写 lock 后返回同形状的复核结果；错误返回 `ok=false`，保留来源和扩展元数据。
- `export_component(root: Path, name: str, destination: Path) -> dict`：成功返回 `ok`、空 `errors`、`component`、`destination`、`tree_sha256`、`file_count` 与 provenance 路径；无效来源或过期 lock 抛 `ValueError`，目标存在抛 `FileExistsError`，文件系统错误抛 `OSError`。

## 本地验证

组件测试仅用临时合成目录和导入源码副本，不读账号或访问服务。Skill 检查需要 PyYAML，源码安装器检查需要 Node/npm：

```text
uv run --no-project --with pyyaml python -m unittest discover -s tests -v
```

从源码运行时使用 `uv run python -m lorelab.cli …`，由本地依赖绑定找到 Soota；只做 Python 模块检查时可设置 `PYTHONPATH=src:modules/soota/src`。测试覆盖源码/Skill 篡改、路径与链接越界、原子刷新失败、导出隔离、并发内容变化检测、三组件实际文件闭包、产品、兼容入口及组件 Skill 的 frontmatter 和相对链接。`docs/workflow.md` 仅保留旧链接路由，流程契约主源是 `modules/soota/docs/knowledge.md`；检查应同时覆盖产品 Skill 路由和独立 Soota 的引用闭包。
