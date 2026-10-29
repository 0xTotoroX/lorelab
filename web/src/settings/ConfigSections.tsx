/**
 * [INPUT]: 共享配置、校验错误与更新方法。
 * [OUTPUT]: 采集费用、存储导出表单。
 * [POS]: 同一份字段随布局切换重排，不产生独立草稿。
 * [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
 */
import { useId, useState, type ReactNode } from 'react';
import { ArrowDown, ArrowUp, FolderCheck, RotateCcw } from 'lucide-react';
import { Button, Input, Segments, SelectField, SwitchField } from '../components/ui';
import { defaultPriority, validPath, type Config } from './model';
import type { SettingsStore } from './use-settings';
export function FormGroup({ title, note, children, className = '' }: { title: string; note?: string; children: ReactNode; className?: string }) { const id = useId().replace(/:/g, ''); return <section data-od-id={`settings-group-${id}`} className={`form-group ${className}`}><div className="section-heading"><h2 data-od-id={`group-heading-${id}`}>{title}</h2>{note && <span>{note}</span>}</div><div className="group-content">{children}</div></section>; }
export function FormRow({ label, description, children, error }: { label: string; description?: string; children: ReactNode; error?: string }) { const id = useId().replace(/:/g, ''); return <div data-od-id={`setting-row-${id}`} className={`form-row ${error ? 'has-error' : ''}`}><div className="form-label"><strong>{label}</strong>{description && <p>{description}</p>}</div><div className="form-control">{children}{error && <p role="alert" className="field-error">{error}</p>}</div></div>; }
export function Capture({ store }: { store: SettingsStore }) {
  const c = store.draft.capture;
  const update = (patch: Partial<Config['capture']>) => store.update(next => Object.assign(next.capture, patch));
  const reorder = (index: number, change: number) => { const priority = [...c.priority]; [priority[index], priority[index + change]] = [priority[index + change], priority[index]]; update({ priority }); };
  return <div className="configuration-groups" data-od-id="capture-config">
    <FormGroup title="获取方式与费用" note="示例预算，非实际扣费">
      <FormRow label="默认获取内容"><span className="fixed-value">仅原文</span></FormRow>
      <FormRow label="允许付费"><SwitchField label="允许付费" checked={c.paid} onChange={paid => update({ paid })} /></FormRow>
      <FormRow label="单任务预算" description="示例约束：0–10 USD" error={store.errors['capture.budget']}><div className="budget-input"><Input aria-label="单任务预算 USD" type="number" min="0" max="10" step="0.1" disabled={!c.paid} value={c.budget} onChange={e => update({ budget: e.target.value })} aria-invalid={!!store.errors['capture.budget']} /><span>USD</span></div>{!c.paid && <p className="control-help">免费模式下无需预算，开启允许付费后可编辑。</p>}</FormRow>
      <FormRow label="费用确认方式"><SelectField label="费用确认方式" value={c.payment === 'ask' ? '逐次确认（ask）' : '预算内自动（auto）'} options={['逐次确认（ask）', '预算内自动（auto）']} onChange={v => update({ payment: v.includes('ask') ? 'ask' : 'auto' })} /></FormRow>
    </FormGroup>
    <FormGroup title="来源优先级" note="关闭的来源不会参与任务选择" className="priority-group">
      <Segments label="来源优先级模式" value={c.routing} onChange={routing => update({ routing: routing as 'cost' | 'manual' })} items={[{ value: 'cost', label: '费用优先（cost）' }, { value: 'manual', label: '手动顺序（manual）' }]} />
      {c.routing === 'cost' ? <div className="routing-explanation"><p>免费来源优先；付费来源遵循预算与确认方式。</p></div> : <><ol className="priority-list">{c.priority.map((id, i) => <li key={id} data-od-id={`priority-${id.toLowerCase()}`}><span className="order-number">{i + 1}</span><strong>{id}</strong><span className="priority-enabled">{store.draft.services[id].enabled ? '已启用' : '已关闭'}</span><div className="order-buttons"><Button variant="ghost" className="icon-button" aria-label={`上移 ${id}`} title={i === 0 ? '已经是第一项' : '上移一位'} disabled={i === 0} onClick={() => reorder(i, -1)}><ArrowUp size={15} /></Button><Button variant="ghost" className="icon-button" aria-label={`下移 ${id}`} title={i === c.priority.length - 1 ? '已经是最后一项' : '下移一位'} disabled={i === c.priority.length - 1} onClick={() => reorder(i, 1)}><ArrowDown size={15} /></Button></div></li>)}</ol><Button variant="ghost" onClick={() => update({ priority: [...defaultPriority] })}><RotateCcw size={14} />恢复默认顺序</Button></>}
    </FormGroup>
    <FormGroup title="音频与本地转写"><FormRow label="默认音频来源"><span className="fixed-value">yt-dlp</span></FormRow><FormRow label="转写引擎"><SelectField label="转写引擎" value={c.engine} options={['auto', 'Whisper']} onChange={engine => update({ engine: engine as 'auto' | 'Whisper' })} /></FormRow><FormRow label="模型与设备"><span className="fixed-value">base · CPU</span></FormRow></FormGroup>
    <FormGroup title="本次任务参数" note="仅用于此次任务"><FormRow label="并发任务数" description="示例范围：1–5" error={store.errors['task.concurrency']}><Input aria-label="本次任务并发" className="short-input" type="number" min="1" max="5" value={store.draft.task.concurrency} onChange={e => store.update(next => { next.task.concurrency = e.target.value; })} aria-invalid={!!store.errors['task.concurrency']} /></FormRow></FormGroup>
  </div>;
}
export function Storage({ store }: { store: SettingsStore }) {
  const [checks, setChecks] = useState<Record<string, string>>({});
  const s = store.draft.storage;
  const update = (key: keyof Config['storage'], value: string | boolean) => { store.update(next => Object.assign(next.storage, { [key]: value })); setChecks(old => ({ ...old, [key]: '' })); };
  const pathRow = (key: 'output' | 'cache' | 'vault', label: string) => <FormRow label={label} error={store.errors[`storage.${key}`]}><div className="path-control"><Input aria-label={label} value={s[key]} onChange={e => update(key, e.target.value)} aria-invalid={!!store.errors[`storage.${key}`]} /><Button className="icon-button" variant="ghost" aria-label={`检查目录 ${label}`} title="模拟检查目录" onClick={() => { const ok = validPath(s[key]); const message = ok ? '模拟目录检查通过，未访问文件系统。' : '路径无效：需以 / 开头且不包含 .. 或特殊字符。'; setChecks(old => ({ ...old, [key]: message })); store.log(ok ? '信息' : '错误', '存储', `${label}：${ok ? '示例检查通过' : '路径校验失败'}`, message); }}><FolderCheck size={17} /></Button></div>{checks[key] && <p className={`control-help ${checks[key].startsWith('路径无效') ? 'field-error' : ''}`} role="status">{checks[key]}</p>}</FormRow>;
  return <div className="configuration-groups" data-od-id="storage-config"><FormGroup title="内容与缓存" note="示例路径">{pathRow('output', '内容输出目录')}{pathRow('cache', '缓存目录')}</FormGroup><FormGroup title="Obsidian 导出">{pathRow('vault', 'Obsidian 知识库')}<FormRow label="知识库子目录" error={store.errors['storage.subdir']}><Input aria-label="知识库子目录" value={s.subdir} onChange={e => update('subdir', e.target.value)} /></FormRow></FormGroup><FormGroup title="幕布目标"><FormRow label="目标文档" error={store.errors['storage.mubuDoc']}><Input aria-label="幕布目标文档" value={s.mubuDoc} onChange={e => update('mubuDoc', e.target.value)} /></FormRow><FormRow label="父级节点"><Input aria-label="幕布父级节点" value={s.mubuParent} onChange={e => update('mubuParent', e.target.value)} /></FormRow></FormGroup><FormGroup title="文件保护"><FormRow label="保留源文件"><SwitchField label="保留源文件" checked={s.keepSource} onChange={v => update('keepSource', v)} /></FormRow><FormRow label="同名内容冲突"><SelectField label="同名内容冲突" value={s.conflict === 'stop' ? '停止并提示' : '另存新文件'} options={['停止并提示', '另存新文件']} onChange={v => update('conflict', v === '停止并提示' ? 'stop' : 'rename')} /></FormRow></FormGroup></div>;
}
