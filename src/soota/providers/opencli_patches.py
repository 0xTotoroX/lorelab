from __future__ import annotations

import hashlib
import json
from pathlib import Path

from soota.storage.atomic import atomic_write

# Apache-2.0 upstream: jackwener/OpenCLI. Only managed installations are modified.
# https://github.com/jackwener/OpenCLI/issues/2487
NAVIGATION = """            result = await sendCommandFull('navigate', {
                url,
                ...this._cmdOpts(),
            });"""
REPLACEMENT = r"""            // Modified by Soota: supported media adapters use a verified owned tab.
            if (this.surface === 'adapter' && /^https:\/\/(www\.)?(bilibili\.com|youtube\.com)(\/|$)/.test(url)) {
                result = { page: await sootaNavigate(this, url) };
            } else {
                result = await sendCommandFull('navigate', {
                    url,
                    ...this._cmdOpts(),
                });
            }"""
NAVIGATION_HELPER = """// Modified by Soota: avoid Browser Bridge detach/update race for supported media sites.
async function sootaNavigate(page, url) {
    const expected = new URL(url);
    const actual = await page.evaluate('location.href');
    if (actual !== url) {
        const previous = page.getActivePage();
        const target = await page.newTab(url);
        if (!target) throw new Error('Navigation returned no page');
        page.setActivePage(target);
        // Only release the page owned by this adapter session, never user tabs.
        if (previous && previous !== target) await page.closeTab(previous);
    }
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
        const state = await page.evaluate('({ href: location.href, ready: document.readyState })');
        const arrived = new URL(state.href);
        const correctPath = expected.pathname === '/' || arrived.pathname === expected.pathname;
        if (arrived.origin === expected.origin && correctPath && state.ready !== 'loading') {
            return page.getActivePage();
        }
        await new Promise(resolve => setTimeout(resolve, 250));
    }
    throw new Error('Navigation did not reach the requested page');
}
"""


def apply_managed_fixes(install: Path) -> None:
    relative = "node_modules/@jackwener/opencli/dist/src/browser/page.js"
    path = install / relative
    if not path.is_file():
        return
    original = path.read_text()
    if REPLACEMENT not in original:
        # Two matching calls exist: first navigation and stale-target recovery.
        # Replace only the first, scoped to the known Page.goto implementation.
        if "    async goto(url, options) {\n        let result;\n        try {\n" + NAVIGATION not in original:
            return
        original = original.replace(NAVIGATION, REPLACEMENT, 1)
    if NAVIGATION_HELPER not in original:
        original += "\n" + NAVIGATION_HELPER
    atomic_write(path, original)
    atomic_write(
        install / "soota-compatibility.json",
        json.dumps(
            {
                "patch": "media-owned-tab-navigation",
                "modified_by": "Soota",
                "files": [{"file": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
            },
            indent=2,
        )
        + "\n",
    )
