import { readFileSync, readdirSync, statSync, writeFileSync, mkdirSync } from 'node:fs';
import { Script, runInNewContext } from 'node:vm';
import { stripTypeScriptTypes } from 'node:module';
import assert from 'node:assert/strict';
const html = readFileSync('dist/lorelab-settings.html', 'utf8');
const css = readFileSync('src/settings/settings.css', 'utf8') + readFileSync('src/settings/flow.css', 'utf8');
const responsive = readFileSync('src/settings/responsive.css', 'utf8');
const unified = readFileSync('src/settings/unified.css', 'utf8');
const themeTokens = readFileSync('src/settings/obsidian-tokens.css', 'utf8');
const checks = [], contrasts = [];
const pass = (label, fn) => { fn(); checks.push(label); console.log('PASS', label); };
pass('独立 HTML 完整内嵌资源，脚本语法有效且位于 root 后', () => {
  assert(!/<script[^>]+src=|<link[^>]+rel="stylesheet"|<img[^>]+src="https?:|type="module"/i.test(html));
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1); new Script(scripts[0][1]);
  assert(html.indexOf('<div id="root"></div>') < html.indexOf('<script>'));
  assert(!html.includes('/@vite/client')); assert(html.includes('配置与运行管理'));
});
pass('Vite 源入口位于 src，dist 配套相对资源', () => {
  const config = readFileSync('vite.config.ts', 'utf8');
  assert(/root:\s*["']src["']/.test(config));
  assert(/outDir:\s*["']\.\.\/dist["']/.test(config));
  assert(/base:\s*["']\.\/["']/.test(config));
});
function files(dir) { return readdirSync(dir).flatMap(n => { const p = `${dir}/${n}`; return statSync(p).isDirectory() ? files(p) : [p]; }); }
pass('当前配置源码无网络/配置持久化/系统访问调用，不引入原阅读主场景', () => {
  const code = files('src/settings').filter(p => /\.tsx?$/.test(p)).map(p => readFileSync(p, 'utf8')).join('\n');
  assert(!/\bfetch\s*\(|new XMLHttpRequest|localStorage\.|sessionStorage\.|indexedDB\.|\.scrollIntoView\(|FileReader|readFileSync|child_process/.test(code));
  const main = readFileSync('src/main.tsx', 'utf8');
  assert(main.includes('SettingsApp')); assert(!main.includes('"./App"'));
  for (const p of files('src/settings')) assert(readFileSync(p, 'utf8').split('\n').length < 1000, p);
});
pass('统一导航、连接与配置分开，诊断列和手机单列规则存在；不作像素验收声明', () => {
  const app=readFileSync('src/settings/SettingsApp.tsx','utf8');
  const diagnostic=readFileSync('src/settings/DiagnosticWorkspace.tsx','utf8');
  for (const cls of ['workbench-header','workbench-sidebar','connection-overview']) assert(app.includes(cls));
  assert(!app.includes('comparison-toolbar')); assert(app.includes('连接概览')); assert(app.includes('服务配置'));
  for (const cls of ['diagnostic-groups','diagnostic-inspector','diagnostic-detail-row']) assert(diagnostic.includes(cls));
  assert(diagnostic.includes('<FormGroup title="服务状态">'));
  assert(diagnostic.includes('<FormGroup title="最近任务">'));
  assert(diagnostic.includes('<FormGroup title="诊断日志">'));
  assert(unified.includes('@media (max-width: 760px)')); assert(unified.includes('@media (max-width: 1100px)'));
  assert(unified.includes('.diagnostic-grid { display: flex; flex-direction: column; }'));
  assert(unified.includes('env(safe-area-inset-bottom)')); assert(css.includes('prefers-reduced-motion'));
});
pass('窄屏仅隐藏文字 caption，不再隐藏 Base UI span[role=switch]', () => {
  assert(!/\.service-toggle\s*>\s*span\s*\{[^}]*display:\s*none/.test(responsive));
  assert.equal((responsive.match(/\.service-toggle > \.service-toggle-caption \{ display: none; \}/g) || []).length, 2);
  assert(readFileSync('src/settings/Services.tsx', 'utf8').includes('className="service-toggle-caption"'));
});
pass('D 共用曲线几何与节点边界覆盖窄屏和宽屏，含 390 / 1280 目标', () => {
  const source = readFileSync('src/settings/flow-geometry.ts', 'utf8');
  const js = stripTypeScriptTypes(source).replace(/^export /gm, '') + '\nexports.flowGeometry = flowGeometry; exports.curvePoint = curvePoint; exports.curvePath = curvePath;';
  const sandbox = { exports: {} }; runInNewContext(js, sandbox);
  for (const width of [288, 326, 354, 394, 564, 640, 700, 904, 1150, 1600]) {
    const layout = sandbox.exports.flowGeometry(width);
    assert.equal(layout.nodes.length, 11); assert.equal(layout.curves.length, 10);
    for (const n of layout.nodes) {
      assert(n.x - n.width / 2 >= 0 && n.x + n.width / 2 <= width, `${width} ${n.id} horizontal bounds`);
      assert(n.y - 22 >= 0 && n.y + 22 <= layout.height, `${width} ${n.id} vertical bounds`);
      for (const m of layout.nodes) if (m.id !== n.id) assert(Math.abs(m.x-n.x) >= (m.width+n.width)/2 || Math.abs(m.y-n.y) >= 44, `${width} node collision ${m.id}/${n.id}`);
    }
    for (const c of layout.curves) {
      const first = sandbox.exports.curvePoint(c, 0), last = sandbox.exports.curvePoint(c, 1);
      assert.equal(first.x, c.points[0].x); assert.equal(last.y, c.points[3].y);
      assert(sandbox.exports.curvePath(c).startsWith('M '));
    }
  }
});
function tokens(block) { return Object.fromEntries([...block.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)].map(m => [m[1], m[2].trim()])); }
function resolve(palette, key, seen = new Set()) {
  assert(!seen.has(key), `Circular theme variable: ${key}`);
  seen.add(key);
  const value = palette[key];
  assert(value, `Missing theme variable: ${key}`);
  const alias = value.match(/^var\(--([a-z0-9-]+)\)$/);
  return alias ? resolve(palette, alias[1], seen) : value;
}
function luminance(hex) {
  assert(/^#[0-9a-f]{6}$/i.test(hex), `Expected opaque sRGB color: ${hex}`);
  const rgb = hex.slice(1).match(/../g).map(v => parseInt(v, 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];
}
const dark = tokens(themeTokens.match(/:root\[data-design="flow"\]\s*\{([\s\S]*?)\}/)[1]);
const light = tokens(themeTokens.match(/:root\[data-design="flow"\]\[data-theme="light"\]\s*\{([\s\S]*?)\}/)[1]);
const palettes = {dark, light: {...dark, ...light}};
pass('深浅两套主题的正文、辅助字、状态、主按钮与 hover 对比度 ≥ 4.5:1', () => {
  for (const [theme,p] of Object.entries(palettes)) {
    const lum = key => luminance(resolve(p, key));
    const pairs=[['fg','bg'],['fg','surface'],['muted','bg'],['muted','surface'],['muted','selected'],['fg','selected'],['text-on-accent','interactive-accent'],['accent','bg'],['accent','selected'],['hover-fg','hover'],['success','surface'],['danger','surface'],['warn','surface']];
    for (const [fg,bg] of pairs) {
      const a=lum(fg),b=lum(bg); const ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
      contrasts.push({theme,pair:`${fg}/${bg}`,ratio:Number(ratio.toFixed(2))});assert(ratio>=4.5,`${theme} ${fg}/${bg}: ${ratio}`);
    }
    const a=lum('accent-fg'), b=lum('primary-hover'), ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    const base=(Math.max(a,lum('interactive-accent'))+.05)/(Math.min(a,lum('interactive-accent'))+.05);
    assert(ratio>=base,`${theme} hover lowers contrast`);
    contrasts.push({theme,pair:'accent-fg/primary-hover',ratio:Number(ratio.toFixed(2))});
    const c=lum('control-border'),d=lum('surface'),br=(Math.max(c,d)+.05)/(Math.min(c,d)+.05); assert(br>=3,`${theme} control border ${br}`);
    contrasts.push({theme,pair:'control-border/surface',ratio:Number(br.toFixed(2))});
  }
});
pass('日志与表单继承同一主题；主干直线与手机纵向主干有效', () => {
  assert(!/\.style-unified \.logs-panel \{[^}]*--bg/.test(unified));
  const source=readFileSync('src/settings/flow-geometry.ts','utf8');
  const js=stripTypeScriptTypes(source).replace(/^export /gm,'')+'\nexports.flowGeometry=flowGeometry;exports.curvePath=curvePath;';
  const sandbox={exports:{}};runInNewContext(js,sandbox);
  for(const width of [288,346,640,1124]) {
    const layout=sandbox.exports.flowGeometry(width), main=layout.curves.find(c=>c.from==='soota');
    assert(main.straight);assert(sandbox.exports.curvePath(main).includes(' L '));
    const [a,,,d]=main.points;
    assert(width<640 ? a.x===d.x : a.y===d.y);
    for(const n of layout.nodes) assert(n.y-28>=0 && n.y+28<=layout.height);
  }
});
mkdirSync('output', {recursive:true});
writeFileSync('output/static-verification.json', JSON.stringify({scope:'LoreLab 配置台', status:'passed', checks, contrasts}, null, 2));
