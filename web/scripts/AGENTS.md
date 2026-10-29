# scripts/

> L2 | 父级: ../AGENTS.md

- `bundle-standalone.mjs`：从 Vite 产物生成 dist/lorelab-settings.html，保留标准 dist/index.html 与 assets。
- `check-static.mjs`：独立入口、状态边界、流光几何和深浅主题对比度检查。
- `check-interactions.mjs`：使用 JSDOM 执行生产 bundle，检查配置、保护、诊断、日志与动效；不验证像素布局。

报告写入已忽略的 output/。构建和检查不访问真实服务、账号或配置。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
