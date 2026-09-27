**English** | [中文](README.zh-CN.md)

# Mubu CLI

Manage Mubu documents, edit nodes, and export content from your terminal.

Forked from [liuboacean/mubu-integration](https://github.com/liuboacean/mubu-integration). Retains document management and import/export tools, adding node editing and desktop-session reuse.

**Project version: `1.4.0` (not yet released)** · [Published releases](https://github.com/0xTotoroX/mubu-cli/releases). This page lists only already released features.

## Feature comparison

| Feature | Official MCP | Upstream | This fork |
| --- | --- | --- | --- |
| Create/read documents, browse directories, create folders and move items | Supported | Supported | Retained |
| Search documents and folders | Keyword search | Name search | Retained |
| Rename, delete, save whole documents | Not listed | Supported | Retained |
| Single/batch Markdown export, OPML/FreeMind export | Not listed | Supported | Retained |
| Query nickname and membership expiry | Supported | No dedicated command | No dedicated command |
| Authentication | OAuth / official Token | Password / JWT | Adds desktop-session reuse |
| Read/edit nodes, create children, delete subtrees | Not listed | No dedicated command | **Released** |
| Node-edit previews, version checks, readback verification | Not listed | No unified workflow | **Released** |

Upstream baseline: [f2f0e53](https://github.com/liuboacean/mubu-integration/commit/f2f0e53af66447970a1f2664a10bfbbea3f1d406). Official features are based on [Mubu's MCP documentation](https://mubu.com/help/124), checked 2026-09-27. “Not listed” does not mean proven unsupported; no authenticated tool-list audit was performed.

## Quick start

Requires Python 3.9+. No separate upstream installation is needed.

```sh
git clone https://github.com/0xTotoroX/mubu-cli.git
cd mubu-cli
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# Log in to Mubu desktop first, then read document nodes
.venv/bin/python scripts/mubu_api.py --auth desktop nodes DOC_ID

# Preview an edit; add --execute and --expect-version VERSION to apply
.venv/bin/python scripts/mubu_api.py --auth desktop node-update DOC_ID \
  --node-id NODE_ID --text 'New content'
```

## Usage notes

- Uses unofficial Mubu APIs, not official MCP. No multi-user editing or automatic two-way sync.
- Node writes default to preview. Plain `node-update --text` replaces the selected field with plain text; avoid concurrent edits in other clients.
- Desktop-session reuse was verified with macOS App Store Mubu. Windows/Linux have not been live-verified.

[Node editing](https://github.com/0xTotoroX/mubu-cli/blob/totoro-v1.4.0-alpha.1/docs/node-editing.md) · [Release notes](https://github.com/0xTotoroX/mubu-cli/releases/tag/totoro-v1.4.0-alpha.1)

## Credits and upstream documentation

- **Fork base:** [mubu-integration](https://github.com/liuboacean/mubu-integration), reusing document management, converters, and the request layer under the MIT license.
- **Implementation references:** [CLI-Anything's Mubu implementation](https://github.com/HKUDS/CLI-Anything/blob/main/mubu/agent-harness/mubu_probe.py) for desktop sessions and node protocols. New modules are independently implemented.
- **Compared only:** [OpenCLI](https://github.com/jackwener/opencli) and official MCP; neither is integrated.

Root READMEs retain the upstream text separately from this page: [English original](../README.md) · [中文原文](../README.zh-CN.md) · [Maintenance](../docs/fork-maintenance.md#readme-维护).
