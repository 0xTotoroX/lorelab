// Synthetic DOM and virtual clock: no browser, account, network or private IDs.
import assert from 'node:assert/strict';
let now = 0;
Date.now = () => now;
globalThis.setTimeout = (callback, ms) => { now += ms; callback(); };
globalThis.getComputedStyle = element => ({
  display: 'block', visibility: 'visible', opacity: '1', pointerEvents: 'auto', ...element.style,
});
const box = {left: 0, top: 0, width: 100, height: 20};
function element(text = '', extras = {}) {
  return {
    textContent: text, children: [], style: {},
    getBoundingClientRect: () => box,
    closest: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    ...extras,
  };
}
const defaults = [
  {group: '排序依据', option: '综合'},
  {group: '笔记类型', option: '不限'},
  {group: '发布时间', option: '不限'},
  {group: '搜索范围', option: '不限'},
  {group: '位置距离', option: '不限'},
];
async function run({duplicate, ghost, initial = '综合', missing, mismatch, unknownRect,
                    request = defaults, unresponsive = false, notReady = false} = {}) {
  now = 0;
  const clicks = [], inspected = new Set();
  const states = {'排序依据': initial};
  const groups = defaults.map(({group, option: defaultOption}) => {
    const options = [];
    for (const name of group === '排序依据' ? ['综合', '最新'] : [defaultOption]) {
      const chip = (decoy = false, extra = {}) => element(name, {
        classList: {contains: () => (states[group] || defaultOption) === name},
        click: () => {
          clicks.push(decoy ? 'ghost' : `${group}/${name}`);
          if (!decoy && !unresponsive) states[group] = name;
        },
        ...extra,
      });
      if (group === '排序依据' && name === '综合') {
        if (ghost) options.push(chip(true, {
          closest: () => ['marked', 'ancestor'].includes(ghost) ? {} : null,
          style: ghost === 'transparent' ? {opacity: '1e-05'} :
                 ghost === 'pointer' ? {pointerEvents: 'none'} : {},
        }));
        if (!missing) options.push(chip());
        if (duplicate) options.push(chip(false, {
          getBoundingClientRect: () => unknownRect ? {width: 100, height: 20} :
            duplicate === 'distinct' ? {...box, top: 120} : box,
          ...(mismatch ? {classList: {contains: () => false}} : {}),
        }));
      } else options.push(chip());
    }
    return element('', {
      children: [element(group, {tagName: 'SPAN'})],
      querySelectorAll: () => { inspected.add(group); return options; },
    });
  });
  const panel = element('', {querySelectorAll: () => groups});
  const row = element('Synthetic result');
  globalThis.document = {
    body: {innerText: ''}, documentElement: {scrollHeight: 100}, querySelector: () => null,
    querySelectorAll: selector => {
      if (selector.endsWith('> .filter-panel')) return [panel];
      if (selector.startsWith('section.note-item')) return notReady ? [] : [row];
      return [];
    },
  };
  const result = await eval(buildApplySearchFiltersJs(request));
  return {result, clicks, inspected: [...inspected], states};
}
// Exercise the unmodified upstream loop, including all default filters.
let result = await run();
assert.deepEqual(result.result, {status: 'ok'});
assert.equal(result.inspected.length, 5);
result = await run({duplicate: 'same'});
assert.equal(result.result.status, PATCHED ? 'ok' : 'layout');
assert.deepEqual(result.clicks, []);
for (const ghost of ['marked', 'ancestor', 'transparent', 'pointer']) {
  result = await run({ghost, initial: '最新'});
  assert.equal(result.result.status, PATCHED ? 'ok' : 'layout');
  if (PATCHED) {
    assert.deepEqual(result.clicks, ['排序依据/综合']);
    assert.equal(result.states['排序依据'], '综合');
    assert.equal(result.inspected.length, 5);
  }
}
for (const options of [{duplicate: 'distinct'}, {duplicate: 'same', mismatch: true},
                       {duplicate: 'same', unknownRect: true}]) {
  result = await run(options);
  assert.deepEqual(result.result, {status: 'layout', detail: 'ambiguous_option'});
}
result = await run({missing: true});
assert.deepEqual(result.result, {status: 'layout', detail: 'option_not_found'});
result = await run({request: [{group: '排序依据', option: '最新'}]});
assert.deepEqual(result.result, {status: 'ok'});
assert.deepEqual(result.clicks, ['排序依据/最新']);
result = await run({initial: '最新', unresponsive: true});
assert.equal(result.result.status, 'inactive');
result = await run({initial: '最新', notReady: true});
assert.equal(result.result.status, 'timeout');
