import { JSDOM, VirtualConsole } from 'jsdom';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import assert from 'node:assert/strict';
import { within, waitFor } from '@testing-library/dom';
import userEvent from '@testing-library/user-event';

// Execute the actual production bundle. JSDOM does not measure visual layout.
const report = { scope: 'LoreLab 配置台交互回归', environment: 'JSDOM / production standalone bundle', browserVisualCheck: 'JSDOM 不验证视觉；响应式与像素布局需要实际浏览器检查', checks: [], errors: [], network: [] };
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', error => { if (!error.message.includes('Could not parse CSS stylesheet')) report.errors.push(error.message); });
const html = readFileSync('dist/lorelab-settings.html', 'utf8');
const motionMedia = [], intersections = [], resizeObservers = [];
let particleDraws = 0;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const options = {
  url: 'https://lorelab.example/?view=overview', runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole,
  beforeParse(w) {
    w.matchMedia = query => {
      const listeners = new Set();
      const media = { matches: false, media: query, addListener() {}, removeListener() {}, addEventListener(_type, fn) { listeners.add(fn); }, removeEventListener(_type, fn) { listeners.delete(fn); }, dispatchEvent() { listeners.forEach(fn => fn({ matches: media.matches })); return true; } };
      if (query.includes('prefers-reduced-motion')) motionMedia.push(media);
      return media;
    };
    w.ResizeObserver = class { constructor(callback) { this.callback = callback; this.active = true; resizeObservers.push(this); } observe(target) { this.target = target; } unobserve() {} disconnect() { this.active = false; } };
    w.IntersectionObserver = class { constructor(callback) { this.callback = callback; this.active = true; intersections.push(this); } observe() {} disconnect() { this.active = false; } };
    // Canvas drawing is instrumented, not rasterized. No JSDOM canvas warning is suppressed.
    w.HTMLCanvasElement.prototype.getContext = () => ({ setTransform() {}, clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, arc() { particleDraws++; }, fill() {} });
    Object.defineProperty(w, 'devicePixelRatio', { configurable: true, value: 3 });
    w.HTMLElement.prototype.scrollTo = function (o) { this.scrollTop = o.top || 0; };
    w.HTMLElement.prototype.scrollIntoView = () => {}; // Base UI internal focus helper, no layout claim.
    w.fetch = (...args) => { report.network.push(String(args[0])); throw new Error('禁止网络请求'); };
    w.XMLHttpRequest.prototype.open = (...args) => { report.network.push(String(args[1])); throw new Error('禁止网络请求'); };
    w.PointerEvent = class extends w.MouseEvent { constructor(type, init = {}) { super(type, init); this.pointerId = init.pointerId || 1; this.pointerType = init.pointerType || 'mouse'; this.isPrimary = init.isPrimary ?? true; } };
    w.HTMLElement.prototype.hasPointerCapture = () => false;
    w.HTMLElement.prototype.setPointerCapture = () => {};
    w.HTMLElement.prototype.releasePointerCapture = () => {};
  }
};
const dom = new JSDOM(html, options);
const w = dom.window;
Object.assign(globalThis, { window: w, document: w.document, HTMLElement: w.HTMLElement, Node: w.Node });
const doc = within(w.document.body);
const user = userEvent.setup({ document: w.document });
const wait = fn => waitFor(fn, { container: w.document.body, timeout: 5000 });
const button = (name, scope = doc) => scope.getByRole('button', { name, exact: true });
const click = async (name, scope = doc) => user.click(button(name, scope));
const dialog = () => within(doc.getByRole('dialog'));
const row = id => within(w.document.querySelector(`[data-od-id="service-row-${id.toLowerCase()}"]`));
const check = async (name, fn) => { await fn(); report.checks.push(name); console.log('PASS', name); };
const input = async (element, value) => { await user.clear(element); await user.type(element, value); };
const style = async name => user.click(doc.getByRole('button', { name: new RegExp(name) }));
const select = async (name, value) => { doc.getByRole('combobox', { name, exact: true }).focus(); await user.keyboard('{ArrowDown}'); await user.click(await doc.findByRole('option', { name: value, exact: true })); };
const close = async () => { await user.keyboard('{Escape}'); await wait(() => assert(!doc.queryByRole('dialog'))); };
const tab = async name => user.click(doc.getByRole('tab', { name, exact: true }));
const editor = () => within(w.document.querySelector('.inline-editor'));
const edge = id => w.document.querySelector(`[data-flow-edge="${id}"]`);
try {
  await wait(() => assert(doc.getByRole('heading', { name: '连接与服务', level: 1 })));
  await check('统一导航与两种连接视图，无风格比较栏和阅读器主场景', async () => {
    assert.equal(w.document.documentElement.dataset.design, 'flow');
    assert.equal(w.document.querySelectorAll('.category-navigation button').length, 4);
    assert(!w.document.querySelector('.comparison-toolbar'));
    for (const name of ['连接与服务', '采集与费用', '存储与导出', '任务与诊断']) assert(button(name));
    for (const name of ['连接概览', '服务配置']) assert(doc.getByRole('tab', { name }));
    assert(!doc.queryByRole('button', { name: '添加来源' }));
    assert(doc.getByText('交互预览 · 示例配置'));
    assert.equal(edge('yt-dlp-soota').dataset.active, 'true');
    for (const id of ['TikHub-soota','Monid-soota','Treg-soota','lorelab-mubu']) assert.equal(edge(id).dataset.active, 'false');
  });
  await check('键盘选择节点、失败反馈、聚焦配置、填入示例并重测，概览状态同步', async () => {
    button('选择连接 TikHub').focus(); await user.keyboard('{Enter}');
    assert(doc.getByRole('heading', { name: 'TikHub', exact: true }));
    await click('测试当前连接');
    assert.equal(edge('TikHub-soota').dataset.testing, 'true');
    await wait(() => assert.equal(edge('TikHub-soota').dataset.testing, 'false'));
    assert(w.document.querySelector('.connection-summary').textContent.includes('缺少示例凭据'));
    await click('配置参数');
    assert.equal(w.document.querySelectorAll('[data-od-id^="service-row-"]').length, 7);
    assert.equal(w.document.activeElement, editor().getByRole('textbox', { name: '示例端点' }));
    await click('填入示例配置', editor());
    assert.equal(editor().getByRole('textbox', { name: '示例凭据' }).value, 'DEMO_ONLY_TIKHUB');
    assert(editor().getByRole('textbox', { name: '示例凭据' }).readOnly);
    await user.click(doc.getByRole('switch', { name: '启用 TikHub' }));
    await click('测试连接 TikHub', editor());
    await wait(() => assert(editor().getByText('模拟测试成功 · 未访问真实服务')));
    await tab('连接概览');
    assert.equal(button('选择连接 TikHub').getAttribute('aria-pressed'), 'true');
    assert.equal(edge('TikHub-soota').dataset.active, 'true');
    await click('保存配置'); assert(button('保存配置').disabled);
  });
  await check('动画暂停/继续、减少动效、离屏和后台暂停，视图切换保留暂停状态并清理资源', async () => {
    const stage = () => w.document.querySelector('.flow-stage');
    assert.equal(stage().dataset.motion, 'running');
    await delay(45); const started=particleDraws; await delay(45); assert(particleDraws>started);
    await click('暂停流动'); await wait(() => assert.equal(stage().dataset.motion, 'paused'));
    await delay(25); const paused=particleDraws; await delay(45); assert.equal(particleDraws,paused);
    await tab('服务配置');
    assert(intersections.every(o=>!o.active)); assert(resizeObservers.filter(o=>o.target?.classList.contains('flow-stage')).every(o=>!o.active));
    await tab('连接概览'); assert.equal(stage().dataset.motion,'paused');
    await click('继续流动'); await wait(()=>assert.equal(stage().dataset.motion,'running'));
    const media=motionMedia.at(-1); media.matches=true; media.dispatchEvent();
    await wait(()=>assert.equal(stage().dataset.motion,'reduced'));
    await click('选择连接 Cubox'); assert(doc.getByRole('heading',{name:'Cubox',exact:true}));
    media.matches=false; media.dispatchEvent(); await wait(()=>assert.equal(stage().dataset.motion,'running'));
    const observer=intersections.findLast(o=>o.active); observer.callback([{isIntersecting:false}]);
    await wait(()=>assert.equal(stage().dataset.motion,'paused'));
    observer.callback([{isIntersecting:true}]); await wait(()=>assert.equal(stage().dataset.motion,'running'));
    Object.defineProperty(w.document,'hidden',{configurable:true,value:true}); w.document.dispatchEvent(new w.Event('visibilitychange'));
    await wait(()=>assert.equal(stage().dataset.motion,'paused'));
    Object.defineProperty(w.document,'hidden',{configurable:true,value:false}); w.document.dispatchEvent(new w.Event('visibilitychange'));
    await wait(()=>assert.equal(stage().dataset.motion,'running'));
    stage().getBoundingClientRect=()=>({width:354}); resizeObservers.filter(o=>o.active&&o.target?.classList.contains('flow-stage')).forEach(o=>o.callback([]));
    await wait(()=>assert.equal(stage().dataset.compact,'true')); assert.equal(w.document.querySelector('.flow-particles').width,708);
  });
  await check('连接图快捷入口也受未保存保护，取消或放弃后导航符合预期', async()=>{
    await user.click(doc.getByRole('switch',{name:'启用 Cubox'}));
    await click('Soota：打开采集与费用'); await click('继续编辑',dialog());
    assert(doc.getByRole('heading',{name:'连接与服务',level:1}));
    await click('内容目录：打开存储与导出'); await click('放弃修改',dialog());
    await wait(()=>assert(doc.getByRole('heading',{name:'存储与导出',level:1})));
    await click('连接与服务'); await tab('服务配置');
  });
  await check('分组配置校验保留错误输入；差异、保存与撤销有效', async()=>{
    await click('配置 Monid');
    await user.click(doc.getByRole('switch',{name:'启用 Monid'}));
    await click('测试连接 Monid',editor());
    await wait(()=>assert(editor().getByText('缺少示例凭据')));
    await click('填入示例配置',editor());
    await input(editor().getByRole('spinbutton',{name:'超时 秒'}),'0');
    await click('测试连接 Monid',editor());
    assert(editor().getByRole('alert').textContent.includes('超时必须大于 0'));
    assert.equal(editor().getByRole('spinbutton',{name:'超时 秒'}).value,'0');
    await click('保存配置'); assert(!button('保存配置').disabled);
    await input(editor().getByRole('spinbutton',{name:'超时 秒'}),'90');
    await click('查看修改');
    for(const text of ['Monid · 启用','Monid · 超时','关闭','开启','60 秒','90 秒']) assert(dialog().getByText(text,{exact:true}));
    await close(); await click('保存配置'); assert(button('保存配置').disabled);
    await user.click(doc.getByRole('switch',{name:'启用 Monid'})); await click('撤销');
    assert.equal(doc.getByRole('switch',{name:'启用 Monid'}).getAttribute('aria-checked'),'true');
    await click('采集与费用');
  });
  await check('免费默认、预算边界与手动来源顺序，保存后切换', async()=>{
    const budget=()=>doc.getByRole('spinbutton',{name:'单任务预算 USD'});
    assert(budget().disabled); await user.click(doc.getByRole('switch',{name:'允许付费'}));
    for(const value of ['-1','11']) {await input(budget(),value); await click('保存配置'); assert.equal(budget().value,value); assert(doc.getByRole('alert').textContent.includes('0–10 USD'));}
    await input(budget(),'3'); await click('保存配置'); assert(button('保存配置').disabled);
    await tab('手动顺序（manual）'); button('上移 OpenCLI').focus(); await user.keyboard('{Enter}');
    assert(w.document.querySelector('.priority-list li').textContent.includes('OpenCLI'));
    await click('恢复默认顺序'); assert(w.document.querySelector('.priority-list li').textContent.includes('yt-dlp'));
    await click('存储与导出'); await click('保存后切换',dialog());
    await wait(()=>assert(doc.getByRole('heading',{name:'存储与导出',level:1})));
  });
  await check('路径错误保留、目录模拟校验、源文件与冲突保护',async()=>{
    assert.equal(doc.getByRole('switch',{name:'保留源文件'}).getAttribute('aria-checked'),'true');
    assert(doc.getByRole('combobox',{name:'同名内容冲突'}).textContent.includes('停止并提示'));
    const path=doc.getByRole('textbox',{name:'内容输出目录'});
    await input(path,'relative/content'); await click('检查目录 内容输出目录'); assert(doc.getByText(/路径无效：需以/));
    await click('保存配置'); assert.equal(path.value,'relative/content');
    await input(path,'/示例输出/content'); await click('检查目录 内容输出目录'); assert(doc.getByText('模拟目录检查通过，未访问文件系统。'));
    await click('任务与诊断'); await click('保存后切换',dialog());
    await wait(()=>assert(doc.getByRole('heading',{name:'任务与诊断',level:1})));
  });
  await check('诊断七项服务、错误详情、关联日志和配置跳转构成排错流程',async()=>{
    assert.equal(w.document.querySelectorAll('.health-table tbody tr').length,7);
    await click('查看任务 TASK-102');
    assert(doc.getByText('示例服务响应超时，未返回正文。'));
    await click('运行组件诊断');
    await wait(()=>assert(w.document.querySelector('.health-table').textContent.includes('需配置')));
    assert(!w.document.querySelector('.health-table').textContent.includes('未检查'));
    await click('检查服务 幕布');
    assert(doc.getByRole('heading',{name:'幕布 · 连接详情'}));
    assert.equal(w.document.activeElement,w.document.querySelector('.diagnostic-inspector'));
    await click('仅看 幕布');
    assert(w.document.querySelector('.empty-logs')); await click('清除筛选');
    await click('检查 幕布 配置');
    await wait(()=>assert(doc.getByRole('heading',{name:'幕布 连接参数'})));
    await click('填入示例配置',editor());
    await click('任务与诊断'); await click('继续编辑',dialog());
    assert(doc.getByRole('heading',{name:'幕布 连接参数'}));
    await click('任务与诊断'); await click('保存后切换',dialog());
    await wait(()=>assert(doc.getByRole('heading',{name:'任务与诊断',level:1})));
    await click('检查服务 幕布'); await click('测试连接 幕布',within(w.document.querySelector('.diagnostic-inspector')));
    await wait(()=>assert(w.document.querySelector('.service-inspection').textContent.includes('模拟测试成功')));
    assert(w.document.querySelector('.service-inspection').textContent.includes('已关闭'));
  });
  await check('任务重试更新结果，筛选空态可以恢复，详情与日志上下文联动',async()=>{
    await click('查看任务 TASK-102'); assert(doc.getByText('示例服务响应超时，未返回正文。'));
    await click('仅看 Treg');
    assert([...w.document.querySelectorAll('.log-entry')].every(e=>e.textContent.includes('Treg')));
    await click('模拟重试');
    await wait(()=>assert(w.document.querySelector('[data-od-id="task-task-102"]').textContent.includes('已完成')));
    assert(!w.document.querySelector('.task-error'));
    await select('任务状态','待重试'); assert(w.document.querySelector('.empty-task')); await click('显示全部任务');
    await click('运行 TASK-104'); await wait(()=>assert(w.document.querySelector('[data-od-id="task-task-104"]').textContent.includes('已完成')));
    await click('运行 TASK-103'); await wait(()=>assert(w.document.querySelector('[data-od-id="task-task-103"]').textContent.includes('已完成')));
    await click('查看任务 TASK-102');
  });
  await check('日志关键词、级别与关联筛选可组合，展开详情和清空筛选有效',async()=>{
    await select('日志级别','错误');
    const search=doc.getByRole('textbox',{name:'搜索日志'}); await input(search,'TASK-102');
    assert(w.document.querySelectorAll('.log-entry').length>0);
    assert([...w.document.querySelectorAll('.log-entry')].every(e=>e.dataset.level==='错误'&&e.textContent.includes('Treg')));
    await user.click(w.document.querySelector('.log-summary')); assert(w.document.querySelector('.log-detail').textContent.includes('60 秒'));
    await input(search,'no-match-123'); assert(w.document.querySelector('.empty-logs')); await click('清除筛选');
    assert.equal(search.value,''); assert(button('仅看 Treg').getAttribute('aria-pressed')==='false');
    assert(doc.getByRole('combobox',{name:'日志级别'}).textContent.includes('全部级别'));
  });
  await check('已保存配置跨页保留，无网络和 Web Storage，刷新恢复初始示例',async()=>{
    await click('连接与服务'); await tab('服务配置');
    await click('配置 Monid'); assert.equal(doc.getByRole('spinbutton',{name:'超时 秒'}).value,'90');
    assert.equal(doc.getByRole('switch',{name:'启用 Monid'}).getAttribute('aria-checked'),'true');
    assert.equal(report.network.length,0); assert.equal(w.localStorage.length,0); assert.equal(w.sessionStorage.length,0);
    const fresh=new JSDOM(html,options);
    await waitFor(()=>assert(fresh.window.document.querySelector('[data-flow-edge="TikHub-soota"]')),{container:fresh.window.document.body});
    assert.equal(fresh.window.document.querySelector('[data-flow-edge="TikHub-soota"]').dataset.active,'false');
    assert.equal(fresh.window.document.documentElement.dataset.design,'flow'); fresh.window.close();
    assert.equal(report.errors.length,0,report.errors.join('\n'));
  });
  report.status='passed';
} catch(error) { report.status='failed'; report.failure=error.message.slice(0,3500); console.error('FAIL',error.message.slice(0,3500)); process.exitCode=1; }
finally { mkdirSync('output',{recursive:true}); writeFileSync('output/verification.json',JSON.stringify(report,null,2)); dom.window.close(); }
