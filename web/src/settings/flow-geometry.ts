/**
 * [INPUT]: 画布实际宽度。
 * [OUTPUT]: SVG、Canvas 和按钮共用的节点与三次贝塞尔坐标。
 * [POS]: 独立原创的连接关系布局；无第三方素材或绘图库。
 * [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
 */
import type { Category, ServiceId } from './model';
export type Point = { x: number; y: number };
export type FlowNode = Point & {
  id: string; label: string; detail: string; width: number;
  service?: ServiceId; category?: Category;
};
export type Curve = { id: string; from: string; to: string; points: [Point, Point, Point, Point]; service?: ServiceId; straight?: boolean };
export type FlowGeometry = { width: number; height: number; compact: boolean; nodes: FlowNode[]; curves: Curve[] };
const providers: ServiceId[] = ['yt-dlp', 'OpenCLI', 'TikHub', 'Monid', 'Treg'];
export function flowGeometry(width: number): FlowGeometry {
  const compact = width < 640;
  const nodes: FlowNode[] = [];
  const add = (id: string, label: string, detail: string, x: number, y: number, nodeWidth: number, service?: ServiceId, category?: Category) => {
    nodes.push({ id, label, detail, x, y, width: nodeWidth, service, category });
  };
  if (compact) {
    providers.forEach((id, i) => add(id, id, '', width * .18, 42 + i * 64, width * .31, id));
    add('soota', 'Soota', '采集原文', width * .72, 170, width * .34, undefined, 'capture');
    add('lorelab', 'LoreLab', '按需整理', width * .72, 390, width * .34, undefined, 'storage');
    add('Cubox', 'Cubox', '内容连接', width * .18, 390, width * .31, 'Cubox');
    add('content', '内容目录', '输出', width * .17, 506, width * .30, undefined, 'storage');
    add('obsidian', 'Obsidian', '输出', width * .50, 506, width * .30, undefined, 'storage');
    add('mubu', '幕布', '交付', width * .83, 506, width * .30, '幕布');
  } else {
    const nodeWidth = Math.min(144, width * .18);
    providers.forEach((id, i) => add(id, id, '', width * .1, 42 + i * 70, nodeWidth, id));
    add('soota', 'Soota', '采集原文', width * .36, 182, nodeWidth, undefined, 'capture');
    add('lorelab', 'LoreLab', '按需整理', width * .64, 182, nodeWidth, undefined, 'storage');
    add('Cubox', 'Cubox', '内容连接', width * .36, 322, nodeWidth, 'Cubox');
    add('content', '内容目录', '输出', width * .9, 88, nodeWidth, undefined, 'storage');
    add('obsidian', 'Obsidian', '输出', width * .9, 182, nodeWidth, undefined, 'storage');
    add('mubu', '幕布', '交付', width * .9, 276, nodeWidth, '幕布');
  }
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const curves: Curve[] = [];
  function link(from: string, to: string, service?: ServiceId) {
    const a = byId[from], b = byId[to];
    let points: Curve['points'];
    if (compact && from === 'soota') {
      const start = { x: a.x, y: a.y + 28 }, end = { x: b.x, y: b.y - 28 };
      points = [start, { x: start.x, y: start.y + (end.y-start.y)/3 }, { x: end.x, y: start.y+2*(end.y-start.y)/3 }, end];
    } else if (compact && from === 'lorelab') {
      const start = { x: a.x, y: a.y + 28 }, end = { x: b.x, y: b.y - 28 };
      const bend = (start.y + end.y) / 2;
      points = [start, { x: start.x, y: bend }, { x: end.x, y: bend }, end];
    } else if (!compact && from === 'Cubox') {
      const start = { x: a.x + a.width/2, y: a.y }, end = { x: b.x, y: b.y + 28 };
      points = [start, { x: end.x, y: start.y }, { x: end.x, y: end.y+48 }, end];
    } else {
      const start = { x: a.x + a.width / 2, y: a.y }, end = { x: b.x - b.width / 2, y: b.y };
      const bend = (start.x + end.x) / 2;
      points = [start, { x: bend, y: start.y }, { x: bend, y: end.y }, end];
    }
    curves.push({ id: `${from}-${to}`, from, to, points, service, straight: from === 'soota' });
  }
  providers.forEach(id => link(id, 'soota', id));
  link('soota', 'lorelab');
  link('Cubox', 'lorelab', 'Cubox');
  link('lorelab', 'content'); link('lorelab', 'obsidian'); link('lorelab', 'mubu', '幕布');
  return { width, height: compact ? 548 : 366, compact, nodes, curves };
}
export function curvePath(curve: Curve) {
  const [a,b,c,d] = curve.points;
  if (curve.straight) return `M ${a.x} ${a.y} L ${d.x} ${d.y}`;
  return `M ${a.x} ${a.y} C ${b.x} ${b.y}, ${c.x} ${c.y}, ${d.x} ${d.y}`;
}
export function curvePoint(curve: Curve, t: number): Point {
  const [a,b,c,d] = curve.points, u = 1 - t;
  return { x: u*u*u*a.x + 3*u*u*t*b.x + 3*u*t*t*c.x + t*t*t*d.x,
    y: u*u*u*a.y + 3*u*u*t*b.y + 3*u*t*t*c.y + t*t*t*d.y };
}
