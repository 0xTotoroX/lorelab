/**
 * [INPUT]: 共用服务、任务、诊断结果、日志与配置导航。
 * [OUTPUT]: 与前三页一致的标题列加内容列；服务/任务详情在对应行下展开。
 * [POS]: 原版三列框架下的诊断页，只调整此页信息组织。
 * [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
 */
import { Fragment, useEffect, useRef, useState } from 'react';
import { Activity, ArrowUpRight, LoaderCircle } from 'lucide-react';
import { Button } from '../components/ui';
import { FormGroup } from './ConfigSections';
import { Diagnostics, LogsPanel, TaskDetails } from './Diagnostics';
import { ConnectionBadge, TestButton } from './Services';
import { serviceDefinitions, type ServiceId } from './model';
import type { SettingsStore } from './use-settings';

export function DiagnosticWorkspace({ store, selectedService, selectService, selectedJob, selectJob, configure }: {
  store: SettingsStore; selectedService: ServiceId; selectService: (id: ServiceId) => void;
  selectedJob: string; selectJob: (id: string) => void; configure: (id: ServiceId) => void;
}) {
  const [inspection, setInspection] = useState<'task' | 'service' | null>(null);
  const job = store.jobs.find(j => j.id === selectedJob)!;
  const [context, setContext] = useState<string>(job.provider);
  const details = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  useEffect(() => { if (inspection) details.current?.focus({ preventScroll: window.matchMedia('(min-width: 761px)').matches }); }, [inspection, selectedService, selectedJob]);
  const inspect = (kind: 'task' | 'service', provider: string) => {
    trigger.current = document.activeElement as HTMLElement;
    setInspection(kind); setContext(provider);
    if (inspection === kind) details.current?.focus({ preventScroll: window.matchMedia('(min-width: 761px)').matches });
  };
  const close = () => { setInspection(null); trigger.current?.focus(); };
  const provider = inspection === 'service' ? selectedService : job.provider;
  const panel = <aside className="diagnostic-inspector" aria-label="检查详情" data-od-id="inspection-panel" ref={details} tabIndex={-1}>
    <div className="inspector-heading"><h3>{inspection === 'service' ? selectedService + ' · 连接详情' : '任务详情'}</h3></div>
    {inspection === 'task' ? <TaskDetails job={job} store={store} /> :
      <div className="service-inspection"><ConnectionBadge connection={store.connections[selectedService]} />
        <p className="connection-message" role="status">{store.connections[selectedService].message}</p>
        <dl><div><dt>参与采集 / 交付</dt><dd>{store.draft.services[selectedService].enabled ? '已启用' : '已关闭'}</dd></div>
          <div><dt>超时</dt><dd>{store.draft.services[selectedService].timeout} 秒</dd></div>
          <div><dt>示例端点</dt><dd className="endpoint-value">{store.draft.services[selectedService].endpoint}</dd></div></dl>
        {store.diagnosis.find(r => r.name === selectedService) && <p className="inspection-result">{store.diagnosis.find(r => r.name === selectedService)!.message}</p>}
        <TestButton store={store} id={selectedService} />
      </div>}
    <div className="inspector-followup"><Button variant="outline" onClick={() => configure(provider)}><ArrowUpRight size={15} />{'检查 ' + provider + ' 配置'}</Button>
      <Button variant="ghost" onClick={close}>收起详情</Button></div>
  </aside>;
  return <div className="configuration-groups diagnostic-groups" data-od-id="diagnostics-page">
    <FormGroup title="服务状态">
      <section className="service-health" aria-label="服务状态列表">
        <div className="diagnostic-group-actions"><Button variant="outline" disabled={store.diagnosing} onClick={store.diagnose}>
          {store.diagnosing ? <LoaderCircle size={14} className="spin" /> : <Activity size={14} />}{store.diagnosing ? '正在检查' : '运行组件诊断'}</Button></div>
        <table className="health-table"><thead><tr><th>服务</th><th>连接</th><th>诊断</th></tr></thead><tbody>
          {serviceDefinitions.map(d => {
            const result = store.diagnosis.find(r => r.name === d.id);
            const open = inspection === 'service' && selectedService === d.id;
            return <Fragment key={d.id}><tr className={open ? 'selected-health' : ''}>
              <td><Button variant="ghost" onClick={() => { selectService(d.id); inspect('service', d.id); }}
                aria-label={'检查服务 ' + d.id} aria-expanded={open}>
                <span><strong>{d.id}</strong><small>{store.draft.services[d.id].enabled ? '已启用' : '已关闭'}</small></span></Button></td>
              <td><ConnectionBadge connection={store.connections[d.id]} /></td>
              <td className={result && result.state !== '通过' ? 'text-warning' : 'health-result'}>{store.diagnosing ? '检查中' : result?.state || '未检查'}</td>
            </tr>{open && <tr className="diagnostic-detail-row"><td colSpan={3}>{panel}</td></tr>}</Fragment>;
          })}
        </tbody></table>
      </section>
    </FormGroup>
    <FormGroup title="最近任务"><Diagnostics store={store} selected={selectedJob} showHeading={false}
      detail={inspection === 'task' ? panel : undefined} onFilterChange={() => setInspection(null)}
      select={id => { selectJob(id); inspect('task', store.jobs.find(j => j.id === id)!.provider); }} /></FormGroup>
    <FormGroup title="诊断日志"><LogsPanel store={store} context={context} showHeading={false} /></FormGroup>
  </div>;
}
