"""mubu 包 — 幕布 API 封装（模块化拆分后的正式包）。

子模块职责：
- config: 常量 / 配置 / 日志 / 异常 / 路径安全
- convert: 文档结构 ↔ Markdown / OPML / FreeMind 转换 + 展示格式化
- client: MubuClient（鉴权 / 请求 / 文档·文件夹·搜索·导出）
- desktop: 只读复用桌面认证和 macOS 数据目录发现
- nodes: 原始节点定位、局部事件构造和完整性比较
- node_service: 快照前置检查、单次写入、读回确认和操作记录
- node_cli: 节点命令的参数与 JSON 输出
- rich_text: 保留格式的唯一文本片段替换与链接
- media: 图片/附件上传、绑定、核验和阶段记录
- media_cli: 图片/附件命令和只读鉴权检查
- cli: 命令行入口（argparse 子命令 + 日志配置）

旧入口 scripts/mubu_api.py 现为向后兼容 shim，重新导出本包全部公开符号。
"""

__version__ = "1.4.0"
