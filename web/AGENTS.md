# web/

> L2 | 父级: ../AGENTS.md

React 18 + TypeScript + Vite + Base UI + Lucide。当前 GUI 开发主源，只包含已确认的配置台，不恢复旧阅读工作台或实验布局入口。

- `src/`：配置台入口、共享控件、主题与内存示例状态。
- `scripts/`：独立 HTML 打包、静态和交互检查，见该目录地图。
- `package.json` / `package-lock.json`：唯一 npm 依赖与版本锁，不引入第二套组件库。
- `tsconfig.json` / `vite.config.ts`：类型检查、以 src 为根目录的相对资源构建。
- `README.md`：本地启动、构建、验证及真实后端边界。
- `DESIGN.md`：已确认的视觉与交互规范。
- `.gitignore`：依赖、产物、浏览器状态与验证报告不入库。

`npm test` 运行构建、静态与交互检查。涉及视觉变更时另做真实浏览器检查。所有状态仅保存在 React 内存；禁止把合成端点、凭据或示例费用当成真实配置。真实后台接入需遵循现有 CLI 契约，不能新增独立采集、写作或交付实现。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
