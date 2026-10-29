/**
 * [INPUT]: 本轮确认的配置能力；全部合成初值。
 * [OUTPUT]: 配置类型、服务定义、校验与差异。
 * [POS]: 配置预览的数据边界，不读取真实配置。
 * [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
 */
export type Category = 'services' | 'capture' | 'storage' | 'diagnostics';
export type ServiceId = 'yt-dlp' | 'OpenCLI' | 'TikHub' | 'Monid' | 'Treg' | 'Cubox' | '幕布';
export interface ServiceDefinition { id: ServiceId; detail: string; group: '采集来源' | '内容连接'; credential: boolean; endpoint: string }
export const serviceDefinitions: ServiceDefinition[] = [
  { id: 'yt-dlp', detail: '视频与音频获取', group: '采集来源', credential: false, endpoint: 'https://example.com/yt-dlp' },
  { id: 'OpenCLI', detail: '网页内容获取', group: '采集来源', credential: false, endpoint: 'https://example.com/opencli' },
  { id: 'TikHub', detail: '内容获取服务', group: '采集来源', credential: true, endpoint: 'https://example.com/tikhub' },
  { id: 'Monid', detail: '内容获取服务', group: '采集来源', credential: true, endpoint: 'https://example.com/monid' },
  { id: 'Treg', detail: '内容获取服务', group: '采集来源', credential: true, endpoint: 'https://example.com/treg' },
  { id: 'Cubox', detail: '收藏读取连接', group: '内容连接', credential: true, endpoint: 'https://example.com/cubox' },
  { id: '幕布', detail: '大纲交付连接', group: '内容连接', credential: true, endpoint: 'https://example.com/mubu' },
];
export const categories: { id: Category; label: string; description: string }[] = [
  { id: 'services', label: '连接与服务', description: '管理采集来源与内容连接，分别设置启用状态和连接参数。' },
  { id: 'capture', label: '采集与费用', description: '设置获取方式、来源优先级和单任务费用限制。' },
  { id: 'storage', label: '存储与导出', description: '设置内容去向，保留源文件，保护已有修改。' },
  { id: 'diagnostics', label: '任务与诊断', description: '查看任务阶段、错误原因和可执行的恢复动作。' },
];
export interface ServiceConfig { enabled: boolean; endpoint: string; timeout: string; cache: boolean; credential: string }
export interface Config {
  services: Record<ServiceId, ServiceConfig>;
  capture: { paid: boolean; budget: string; payment: 'ask' | 'auto'; routing: 'cost' | 'manual'; priority: ServiceId[]; engine: 'auto' | 'Whisper' };
  storage: { output: string; cache: string; vault: string; subdir: string; mubuDoc: string; mubuParent: string; keepSource: boolean; conflict: 'stop' | 'rename' };
  task: { concurrency: string };
}
export const defaultPriority: ServiceId[] = ['yt-dlp', 'OpenCLI', 'Treg', 'TikHub', 'Monid'];
export const initialConfig: Config = {
  services: Object.fromEntries(serviceDefinitions.map(d => [d.id, {
    enabled: !['TikHub', 'Monid', '幕布'].includes(d.id), endpoint: d.endpoint, timeout: '60', cache: true,
    credential: ['Treg', 'Cubox'].includes(d.id) ? `DEMO_ONLY_${d.id.toUpperCase()}` : '',
  }])) as Record<ServiceId, ServiceConfig>,
  capture: { paid: false, budget: '0.50', payment: 'ask', routing: 'cost', priority: [...defaultPriority], engine: 'auto' },
  storage: { output: '/示例工作区/content', cache: '/示例工作区/cache', vault: '/示例知识库', subdir: 'LoreLab', mubuDoc: 'demo-doc-001', mubuParent: '示例学习大纲', keepSource: true, conflict: 'stop' },
  task: { concurrency: '2' },
};
export type Errors = Record<string, string>;
export function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)); }
export function validateService(id: ServiceId, config: ServiceConfig): Errors {
  const errors: Errors = {};
  if (!config.timeout.trim() || !Number.isFinite(Number(config.timeout)) || Number(config.timeout) <= 0) errors[`service.${id}.timeout`] = '超时必须大于 0 秒，输入已保留。';
  try { const u = new URL(config.endpoint); if (!['http:', 'https:'].includes(u.protocol) || !u.hostname) throw new Error(); }
  catch { errors[`service.${id}.endpoint`] = '请输入完整的 http:// 或 https:// 示例端点。'; }
  return errors;
}
export function validateConfig(config: Config): Errors {
  const errors = Object.assign({}, ...serviceDefinitions.map(d => validateService(d.id, config.services[d.id])));
  if (config.capture.paid && (!config.capture.budget.trim() || !Number.isFinite(Number(config.capture.budget)) || Number(config.capture.budget) < 0 || Number(config.capture.budget) > 10)) errors['capture.budget'] = '预算须在 0–10 USD 之间（示例约束），输入已保留。';
  if (!Number.isInteger(Number(config.task.concurrency)) || Number(config.task.concurrency) < 1 || Number(config.task.concurrency) > 5) errors['task.concurrency'] = '本次任务并发须为 1–5 的整数（示例约束）。';
  for (const key of ['output', 'cache', 'vault'] as const) if (!validPath(config.storage[key])) errors[`storage.${key}`] = '使用以 / 开头的示例绝对路径，且不能包含 .. 或特殊字符。';
  if (!config.storage.subdir.trim() || config.storage.subdir.startsWith('/') || config.storage.subdir.split('/').includes('..') || /[\\:*?"<>|]/.test(config.storage.subdir)) errors['storage.subdir'] = '子目录应为相对路径，例如 LoreLab；不能包含 ..。';
  if (!config.storage.mubuDoc.trim()) errors['storage.mubuDoc'] = '请填写示例目标文档编号。';
  return errors;
}
export function validPath(path: string) { return path.startsWith('/') && path.trim().length > 1 && !path.split('/').includes('..') && !/[\\:*?"<>|]/.test(path); }
export interface Change { key: string; label: string; before: string; after: string }
function flatten(config: Config): Record<string, [string, string]> {
  const out: Record<string, [string, string]> = {};
  for (const d of serviceDefinitions) {
    const s = config.services[d.id];
    for (const [key, label, value] of [['enabled', '启用', s.enabled ? '开启' : '关闭'], ['timeout', '超时', `${s.timeout} 秒`], ['cache', '缓存', s.cache ? '开启' : '关闭'], ['endpoint', '端点', s.endpoint], ['credential', '示例凭据', s.credential ? '已填入示例' : '未填入']] as const) out[`service.${d.id}.${key}`] = [`${d.id} · ${label}`, value];
  }
  Object.assign(out, {
    'capture.paid': ['允许付费', config.capture.paid ? '允许' : '仅免费'], 'capture.budget': ['单任务预算', `${config.capture.budget} USD`],
    'capture.payment': ['费用确认方式', config.capture.payment], 'capture.routing': ['来源优先级模式', config.capture.routing],
    'capture.priority': ['手动来源顺序', config.capture.priority.join(' → ')], 'capture.engine': ['本地转写引擎', config.capture.engine],
    'task.concurrency': ['本次任务并发', config.task.concurrency],
  });
  const labels = { output: '内容输出目录', cache: '缓存目录', vault: 'Obsidian 知识库', subdir: '知识库子目录', mubuDoc: '幕布目标文档', mubuParent: '幕布父级节点', keepSource: '保留源文件', conflict: '同名冲突处理' };
  for (const key of Object.keys(labels) as (keyof Config['storage'])[]) out[`storage.${key}`] = [labels[key], key === 'keepSource' ? (config.storage.keepSource ? '保留' : '不保留') : key === 'conflict' ? (config.storage.conflict === 'stop' ? '停止并提示' : '另存新文件') : String(config.storage[key])];
  return out;
}
export function getChanges(saved: Config, draft: Config): Change[] {
  const before = flatten(saved), after = flatten(draft);
  return Object.keys(after).filter(k => before[k][1] !== after[k][1]).map(key => ({ key, label: after[key][0], before: before[key][1], after: after[key][1] }));
}
export type ConnectionState = '就绪' | '未配置' | '待重试' | '测试中' | '待测试';
export interface Connection { state: ConnectionState; message: string; tested?: boolean }
export type Level = '信息' | '警告' | '错误';
export interface Log { id: number; time: string; level: Level; component: string; message: string; detail: string }
export interface Job { id: string; name: string; provider: ServiceId; state: '等待' | '处理中' | '待重试' | '已完成'; stage: string; error?: string; recovery?: string }
export const initialJobs: Job[] = [
  { id: 'TASK-104', name: '示例网页内容获取', provider: 'OpenCLI', state: '等待', stage: '等待运行参数确认' },
  { id: 'TASK-103', name: '示例音频原文提取', provider: 'yt-dlp', state: '处理中', stage: '正在保留原文与独立时间轴' },
  { id: 'TASK-102', name: '示例来源内容获取', provider: 'Treg', state: '待重试', stage: '内容尚未获取', error: '示例服务响应超时，未返回正文。', recovery: '检查连接与超时参数后重试；不会删除源文件。' },
  { id: 'TASK-101', name: '示例收藏连接检查', provider: 'Cubox', state: '已完成', stage: '连接检查完成；未读取收藏' },
];
