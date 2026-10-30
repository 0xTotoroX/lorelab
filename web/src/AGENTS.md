# src/

> L2 | 父级: ../AGENTS.md

- `main.tsx`：挂载 SettingsApp，按顺序加载基础、主题与当前布局样式。
- `index.html`：Vite 页面模板与 SVG favicon 入口。
- `lorelab-mark.svg`：A1「错榫」品牌主文件，侧栏蒙版与浏览器图标共用，构建时内嵌。
- `vite-env.d.ts`：Vite 类型声明。
- `theme.css`：共享控件基础样式；当前主题由 settings/obsidian-tokens.css 提供。
- `components/ui/index.tsx`：Base UI 本地控件与弹层回焦。
- `settings/`：配置台页面、内存示例模型、流光与语义样式，见该目录地图。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
