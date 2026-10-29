# LoreLab 配置台

后台配置与运行管理 GUI。这里是当前界面的开发主源；保留已确认的完整侧栏、三列分组、Obsidian 灰紫深浅主题、流光连接与分组诊断。

**当前使用内存示例数据。** 配置保存、连接测试、目录检查、诊断、任务重试和日志均为模拟行为；刷新后恢复初值。不会读取真实凭据、配置、收藏或知识库，也不会调用 CLI、付费服务或语言模型。真实后端接入尚未实现。

## 运行

使用符合 `package.json` engines 的 Node.js 和 npm；本机验证使用 Node.js 26。依赖由 `package-lock.json` 固定。

```sh
cd web
npm ci
npm run dev
```

开发服务默认只监听本机，按终端输出的地址打开。无需 API key、账号或环境变量。

默认进入服务配置。`?view=overview` 打开连接概览；`?page=capture`、`?page=storage`、`?page=diagnostics` 分别直达其他分类。只有一套当前布局。

## 构建与验证

```sh
npm test
```

该命令依次运行 TypeScript / Vite 构建、静态边界和对比度检查、生产 bundle 的交互检查。检查覆盖参数校验、草稿保护、连接反馈、任务恢复、日志筛选以及动画生命周期；JSDOM 不验证像素布局。

```sh
npm run build
npm run preview
```

- `dist/index.html` 与 `dist/assets/`：可由静态服务器提供的构建产物。
- `dist/lorelab-settings.html`：内嵌 CSS / JS 的单文件版本，可直接打开。
- `output/`：本地验证报告；与依赖、构建产物一起忽略，不提交。

修改布局或控件后，使用真实浏览器检查桌面、手机尺寸、深浅主题、键盘顺序和未保存弹层。视口模拟不能替代真实 iPhone / Safari 验收。

## 实现

React 18、TypeScript、Vite、Base UI 和 Lucide；状态集中在 `src/settings/use-settings.ts`。`model.ts` 定义合成数据与校验，`SettingsApp.tsx` 管理外壳、导航与保存保护。配置和诊断复用标题列与内容列；SVG 轨道、Canvas 光点和节点按钮共用几何。

设计约束与变量来源见 [DESIGN.md](DESIGN.md)，模块职责见 [AGENTS.md](AGENTS.md)。GUI 不加入当前 Python / CLI / Skill 安装包；前端开发不要求更改既有安装或组件锁。
