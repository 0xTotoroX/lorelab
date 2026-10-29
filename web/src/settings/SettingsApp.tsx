/**
 * [INPUT]: 共享配置、连接关系、任务与诊断。
 * [OUTPUT]: 品牌、主题与导航组成完整侧栏；右侧保留三列分组、诊断、草稿与流光。
 * [POS]: 唯一配置台界面入口；业务状态来自内存示例 store。
 * [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Activity, ArrowRight, Check, Circle, FileDiff, FolderOpen, Layers2, Plug, RotateCcw, Save, SlidersHorizontal, Sun, Moon } from 'lucide-react';
import { Button, Modal, Segments, SwitchField } from '../components/ui';
import { Capture, Storage } from './ConfigSections';
import { FlowMap } from './FlowMap';
import { DiagnosticWorkspace } from './DiagnosticWorkspace';
import { ConnectionBadge, Services } from './Services';
import { categories, serviceDefinitions, type Category, type Change, type ServiceId } from './model';
import { useSettings, type SettingsStore } from './use-settings';

const icons = { services: Plug, capture: SlidersHorizontal, storage: FolderOpen, diagnostics: Activity };
type Destination = { category: Category; service?: ServiceId };
function Changes({ changes }: { changes: Change[] }) {
  return <div className="changes-list" data-od-id="configuration-diff">{changes.map(c =>
    <div className="change-row" key={c.key}><strong>{c.label}</strong><div>
      <span className="change-before">{c.before}</span><ArrowRight size={14} aria-label="改为" />
      <span className="change-after">{c.after}</span>
    </div></div>)}</div>;
}
function SaveBar({ store, review }: { store: SettingsStore; review: () => void }) {
  return <footer className={'save-bar' + (store.changes.length ? ' has-changes' : '')} data-od-id="save-bar">
    <div className={'save-status ' + (Object.keys(store.errors).length ? 'text-error' : '')} role="status">
      {store.changes.length ? <Circle size={8} fill="currentColor" /> : <Check size={15} />}
      <div><strong>{store.saveMessage || (store.changes.length ? store.changes.length + ' 项未保存修改' : '配置已保存')}</strong></div>
    </div>
    <div className="save-actions">
      <Button variant="ghost" disabled={!store.changes.length} onClick={store.undo}><RotateCcw size={15} />撤销</Button>
      <Button variant="outline" disabled={!store.changes.length} onClick={review}><FileDiff size={15} />查看修改</Button>
      <Button variant="primary" disabled={!store.changes.length} onClick={store.save}><Save size={15} />保存配置</Button>
    </div>
  </footer>;
}

export function SettingsApp() {
  const store = useSettings();
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [category, setCategory] = useState<Category>(() => {
    const page = new URLSearchParams(window.location.search).get('page');
    return categories.some(c => c.id === page) ? page as Category : 'services';
  });
  const [serviceView, setServiceView] = useState(() => new URLSearchParams(window.location.search).get('view') === 'overview' ? 'overview' : 'settings');
  const [selected, setSelected] = useState<ServiceId>('yt-dlp');
  const [expanded, setExpanded] = useState(() => new URLSearchParams(window.location.search).get('view') !== 'overview');
  const [flowPaused, setFlowPaused] = useState(false);
  const [selectedJob, setSelectedJob] = useState('TASK-102');
  const [modal, setModal] = useState<'changes' | 'unsaved' | null>(null);
  const [pending, setPending] = useState<Destination | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const focusEditor = useRef(false);
  const content = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    document.documentElement.dataset.design = 'flow';
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#1c1c1c' : '#ffffff');
  }, [theme]);
  useEffect(() => {
    if (focusEditor.current && serviceView === 'settings' && category === 'services') {
      focusEditor.current = false;
      content.current?.querySelector<HTMLInputElement>('.inline-editor input:not([readonly]), .service-workspace-editor input:not([readonly])')?.focus();
    }
  }, [serviceView, category, selected, expanded]);
  const current = categories.find(c => c.id === category)!;
  const selectedDefinition = serviceDefinitions.find(d => d.id === selected)!;
  const open = (name: typeof modal) => {
    returnFocus.current = document.activeElement as HTMLElement;
    // 先移出即将被弹层隐藏的背景；关闭后仍归还到已记录的触发器。
    returnFocus.current?.blur();
    setModal(name);
  };
  const close = () => setModal(null);
  const editService = (id: ServiceId) => {
    focusEditor.current = true; setSelected(id); setExpanded(true); setServiceView('settings');
  };
  const arrive = (next: Destination) => {
    setCategory(next.category);
    if (next.service) editService(next.service);
    content.current?.scrollTo({ top: 0 });
  };
  const navigate = (next: Category, service?: ServiceId) => {
    if (next === category) { if (service) editService(service); return; }
    const destination = { category: next, service };
    if (store.changes.length) { setPending(destination); open('unsaved'); } else arrive(destination);
  };
  const finishNavigation = () => { if (pending) arrive(pending); setPending(null); close(); };
  const configure = (id: ServiceId) => {
    setExpanded(selected === id ? !expanded : true); setSelected(id);
  };
  return <div className={'settings-preview style-unified layout-original page-' + category} data-od-id="settings-preview">
    <div className="configuration-app">
      <aside className="workbench-sidebar" aria-label="LoreLab 工作区">
        <header className="workbench-header">
          <div className="workbench-brand"><Layers2 size={20} /><strong>LoreLab</strong></div>
          <Button variant="ghost" className="theme-toggle" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            aria-label={theme === 'dark' ? '切换为浅色主题' : '切换为深色主题'}
            title={theme === 'dark' ? '切换为浅色主题' : '切换为深色主题'}>
            {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
          </Button>
        </header>
        <nav className="category-navigation" aria-label="配置分类">{categories.map(c => {
          const Icon = icons[c.id];
          return <Button key={c.id} variant="ghost" className={'category-button ' + (category === c.id ? 'current-category' : '')}
            aria-current={category === c.id ? 'page' : undefined} onClick={() => navigate(c.id)}
            data-od-focus-fallback={category === c.id ? '' : undefined}><Icon size={18} /><span>{c.label}</span></Button>;
        })}</nav>
        <div className="sidebar-foot"><span className="preview-label" title="所有操作使用示例数据，刷新后还原">交互预览 · 示例配置</span></div>
      </aside>
      <div className="app-content">
        <main className="settings-scroll" ref={content} data-od-id="configuration-content">
          <div className="content-width">
            <header className="page-heading"><h1>{current.label}</h1>
              {category === 'services' && <Segments label="连接视图" value={serviceView} onChange={setServiceView}
                items={[{ value: 'overview', label: '连接概览' }, { value: 'settings', label: '服务配置' }]} />}
            </header>
            {category === 'services' && <>
              {serviceView === 'overview' ? <div className="connection-overview">
                <FlowMap theme={theme} store={store} selected={selected} select={setSelected} navigate={navigate} paused={flowPaused} setPaused={setFlowPaused} />
                <section className="selected-connection" aria-label="所选连接">
                  <div className="connection-identity"><h2>{selected}</h2><p>{selectedDefinition.detail}</p></div>
                  <div className="connection-summary"><ConnectionBadge connection={store.connections[selected]} />
                    {store.connections[selected].state !== '就绪' && <p role="status">{store.connections[selected].message}</p>}</div>
                  <div className="connection-actions"><label className="enable-label"><SwitchField label={'启用 ' + selected} checked={store.draft.services[selected].enabled}
                    onChange={enabled => store.updateService(selected, { enabled })} /><span>{store.draft.services[selected].enabled ? '已启用' : '未启用'}</span></label>
                    <Button variant="outline" onClick={() => editService(selected)}>配置参数<ArrowRight size={16} /></Button></div>
                </section>
              </div> : <Services store={store} selected={selected} expanded={expanded} configure={configure} />}
            </>}
            {category === 'capture' && <Capture store={store} />}
            {category === 'storage' && <Storage store={store} />}
            {category === 'diagnostics' && <DiagnosticWorkspace store={store} selectedService={selected} selectService={setSelected}
              selectedJob={selectedJob} selectJob={setSelectedJob} configure={id => navigate('services', id)} />}
          </div>
        </main>
        <SaveBar store={store} review={() => open('changes')} />
      </div>
    </div>
    <Modal open={modal === 'changes'} close={close} title="查看修改" description="对比上次保存与当前草稿。" returnFocus={returnFocus.current}>
      <Changes changes={store.changes} />
      {Object.keys(store.errors).length > 0 && <p className="field-error" role="alert">{Object.values(store.errors)[0]}</p>}
      <div className="dialog-actions"><Button variant="ghost" onClick={close}>继续编辑</Button>
        <Button variant="primary" disabled={!store.changes.length} onClick={() => { if (store.save()) close(); }}>保存配置</Button></div>
    </Modal>
    <Modal open={modal === 'unsaved'} close={() => { setPending(null); close(); }} title="还有未保存的修改"
      description={'切换到「' + (categories.find(c => c.id === pending?.category)?.label || '') + '」前，请处理当前 ' + store.changes.length + ' 项修改。'} returnFocus={returnFocus.current}>
      <p className="unsaved-copy">可以继续编辑、放弃修改，或保存后切换。</p>
      {Object.keys(store.errors).length > 0 && <p className="field-error" role="alert">{Object.values(store.errors)[0]}</p>}
      <div className="dialog-actions"><Button variant="ghost" onClick={() => { setPending(null); close(); }}>继续编辑</Button>
        <Button variant="outline" onClick={() => { store.undo(); finishNavigation(); }}>放弃修改</Button>
        <Button variant="primary" onClick={() => { if (store.save()) finishNavigation(); }}>保存后切换</Button></div>
    </Modal>
  </div>;
}
