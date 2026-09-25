# Third-party notices

Soota's Apache-2.0 declaration covers its own code. It does not replace the
licenses, copyright notices, or other requirements of third-party components.
Dependencies are installed separately; Soota does not vendor their source or
include their runtimes in its wheel. The copies below document the reviewed
versions. They are included in Soota's wheel and source distribution.

## TikHub Python SDK 2.1.2

- Integration: pinned Python dependency (`tikhub==2.1.2`); no upstream files modified.
- Release: <https://pypi.org/project/tikhub/2.1.2/>.
- Declared source: <https://github.com/TikHub/TikHub-API-Python-SDK-V2>.
- License text: [the unmodified release LICENSE](LICENSES/tikhub-2.1.2-LICENSE), Apache-2.0.
- **Unresolved upstream conflict:** the same wheel's METADATA and the source
  distribution's pyproject.toml declare MIT, while both distributions contain
  an Apache-2.0 LICENSE. This is not evidence of a dual-license grant. Soota
  preserves the actual license text without claiming that the conflict is resolved.
- No upstream NOTICE was present in the reviewed wheel or source distribution.
- Reviewed 2026-09-22 against the artifacts pinned by `uv.lock`:
  wheel SHA-256 `9de5b6828ab2e04a97efed6054af6015ac3546cc42cf8ecaaa1e26d48faee710`;
  sdist SHA-256 `7d6be6728a4a4441e3dc3a441777414e12be072024bd73bd408cc23675f7fbbf`.

## OpenCLI 1.8.3 (adapter reference version)

- Integration: separately installed executable invoked through a read-only command allowlist.
- Source: <https://github.com/jackwener/OpenCLI/tree/v1.8.3>.
- Package: <https://www.npmjs.com/package/@jackwener/opencli/v/1.8.3>.
- Copyright 2025 jackwener. License: Apache-2.0, consistently declared by
  package.json and [the unmodified LICENSE](LICENSES/opencli-1.8.3-LICENSE).
- No root NOTICE was present in the reviewed release. Soota makes no changes
  to the upstream executable. User-installed or Soota-managed runtimes retain
  their own license files; this reference copy does not describe every later release.

## opencli-mcp 0.0.22 (external runtime)

- Integration: separately installed local MCP process and Chrome extension; no upstream code or runtime is bundled in Soota's Python wheel.
- Source: <https://github.com/jackwener/opencli-mcp/tree/v0.0.22>.
- npm package: <https://www.npmjs.com/package/opencli-mcp/v/0.0.22>.
- Copyright 2026 jackwener. License: Apache-2.0 as declared by its source LICENSE and npm package metadata.
- Soota calls only an audited read-only site-command allowlist through MCP stdio; the external installation retains its own license files.

## Other dependencies

The dependencies listed in `pyproject.toml` and their transitive dependencies
retain their own distribution metadata and license files in the Python environment.
This list is not a license inventory for a bundled Python/Node application.
If such an application is distributed later, its actual included dependencies
and applicable notices must be inventoried at that time.
