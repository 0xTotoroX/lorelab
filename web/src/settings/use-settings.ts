/**
 * [INPUT]: 配置模型与 React 状态。
 * [OUTPUT]: 四个风格共享的草稿、连接测试、任务和日志。
 * [POS]: 纯会话控制器，无网络、文件或 storage 调用。
 * [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
 */
import { useEffect, useRef, useState } from 'react';
import { clone, getChanges, initialConfig, initialJobs, serviceDefinitions, validateConfig, validateService, type Config, type Connection, type Errors, type Job, type Level, type Log, type ServiceId } from './model';
export function useSettings() {
  const [saved, setSaved] = useState<Config>(() => clone(initialConfig));
  const [draft, setDraft] = useState<Config>(() => clone(initialConfig));
  const [errors, setErrors] = useState<Errors>({});
  const [saveMessage, setSaveMessage] = useState('');
  const [connections, setConnections] = useState<Record<ServiceId, Connection>>(() => Object.fromEntries(serviceDefinitions.map(d => [d.id, { state: d.id === 'Treg' ? '待重试' : d.credential && !initialConfig.services[d.id].credential ? '未配置' : '就绪', message: d.id === 'Treg' ? '上次示例请求超时，可重新测试。' : d.credential && !initialConfig.services[d.id].credential ? '缺少示例凭据' : '示例连接测试通过' }])) as Record<ServiceId, Connection>);
  const [jobs, setJobs] = useState<Job[]>(() => clone(initialJobs));
  const [logs, setLogs] = useState<Log[]>([
    { id: 1, time: '10:24:06', level: '信息', component: 'yt-dlp', message: '示例执行环境检查通过', detail: '只读演示检查；没有运行本机命令。' },
    { id: 2, time: '10:24:08', level: '错误', component: 'Treg', message: '响应超时，任务 TASK-102 等待重试', detail: '原因：示例响应未在 60 秒内返回。恢复：检查服务连接，必要时调整超时，然后重试任务。' },
    { id: 3, time: '10:24:10', level: '警告', component: 'Monid', message: '缺少示例凭据，尚不能测试连接', detail: '恢复：在 Monid 配置面板点击“填入示例配置”，然后测试。启用开关不会自动验证连接。' },
  ]);
  const [diagnosing, setDiagnosing] = useState(false);
  const [runningJobs, setRunningJobs] = useState<string[]>([]);
  const [diagnosis, setDiagnosis] = useState<{ name: string; state: string; message: string }[]>([]);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const latest = useRef(draft); latest.current = draft;
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  const later = (action: () => void, ms = 550) => { timers.current.push(setTimeout(action, ms)); };
  const log = (level: Level, component: string, message: string, detail: string) => setLogs(old => [...old, { id: Date.now() + Math.random(), time: new Date().toLocaleTimeString('zh-CN', { hour12: false }), level, component, message, detail }]);
  const update = (mutate: (next: Config) => void) => { setDraft(current => { const next = clone(current); mutate(next); return next; }); setErrors({}); setSaveMessage(''); };
  const updateService = (id: ServiceId, patch: Partial<Config['services'][ServiceId]>) => {
    update(next => Object.assign(next.services[id], patch));
    if ('endpoint' in patch || 'timeout' in patch || 'credential' in patch) setConnections(current => ({ ...current, [id]: { state: '待测试', message: '连接参数已变更，请重新测试。' } }));
  };
  const fillExample = (id: ServiceId) => {
    updateService(id, { credential: `DEMO_ONLY_${id === '幕布' ? 'MUBU' : id.toUpperCase()}`, endpoint: serviceDefinitions.find(d => d.id === id)!.endpoint });
    log('信息', id, '已填入合成示例配置', '下一步：点击测试连接。真实凭据未读取，配置尚未保存。');
  };
  const testConnection = (id: ServiceId) => {
    const config = clone(latest.current.services[id]);
    const problem = validateService(id, config);
    if (Object.keys(problem).length) { setErrors(problem); setConnections(current => ({ ...current, [id]: { state: '待重试', message: Object.values(problem)[0], tested: true } })); return; }
    setConnections(current => ({ ...current, [id]: { state: '测试中', message: '正在模拟连接测试…' } }));
    later(() => {
      if (JSON.stringify(latest.current.services[id]) !== JSON.stringify(config)) { setConnections(current => ({ ...current, [id]: { state: '待测试', message: '参数已变更，请重新测试。' } })); return; }
      const missing = serviceDefinitions.find(d => d.id === id)!.credential && !config.credential;
      setConnections(current => ({ ...current, [id]: { state: missing ? '未配置' : '就绪', message: missing ? '缺少示例凭据' : '模拟测试成功 · 未访问真实服务', tested: true } }));
      log(missing ? '错误' : '信息', id, missing ? '连接测试未通过：缺少示例凭据' : '模拟连接测试成功', missing ? '恢复：打开配置面板，填入示例配置后重试。' : '示例端点与参数校验通过；启用状态保持不变。');
    });
  };
  const save = () => {
    const problems = validateConfig(draft); setErrors(problems);
    if (Object.keys(problems).length) { setSaveMessage('请先修正配置错误，输入已保留'); return false; }
    const count = getChanges(saved, draft).length;
    setSaved(clone(draft)); setSaveMessage('已保存到预览');
    log('信息', '配置', `已保存 ${count} 项修改到预览`, '仅更新本页会话。未写入磁盘配置，刷新后恢复初值。');
    return true;
  };
  const undo = () => {
    setDraft(clone(saved)); setErrors({}); setSaveMessage('已撤销未保存修改');
    setConnections(current => Object.fromEntries(serviceDefinitions.map(d => [d.id, JSON.stringify(saved.services[d.id]) === JSON.stringify(draft.services[d.id]) ? current[d.id] : { state: d.credential && !saved.services[d.id].credential ? '未配置' : '待测试', message: '已恢复上次保存的参数。' }])) as Record<ServiceId, Connection>);
  };
  const runJob = (id: string) => {
    if (runningJobs.includes(id)) return;
    const job = jobs.find(j => j.id === id)!;
    setRunningJobs(current => [...current, id]);
    setJobs(current => current.map(j => j.id === id ? { ...j, state: '处理中', stage: '重新检查来源并获取内容', error: undefined } : j));
    log('信息', job.provider, `${id} 已开始模拟处理`, '保留原任务与源文件；只演示任务状态变化。');
    later(() => {
      const config = latest.current.services[job.provider];
      const missing = serviceDefinitions.find(d => d.id === job.provider)!.credential && !config.credential;
      const problem = !config.enabled ? '来源服务未启用' : Object.values(validateService(job.provider, config))[0] || (missing ? '缺少示例凭据' : '');
      setJobs(current => current.map(j => j.id === id ? { ...j, state: problem ? '待重试' : '已完成', stage: problem ? '连接检查未通过' : '原文获取模拟完成', error: problem || undefined, recovery: problem ? '检查对应服务的启用状态和示例配置，再重试。' : undefined } : j));
      log(problem ? '错误' : '信息', job.provider, problem ? `${id} 未完成：${problem}` : `${id} 模拟处理完成`, problem ? '恢复：在连接与服务中修正配置，再重试任务。' : '仅演示正文获取，不自动生成笔记或文章。');
      setRunningJobs(current => current.filter(value => value !== id));
    }, 800);
  };
  const diagnose = () => {
    setDiagnosing(true); log('信息', '诊断', '开始组件只读诊断演示', '检查合成配置，不运行本机 doctor，不读取账号。');
    later(() => {
      const cfg = latest.current;
      const rows = serviceDefinitions.map(d => ({ name: d.id, state: d.credential && !cfg.services[d.id].credential ? '需配置' : Object.keys(validateService(d.id, cfg.services[d.id])).length ? '需修正' : '通过', message: d.credential && !cfg.services[d.id].credential ? '缺少示例凭据；填入示例配置后再测试。' : Object.values(validateService(d.id, cfg.services[d.id]))[0] || '示例参数检查完成，未检查真实账号。' }));
      setDiagnosis(rows); setDiagnosing(false);
      log(rows.some(r => r.state !== '通过') ? '警告' : '信息', '诊断', '组件诊断演示完成', rows.filter(r => r.state !== '通过').map(r => `${r.name}：${r.message}`).join('；') || '示例参数检查通过。');
    }, 650);
  };
  return { saved, draft, errors, saveMessage, connections, jobs, runningJobs, logs, diagnosing, diagnosis, changes: getChanges(saved, draft), update, updateService, fillExample, testConnection, save, undo, runJob, diagnose, log };
}
export type SettingsStore = ReturnType<typeof useSettings>;
