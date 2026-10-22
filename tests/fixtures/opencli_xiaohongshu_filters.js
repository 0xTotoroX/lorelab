// Copyright 2025 jackwener/OpenCLI; Apache-2.0. See LICENSES/opencli-1.8.3-LICENSE.
// Unmodified filter function from OpenCLI v1.8.8 clis/xiaohongshu/search.js.
// https://github.com/jackwener/OpenCLI/blob/v1.8.8/clis/xiaohongshu/search.js
// The harness supplies synthetic DOM state and virtual time only.
const FILTER_SETTLE_SECONDS = 5;
function buildApplySearchFiltersJs(requestedFilters) {
    return `
      (async () => {
        const requestedFilters = ${JSON.stringify(requestedFilters)};
        const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const text = (element) => (element?.textContent || '').replace(/\\s+/g, '').trim();
        const visible = (element) => {
          if (!element) return false;
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return rect.width > 0 && rect.height > 0 &&
            style.display !== 'none' && style.visibility !== 'hidden';
        };
        const visibleMatches = (root, selector) =>
          Array.from(root.querySelectorAll(selector)).filter(visible);
        const authBlocked = () => /登录后查看搜索结果/.test(document.body?.innerText || '') ||
          visible(document.querySelector('#login-btn'));
        const locationBlocked = () => /请开启浏览器地理位置权限/.test(document.body?.innerText || '');
        const panels = () => visibleMatches(document, '.search-layout__top > .filter > .filter-panel');
        const triggers = () => visibleMatches(document, '.search-layout__top > .filter');

        const openPanel = async () => {
          let clicked = false;
          for (let attempt = 0; attempt < 16; attempt++) {
            if (authBlocked()) return { status: 'auth', detail: 'login_wall' };
            const currentPanels = panels();
            if (currentPanels.length === 1) return { status: 'ok', panel: currentPanels[0] };
            if (currentPanels.length > 1) return { status: 'layout', detail: 'ambiguous_filter_panel' };
            const currentTriggers = triggers();
            if (currentTriggers.length > 1) return { status: 'layout', detail: 'ambiguous_filter_trigger' };
            if (!clicked && currentTriggers.length === 1) {
              currentTriggers[0].click();
              clicked = true;
            }
            await sleep(100);
          }
          return { status: 'layout', detail: 'filter_panel_not_found' };
        };

        const findOption = (panel, request) => {
          const groups = visibleMatches(panel, '.filters').filter((group) => {
            const label = Array.from(group.children).find((child) => child.tagName === 'SPAN');
            return text(label) === request.group;
          });
          if (groups.length !== 1) {
            return { status: 'layout', detail: groups.length ? 'ambiguous_group' : 'group_not_found' };
          }
          const options = visibleMatches(groups[0], '.tag-container > .tags')
            .filter((option) => text(option) === request.option);
          if (options.length !== 1) {
            return { status: 'layout', detail: options.length ? 'ambiguous_option' : 'option_not_found' };
          }
          return { status: 'ok', option: options[0] };
        };
        const isActive = (option) => option.classList.contains('active');
        const ready = () => visibleMatches(document, 'section.note-item, section:has(a[href*="/search_result/"]), section:has(a[href*="/explore/"]), .search-empty-wrapper').length > 0;
        const busy = () => visibleMatches(
          document,
          '.search-layout__main [aria-busy="true"], .search-layout__main [class*="skeleton"], .search-layout__main [class*="loading"]',
        ).length > 0;
        const snapshot = () => {
          const rows = visibleMatches(document, 'section.note-item, section:has(a[href*="/search_result/"]), section:has(a[href*="/explore/"])')
            .map((row) => {
              const anchor = row.querySelector('a[href*="/search_result/"], a[href*="/explore/"]');
              return [anchor?.getAttribute('href') || '', text(row)];
            });
          const feed = document.querySelector('.feeds-container');
          return JSON.stringify([
            rows,
            visibleMatches(document, '.search-empty-wrapper').length,
            document.documentElement?.scrollHeight || 0,
            feed ? feed.clientHeight : null,
          ]);
        };

        for (const request of requestedFilters) {
          const opened = await openPanel();
          if (opened.status !== 'ok') return opened;
          let found = findOption(opened.panel, request);
          if (found.status !== 'ok') {
            if (request.capability === 'location') return { status: 'location', detail: found.detail };
            if (request.capability === 'account') return { status: 'capability', detail: found.detail };
            return found;
          }
          if (isActive(found.option)) {
            continue;
          }

          const clickedAt = Date.now();
          found.option.click();
          let becameActive = false;
          while (Date.now() - clickedAt < 2500) {
            if (authBlocked()) return { status: 'auth', detail: 'login_wall' };
            if (locationBlocked()) return { status: 'location', detail: 'geolocation_denied' };
            const currentPanels = panels();
            if (currentPanels.length === 1) {
              found = findOption(currentPanels[0], request);
              if (found.status === 'ok' && isActive(found.option)) {
                becameActive = true;
                break;
              }
            }
            await sleep(100);
          }
          if (!becameActive) {
            if (request.capability === 'location') return { status: 'location', detail: 'chip_not_active' };
            if (request.capability === 'account') return { status: 'capability', detail: 'chip_not_active' };
            return { status: 'inactive', detail: request.group + '/' + request.option };
          }

          let stableSamples = 0;
          let previousSnapshot = '';
          while (Date.now() - clickedAt < ${FILTER_SETTLE_SECONDS * 1000}) {
            const currentSnapshot = snapshot();
            if (Date.now() - clickedAt >= 1500 && ready() && !busy()) {
              stableSamples = currentSnapshot === previousSnapshot ? stableSamples + 1 : 1;
              previousSnapshot = currentSnapshot;
              if (stableSamples >= 3) break;
            }
            else {
              stableSamples = 0;
              previousSnapshot = '';
            }
            await sleep(200);
          }
          if (stableSamples < 3) {
            return { status: 'timeout', detail: request.group + '/' + request.option };
          }
          const finalPanels = panels();
          const finalFound = finalPanels.length === 1 ? findOption(finalPanels[0], request) : null;
          if (!finalFound || finalFound.status !== 'ok' || !isActive(finalFound.option)) {
            return { status: 'inactive', detail: request.group + '/' + request.option };
          }
        }
        return { status: 'ok' };
      })()
    `;
}

