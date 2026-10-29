/**
 * [INPUT]: 共享配置与连接状态与本地 Base UI 控件。
 * [OUTPUT]: 服务行、连接状态与参数编辑器。
 * [POS]: 连接与服务分组，不混同启用与测试结果。
 * [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
 */
import { Check, ChevronDown, ChevronRight, CircleDashed, LoaderCircle, Plug, Terminal, Video, Bookmark, Network } from 'lucide-react';
import { Button, Input, SwitchField } from '../components/ui';
import { serviceDefinitions, type Connection, type ServiceId } from './model';
import type { SettingsStore } from './use-settings';
export const serviceIcons = { 'yt-dlp': Video, OpenCLI: Terminal, TikHub: Network, Monid: Network, Treg: Network, Cubox: Bookmark, '幕布': Network };
export function ConnectionBadge({ connection }: { connection: Connection }) {
  return <span className={`connection-state state-${connection.state === '就绪' ? 'ready' : connection.state === '待重试' ? 'error' : connection.state === '测试中' ? 'busy' : 'pending'}`} title={connection.message}>{connection.state === '测试中' ? <LoaderCircle size={12} className="spin" /> : <span className="state-dot" />}{connection.state}</span>;
}
export function TestButton({ store, id, compact = false }: { store: SettingsStore; id: ServiceId; compact?: boolean }) {
  const busy = store.connections[id].state === '测试中';
  return <Button variant="ghost" className={compact ? 'test-button compact-test' : 'test-button'} aria-label={`测试连接 ${id}`} disabled={busy} onClick={() => store.testConnection(id)}>{busy ? <LoaderCircle size={14} className="spin" /> : <Plug size={14} />}{busy ? '测试中' : '测试连接'}</Button>;
}
export function ServiceEditor({ store, id }: { store: SettingsStore; id: ServiceId }) {
  const definition = serviceDefinitions.find(d => d.id === id)!;
  const s = store.draft.services[id]; const c = store.connections[id];
  return <div className="service-editor" data-od-id={`service-editor-${id.toLowerCase()}`}>
    <div className="editor-status"><ConnectionBadge connection={c} /><span className="service-toggle-caption">{s.enabled ? '已启用' : '未启用'}</span></div>
    <p className={`connection-message ${c.state === '未配置' || c.state === '待重试' ? 'message-warning' : ''}`} role="status">{c.message}</p>
    <label className="editor-field" htmlFor={`endpoint-${id}`}><span>示例端点</span><Input id={`endpoint-${id}`} value={s.endpoint} onChange={e => store.updateService(id, { endpoint: e.target.value })} aria-invalid={!!store.errors[`service.${id}.endpoint`]} /></label>
    {store.errors[`service.${id}.endpoint`] && <p className="field-error" role="alert">{store.errors[`service.${id}.endpoint`]}</p>}
    <label className="editor-field" htmlFor={`timeout-${id}`}><span>超时 <small>秒</small></span><Input id={`timeout-${id}`} type="number" min="1" value={s.timeout} onChange={e => store.updateService(id, { timeout: e.target.value })} aria-invalid={!!store.errors[`service.${id}.timeout`]} /></label>
    {store.errors[`service.${id}.timeout`] && <p className="field-error" role="alert">{store.errors[`service.${id}.timeout`]}</p>}
    <div className="editor-toggle"><div><strong>缓存获取结果</strong></div><SwitchField label={`${id} 缓存`} checked={s.cache} onChange={cache => store.updateService(id, { cache })} /></div>
    {definition.credential && <div className="credential-field"><label htmlFor={`credential-${id}`}>示例凭据</label><Input id={`credential-${id}`} readOnly value={s.credential} placeholder="尚未填入合成示例" /><p>只使用合成占位值，不填写真实密钥。</p><Button variant="outline" onClick={() => store.fillExample(id)}>{s.credential ? <Check size={14} /> : <PlusIcon />}填入示例配置</Button></div>}
    <div className="editor-actions"><TestButton store={store} id={id} /></div>
  </div>;
}
function PlusIcon() { return <CircleDashed size={14} />; }
export function Services({ store, selected, expanded, configure }: { store: SettingsStore; selected: ServiceId; expanded: boolean; configure: (id: ServiceId) => void }) {
  return <div className="service-groups clean-service-groups">
    {(['采集来源', '内容连接'] as const).map(group => <section className="service-group" key={group} data-od-id={`group-${group === '采集来源' ? 'providers' : 'integrations'}`}><div className="section-heading"><h2>{group === '采集来源' ? 'Soota 采集来源' : group}</h2></div><div className="service-rows">{serviceDefinitions.filter(d => d.group === group).map(d => {
      const s = store.draft.services[d.id]; const Icon = serviceIcons[d.id]; const open = expanded && selected === d.id;
      return <div className="service-item" key={d.id} data-od-id={`service-row-${d.id.toLowerCase()}`}><div className="service-row"><Button variant="ghost" className="service-name-button" onClick={() => configure(d.id)} aria-label={`配置 ${d.id}`} aria-expanded={open}><span className="service-glyph"><Icon size={19} /></span><span><strong>{d.id}</strong><small>{d.detail}</small></span></Button><div className="service-toggle"><SwitchField label={`启用 ${d.id}`} checked={s.enabled} onChange={enabled => store.updateService(d.id, { enabled })} /><span className="service-toggle-caption">{s.enabled ? '已启用' : '未启用'}</span></div><ConnectionBadge connection={store.connections[d.id]} /><TestButton store={store} id={d.id} /><Button className="icon-button configure-service" variant="ghost" aria-label={`${open ? '收起' : '编辑'} ${d.id} 配置`} onClick={() => configure(d.id)}>{open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</Button></div>{store.connections[d.id].tested && ['未配置', '待重试'].includes(store.connections[d.id].state) && <p className="connection-feedback" role="status">{store.connections[d.id].message} · 点击配置修正后重试</p>}{open && <div className="inline-editor"><div className="inline-editor-heading"><h3>{d.id} 连接参数</h3></div><ServiceEditor store={store} id={d.id} /></div>}</div>;
    })}</div></section>)}

  </div>;
}
