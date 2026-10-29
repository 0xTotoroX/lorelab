/**
 * [INPUT]: 共享任务和日志；当前检查对象。
 * [OUTPUT]: 任务筛选、错误恢复详情、可筛选展开的日志；支持外置分组标题和行内详情。
 * [POS]: 统一诊断工作区的可复用内容；只操作示例状态。
 * [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
 */
import { Fragment, useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight, Filter, LoaderCircle, Play, RotateCcw, Search } from 'lucide-react';
import { Button, Input, SelectField } from '../components/ui';
import type { Job, Level } from './model';
import type { SettingsStore } from './use-settings';

export function TaskDetails({ job, store }: { job: Job; store: SettingsStore }) {
  const busy = store.runningJobs.includes(job.id);
  return <div className="task-details" data-od-id="task-detail">
    <h3>{job.name}</h3><dl><div><dt>任务</dt><dd>{job.id}</dd></div><div><dt>来源</dt><dd>{job.provider}</dd></div>
      <div><dt>状态</dt><dd>{job.state}</dd></div><div><dt>当前阶段</dt><dd>{job.stage}</dd></div></dl>
    {job.error && <div className="task-error"><strong>错误原因</strong><p>{job.error}</p><strong>恢复动作</strong><p>{job.recovery}</p></div>}
    {job.state !== '已完成' && <Button variant="outline" disabled={busy} onClick={() => store.runJob(job.id)}>
      {busy ? <LoaderCircle className="spin" size={15} /> : <RotateCcw size={15} />}
      {busy ? '正在模拟处理' : job.state === '待重试' ? '模拟重试' : '继续模拟处理'}</Button>}
    {job.state === '已完成' && <p className="control-help">模拟任务已完成，源文件保持不变。</p>}
  </div>;
}

export function Diagnostics({ store, selected, select, showHeading = true, detail, onFilterChange }: { store: SettingsStore; selected: string; select: (id: string) => void; showHeading?: boolean; detail?: ReactNode; onFilterChange?: () => void }) {
  const [filter, setFilter] = useState('全部任务');
  const jobs = store.jobs.filter(j => filter === '全部任务' || j.state === filter);
  return <section className="task-section" aria-label="最近任务">
    <div className="section-heading">{showHeading && <h2>最近任务</h2>}
      <SelectField label="任务状态" value={filter} onChange={value => { setFilter(value); onFilterChange?.(); }} options={['全部任务', '等待', '处理中', '待重试', '已完成']} /></div>
    <table className="task-table"><thead><tr><th>任务</th><th>状态 / 阶段</th><th>操作</th></tr></thead><tbody>
      {jobs.map(j => <Fragment key={j.id}><tr className={selected === j.id ? 'selected-task' : ''} data-od-id={'task-' + j.id.toLowerCase()}>
        <td><Button variant="ghost" className="task-name" onClick={() => select(j.id)} aria-label={'查看任务 ' + j.id} aria-pressed={selected === j.id}>
          <span>{j.name}<small>{j.id} · {j.provider}</small></span></Button></td>
        <td><span className={'task-state ' + (j.state === '待重试' ? 'text-error' : '')}>
          {store.runningJobs.includes(j.id) && <LoaderCircle className="spin" size={13} />}{j.state}</span><small className="task-stage">{j.stage}</small></td>
        <td>{j.state === '已完成' ? <Button variant="ghost" onClick={() => select(j.id)} aria-label={'查看结果 ' + j.id}>查看结果</Button> :
          <Button variant="ghost" disabled={store.runningJobs.includes(j.id)} onClick={() => { select(j.id); store.runJob(j.id); }}
            aria-label={(j.state === '待重试' ? '重试 ' : '运行 ') + j.id}>
            {j.state === '待重试' ? <RotateCcw size={14} /> : <Play size={14} />}
            {store.runningJobs.includes(j.id) ? '处理中' : j.state === '待重试' ? '重试' : j.state === '等待' ? '开始' : '继续'}</Button>}</td>
      </tr>{detail && selected === j.id && <tr className="diagnostic-detail-row"><td colSpan={3}>{detail}</td></tr>}</Fragment>)}
    </tbody></table>
    {!jobs.length && <div className="empty-task"><p>没有“{filter}”的任务。</p><Button variant="ghost" onClick={() => setFilter('全部任务')}>显示全部任务</Button></div>}
  </section>;
}

export function LogsPanel({ store, context, showHeading = true }: { store: SettingsStore; context: string; showHeading?: boolean }) {
  const [level, setLevel] = useState('全部级别');
  const [query, setQuery] = useState('');
  const [related, setRelated] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const search = query.trim().toLowerCase();
  const filtered = store.logs.filter(l => (level === '全部级别' || l.level === level) &&
    (!related || l.component === context) &&
    (!search || [l.component, l.message, l.detail, l.time].join(' ').toLowerCase().includes(search))).slice().reverse();
  return <section className="logs-panel logs-open" data-od-id="diagnostic-logs" aria-label="诊断日志">
    <div className="logs-heading">{showHeading ? <h2>诊断日志 <span className="log-count">{filtered.length}</span></h2> : <span className="log-count">{filtered.length} 条记录</span>}
      <Button variant="ghost" aria-pressed={related} className={related ? 'log-context-active' : ''} onClick={() => setRelated(v => !v)}>
        <Filter size={14} />{'仅看 ' + context}</Button></div>
    <div className="log-filters"><label className="log-search"><Search size={15} /><Input aria-label="搜索日志" placeholder="搜索错误、组件或消息" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <SelectField label="日志级别" value={level} onChange={setLevel} options={['全部级别', '信息', '警告', '错误']} /></div>
    <div className="log-entries" role="log" aria-label="合成诊断日志">
      {filtered.map(l => <div className="log-entry" key={l.id} data-level={l.level}><Button variant="ghost" className="log-summary"
        onClick={() => setExpanded(expanded === l.id ? null : l.id)} aria-expanded={expanded === l.id}>
        <time>{l.time}</time><span className={'log-level level-' + ({ 信息: 'info', 警告: 'warn', 错误: 'error' } as Record<Level, string>)[l.level]}>{l.level}</span>
        <span className="log-message"><strong>{l.component}</strong> {l.message}</span>{expanded === l.id ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </Button>{expanded === l.id && <p className="log-detail">{l.detail}</p>}</div>)}
      {!filtered.length && <div className="empty-logs"><p>没有符合当前筛选条件的日志。</p><Button variant="ghost" onClick={() => { setQuery(''); setLevel('全部级别'); setRelated(false); }}>清除筛选</Button></div>}
    </div>
  </section>;
}
