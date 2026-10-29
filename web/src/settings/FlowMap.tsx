/**
 * [INPUT]: 当前服务、共享配置/连接状态、暂停选择、深浅主题与导航保护。
 * [OUTPUT]: 可键盘操作的连接关系图，静态 SVG + 少量 Canvas 光点。
 * [POS]: D 流光连接的轻量原创示意，不是生产遥测或自动工作流。
 * [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { LoaderCircle, Pause, Play, Plug } from 'lucide-react';
import { Button } from '../components/ui';
import { curvePath, curvePoint, flowGeometry, type Curve } from './flow-geometry';
import type { Category, ServiceId } from './model';
import type { SettingsStore } from './use-settings';

type Track = Curve & { active: boolean; testing: boolean };
export function FlowMap({ theme, store, selected, select, navigate, paused, setPaused }: {
  theme: 'dark' | 'light'; store: SettingsStore; selected: ServiceId; select: (id: ServiceId) => void;
  navigate: (category: Category) => void; paused: boolean; setPaused: (value: boolean) => void;
}) {
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const clock = useRef(0);
  const [width, setWidth] = useState(() => Math.max(280, Math.min(840, window.innerWidth - 36)));
  const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [inView, setInView] = useState(true);
  const [visible, setVisible] = useState(!document.hidden);
  const geometry = useMemo(() => flowGeometry(width), [width]);
  const ready = (id: ServiceId) => store.draft.services[id].enabled && store.connections[id].state === '就绪';
  const sourcesReady = (['yt-dlp', 'OpenCLI', 'TikHub', 'Monid', 'Treg'] as ServiceId[]).some(ready);
  const inputReady = sourcesReady || ready('Cubox');
  const tracks: Track[] = geometry.curves.map(curve => ({ ...curve,
    active: curve.service ? ready(curve.service) && (curve.service !== '幕布' || inputReady) : curve.from === 'soota' ? sourcesReady : inputReady,
    testing: !!curve.service && store.connections[curve.service].state === '测试中',
  }));
  const trackSignature = tracks.map(t => `${t.active}:${t.testing}`).join('|');
  const trackRef = useRef(tracks); trackRef.current = tracks;
  const running = !paused && !reduced && inView && visible;

  useLayoutEffect(() => {
    const element = stage.current!;
    const resize = () => { const next = element.getBoundingClientRect().width; if (next > 0) setWidth(next); };
    resize();
    const sizeObserver = new ResizeObserver(resize); sizeObserver.observe(element);
    const viewObserver = typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver(entries => setInView(entries[0]?.isIntersecting ?? true), { threshold: .05 }) : null;
    viewObserver?.observe(element);
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const motionChange = () => setReduced(media.matches);
    const visibilityChange = () => setVisible(!document.hidden);
    media.addEventListener('change', motionChange);
    document.addEventListener('visibilitychange', visibilityChange);
    window.addEventListener('resize', resize);
    return () => {
      sizeObserver.disconnect(); viewObserver?.disconnect();
      media.removeEventListener('change', motionChange);
      document.removeEventListener('visibilitychange', visibilityChange);
      window.removeEventListener('resize', resize);
    };
  }, []);

  useEffect(() => {
    const layer = canvas.current!;
    const context = layer.getContext('2d');
    if (!context) return; // SVG tracks and buttons remain fully functional.
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    layer.width = Math.round(width * ratio); layer.height = geometry.height * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    const tokens = getComputedStyle(stage.current!);
    const blue = tokens.getPropertyValue('--flow-particle').trim();
    const cyan = tokens.getPropertyValue('--flow-particle-alt').trim();
    let raf = 0, previous = 0;
    function paint(time: number) {
      context!.clearRect(0, 0, width, geometry.height);
      trackRef.current.forEach((track, index) => {
        if (!track.active) return;
        // Two small pulses per ready branch; no particles on disabled/error paths.
        for (let p = 0; p < 2; p++) {
          const t = (time / (4700 + (index % 3) * 620) + index * .137 + p * .5) % 1;
          const head = curvePoint(track, t), tail = curvePoint(track, Math.max(0, t - .055));
          const color = (index + p) % 2 ? cyan : blue;
          context!.globalAlpha = .82; context!.strokeStyle = color;
          context!.lineWidth = 1.5; context!.lineCap = 'round';
          context!.beginPath(); context!.moveTo(tail.x, tail.y); context!.lineTo(head.x, head.y); context!.stroke();
          context!.globalAlpha = .1; context!.fillStyle = color;
          context!.beginPath(); context!.arc(head.x, head.y, 7, 0, Math.PI * 2); context!.fill();
          context!.globalAlpha = 1;
          context!.beginPath(); context!.arc(head.x, head.y, 2.1, 0, Math.PI * 2); context!.fill();
        }
      });
      context!.globalAlpha = 1;
    }
    function frame(now: number) {
      if (previous) clock.current += Math.min(now - previous, 40);
      previous = now; paint(clock.current);
      raf = requestAnimationFrame(frame);
    }
    paint(clock.current);
    if (running) raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); context.clearRect(0, 0, width, geometry.height); };
  }, [width, geometry.height, trackSignature, running, theme]);

  const testing = store.connections[selected].state === '测试中';
  return <section className="flow-map" data-od-id="connection-flow" aria-labelledby="flow-title">
    <header className="flow-map-heading"><h2 id="flow-title" data-od-id="flow-title">连接流向</h2><div className="flow-map-controls">
      <Button variant="ghost" className="flow-test" disabled={testing} onClick={() => store.testConnection(selected)} aria-label="测试当前连接">{testing ? <LoaderCircle size={14} className="spin" /> : <Plug size={14} />}{testing ? '测试中' : '测试当前连接'}</Button>
      <Button variant="ghost" className="icon-button" onClick={() => setPaused(!paused)} aria-label={paused ? '继续流动' : '暂停流动'} aria-pressed={paused} title={reduced ? '系统已减少动效；此开关不影响配置操作' : paused ? '继续光点流动' : '暂停光点流动'}>{paused ? <Play size={14} /> : <Pause size={14} />}</Button>
    </div></header>
    <div className="flow-lanes" aria-hidden="true"><span>来源</span><span>采集</span><span>整理</span><span>交付</span></div>
    <div ref={stage} className="flow-stage" style={{ height: geometry.height }} data-compact={geometry.compact} data-motion={reduced ? 'reduced' : running ? 'running' : 'paused'}>
      <svg className="flow-tracks" viewBox={`0 0 ${width} ${geometry.height}`} aria-hidden="true" focusable="false">
        {tracks.map(t => <path key={t.id} d={curvePath(t)} className={`flow-track ${t.active ? 'is-ready' : ''} ${t.testing ? 'is-testing' : ''}`} data-flow-edge={t.id} data-active={t.active} data-testing={t.testing} />)}
      </svg>
      <canvas ref={canvas} className="flow-particles" aria-hidden="true" />
      {geometry.nodes.map(node => {
        const connection = node.service ? store.connections[node.service] : null;
        const enabled = node.service ? store.draft.services[node.service].enabled : true;
        const caption = connection ? `${enabled ? '' : '已关闭 · '}${connection.state}` : node.detail;
        return <Button key={node.id} variant="ghost" className={`flow-node ${node.service === selected ? 'is-selected' : ''} ${connection?.state === '待重试' ? 'has-failure' : ''} ${connection?.state === '测试中' ? 'is-testing' : ''} ${node.id === 'lorelab' || node.id === 'soota' ? 'is-core' : ''}`}
          style={{ left: node.x, top: node.y, width: node.width }}
          onClick={() => node.service ? select(node.service) : node.category && navigate(node.category)}
          aria-label={node.service ? `选择连接 ${node.service}` : `${node.label}：打开${node.category === 'capture' ? '采集与费用' : '存储与导出'}`}
          aria-pressed={node.service ? node.service === selected : undefined}
          data-od-id={`flow-node-${node.id.toLowerCase()}`}>
          <strong>{node.label}</strong><small>{caption}</small>
        </Button>;
      })}
    </div>
    <footer className="flow-map-caption"><span>模拟流转</span><span className="motion-status" role="status">{reduced ? '减少动效 · 静态' : paused ? '流动已暂停' : '示例流动'}</span></footer>
  </section>;
}
