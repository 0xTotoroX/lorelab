# 组件与许可证

LoreHub 产品层使用 [GPL-3.0-only](LICENSE)。成套交付时保留以下组件源码和许可证；各组件的原版权声明不因目录整合而改变。

| 组件 | 本仓库目录 | 许可证 |
| --- | --- | --- |
| Soota | `modules/soota` | [GPL-3.0-only](modules/soota/LICENSE) |
| Cubox CLI | `modules/cubox-cli` | [MIT](modules/cubox-cli/LICENSE) |
| 幕布 CLI | `modules/mubu-cli` | [MIT](modules/mubu-cli/LICENSE) |

导入来源和提交记录在 `components.lock.json`。当前可构建源码以本仓库中的文件及内容指纹为准，原始导入提交只作溯源。Python 依赖按固定清单构建，发行包内各 wheel 保留其许可证元数据；uv 与 Python 由安装器获取其各自发行物。
