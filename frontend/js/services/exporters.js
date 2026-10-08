/** 导出：海报（PNG）· 打印（PDF）· 日历（ICS）· Markdown · 文字 */
import { h } from "../core/dom.js";
import { state } from "../core/state.js";
import { downloadBlob } from "../core/dom.js";
import { DAY_HEX, TYPE_HEX } from "../core/config.js";
import { typeLabel } from "../core/icons.js";
import { stopName, stopLocation, stopDuration, hasCoords, toMin, fromMin, dayDate, fmtDate, buildIcs, toShareText, estimateCost, dayStats, fmtDuration, isoDate } from "./planner.js";

const SERIF = `"Noto Serif SC","Songti SC","STSong",serif`;
const SANS = `"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif`;
const MONO = `"DM Mono",ui-monospace,Menlo,monospace`;
const INK = "#1e1915";
const PAPER = "#f4eee1";
const SEAL = "#d6402a";

const ctxInfo = () => ({
  city: state.trip.city || "上海",
  startDate: state.trip.startDate || "",
  budget: state.trip.budget || 0,
  persona: state.persona,
});

export const fileBase = () => `一拍迹合-${ctxInfo().city}${state.itinerary.days.length}日`;

// -------------------------------------------------------------- 海报 ----
const SVG = "http://www.w3.org/2000/svg";
function routeSvg(itin, w, hgt) {
  const pts = [];
  itin.days.forEach((d, di) => d.items.forEach((s, si) => hasCoords(stopLocation(s)) && pts.push({ ...stopLocation(s), di, si })));
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("width", w);
  svg.setAttribute("height", hgt);
  svg.setAttribute("viewBox", `0 0 ${w} ${hgt}`);
  const el = (tag, attrs) => Object.entries(attrs).reduce((n, [k, v]) => (n.setAttribute(k, v), n), document.createElementNS(SVG, tag));
  svg.append(el("rect", { width: w, height: hgt, fill: "#fbf7ee" }));
  for (let x = 0; x < w; x += 30) svg.append(el("line", { x1: x, y1: 0, x2: x, y2: hgt, stroke: "#e7decc", "stroke-width": 1 }));
  for (let y = 0; y < hgt; y += 30) svg.append(el("line", { x1: 0, y1: y, x2: w, y2: y, stroke: "#e7decc", "stroke-width": 1 }));
  if (!pts.length) return svg;
  const lats = pts.map((p) => Number(p.lat));
  const lngs = pts.map((p) => Number(p.lng));
  const [minLat, maxLat, minLng, maxLng] = [Math.min(...lats), Math.max(...lats), Math.min(...lngs), Math.max(...lngs)];
  const kx = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
  const sx = Math.max((maxLng - minLng) * kx, 0.004);
  const sy = Math.max(maxLat - minLat, 0.004);
  const pad = 46;
  const sc = Math.min((w - pad * 2) / sx, (hgt - pad * 2) / sy);
  const ox = (w - sx * sc) / 2;
  const oy = (hgt - sy * sc) / 2;
  const P = (p) => [ox + (p.lng - minLng) * kx * sc, oy + (maxLat - p.lat) * sc];
  itin.days.forEach((_, di) => {
    const line = pts.filter((p) => p.di === di).map(P);
    if (line.length > 1) svg.append(el("polyline", { points: line.map((q) => q.join(",")).join(" "), fill: "none", stroke: DAY_HEX[di % 8], "stroke-width": 3.5, "stroke-dasharray": "2 8", "stroke-linecap": "round" }));
  });
  pts.forEach((p) => {
    const [x, y] = P(p);
    svg.append(el("circle", { cx: x, cy: y, r: 12, fill: DAY_HEX[p.di % 8], stroke: "#fff", "stroke-width": 3 }));
    const t = el("text", { x, y: y + 4, "text-anchor": "middle", fill: "#fff", "font-size": 11, "font-weight": 700, "font-family": MONO });
    t.textContent = p.si + 1;
    svg.append(t);
  });
  return svg;
}

/** 750px 宽的分享海报。仅用内联样式与十六进制颜色，保证 html2canvas 渲染一致。 */
export function buildPoster() {
  const itin = state.itinerary;
  const { city, startDate, budget, persona } = ctxInfo();
  const cost = estimateCost(itin, { budget });
  const stops = itin.days.reduce((n, d) => n + d.items.length, 0);
  const first = dayDate(startDate, 0);
  const s = (style) => ({ style });

  const chip = (label, value) => h("div", s(`display:flex;flex-direction:column;gap:2px;padding:0 20px;border-left:1px solid #d9cdb7`), h("span", s(`font:500 11px ${MONO};letter-spacing:.14em;color:#8a7f71;text-transform:uppercase`), label), h("span", s(`font:900 22px ${SERIF};color:${INK}`), value));

  const dayBlocks = itin.days.map((day, di) => {
    const color = DAY_HEX[di % 8];
    const dt = dayDate(startDate, di);
    const st = dayStats(day);
    return h("div", s(`margin-bottom:22px`),
      h("div", s(`display:flex;align-items:center;gap:12px;margin-bottom:10px`),
        h("div", s(`width:38px;height:38px;border-radius:11px;background:${color};color:#fff;font:500 14px/38px ${MONO};text-align:center;box-shadow:0 3px 0 rgba(0,0,0,.25)`), `D${di + 1}`),
        h("div", null, h("div", s(`font:900 19px ${SERIF};color:${INK}`), day.title || `Day ${di + 1}`), h("div", s(`font:400 12px ${SANS};color:#8a7f71`), [dt ? fmtDate(dt) : "", `${st.count} 个点`, st.travelMin ? `通勤 ${fmtDuration(st.travelMin)}` : ""].filter(Boolean).join(" · ")))),
      h("div", s(`margin-left:19px;padding-left:22px;border-left:2px dashed #d9cdb7`),
        day.items.map((it, si) => {
          const loc = stopLocation(it);
          const end = toMin(it.time) != null ? fromMin(toMin(it.time) + stopDuration(it)) : "";
          return h("div", s(`position:relative;padding:8px 0`),
            h("i", s(`position:absolute;left:-30px;top:14px;width:12px;height:12px;border-radius:50%;background:${color};border:3px solid ${PAPER}`)),
            h("div", s(`display:flex;align-items:baseline;gap:10px`),
              h("span", s(`font:500 13px ${MONO};color:${color};min-width:44px`), it.time || "--:--"),
              h("span", s(`font:700 16px ${SANS};color:${INK}`), stopName(it)),
              loc.type && h("span", s(`font:400 11px ${SANS};padding:1px 8px;border-radius:9px;background:${TYPE_HEX[loc.type] || "#8a7f71"}22;color:${TYPE_HEX[loc.type] || "#8a7f71"}`), typeLabel(loc.type)),
              end && h("span", s(`margin-left:auto;font:400 11px ${MONO};color:#b3a897`), `→ ${end}`)),
            it.notes && h("div", s(`margin:3px 0 0 54px;font:400 12px/1.5 ${SANS};color:#6b6155`), it.notes.length > 46 ? it.notes.slice(0, 46) + "…" : it.notes));
        })));
  });

  return h(
    "div",
    s(`width:750px;background:${PAPER};color:${INK};font-family:${SANS};position:relative;overflow:hidden`),
    h("div", s(`padding:44px 48px 28px`),
      h("div", s(`display:flex;justify-content:space-between;align-items:center;margin-bottom:26px`),
        h("div", s(`display:flex;align-items:center;gap:10px;font:900 20px ${SERIF}`), h("span", s(`display:inline-block;width:28px;height:28px;border-radius:50%;background:${SEAL}`)), "一拍迹合"),
        h("span", s(`font:500 11px ${MONO};letter-spacing:.2em;color:#8a7f71`), "TRIP JOURNAL")),
      h("div", s(`display:flex;justify-content:space-between;align-items:flex-end;gap:20px`),
        h("div", null,
          h("div", s(`font:500 12px ${MONO};letter-spacing:.16em;color:${SEAL};margin-bottom:8px`), first ? `${first.getFullYear()}.${String(first.getMonth() + 1).padStart(2, "0")}.${String(first.getDate()).padStart(2, "0")} 出发` : "YOUR NEXT TRIP"),
          h("div", s(`font:900 60px/1.05 ${SERIF};letter-spacing:-.02em`), `${city}`, h("br"), `${itin.days.length} 日漫游`),
          itin.summary && h("div", s(`margin-top:12px;font:400 14px/1.6 ${SANS};color:#5a5046;max-width:440px`), itin.summary)),
        persona?.mbti && h("div", s(`flex:none;width:118px;height:118px;border-radius:50%;border:4px double ${SEAL};color:${SEAL};display:flex;flex-direction:column;align-items:center;justify-content:center;transform:rotate(-8deg)`), h("span", s(`font:500 9px ${MONO};letter-spacing:.2em`), "TRAVEL TYPE"), h("b", s(`font:500 26px ${MONO};letter-spacing:.12em`), persona.mbti), h("span", s(`font:700 12px ${SANS}`), persona.personality?.name || "")))),
    h("div", s(`display:flex;margin:0 48px;padding:16px 0;border-top:2px solid ${INK};border-bottom:1px solid #d9cdb7`),
      h("div", s(`padding-right:20px;display:flex;flex-direction:column;gap:2px`), h("span", s(`font:500 11px ${MONO};letter-spacing:.14em;color:#8a7f71`), "DAYS"), h("span", s(`font:900 22px ${SERIF}`), `${itin.days.length} 天`)),
      chip("SPOTS", `${stops} 个地点`),
      chip("BUDGET", budget ? `¥${budget}/人` : "—"),
      chip("EST.", `¥${cost.per_person}/人`)),
    h("div", s(`margin:24px 48px 8px;border-radius:16px;overflow:hidden;border:1.5px solid ${INK}`), routeSvg(itin, 654, 250)),
    h("div", s(`padding:20px 48px 8px`), dayBlocks),
    itin.tips?.length
      ? h("div", s(`margin:8px 48px 24px;padding:16px 20px;background:#f5e3bb;border-radius:14px`), h("div", s(`font:900 15px ${SERIF};margin-bottom:6px`), "旅行小贴士"), h("ul", s(`margin:0;padding-left:18px;font:400 12.5px/1.75 ${SANS};color:#5a5046`), itin.tips.slice(0, 5).map((t) => h("li", null, t))))
      : null,
    h("div", s(`display:flex;justify-content:space-between;padding:16px 48px 26px;border-top:1px dashed #d9cdb7;font:400 11px ${MONO};color:#8a7f71`), h("span", null, "由 一拍迹合 AI 生成"), h("span", null, isoDate(new Date())))
  );
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (window.html2canvas) return resolve();
    const s = h("script", { src });
    s.onload = resolve;
    s.onerror = () => reject(new Error("截图组件加载失败"));
    document.head.append(s);
  });
}

export async function downloadPoster() {
  await loadScript("vendor/html2canvas.min.js"); // 本地内置，离线也能生成海报
  if (document.fonts?.ready) await document.fonts.ready;
  const wrap = h("div", { style: "position:fixed;left:-9999px;top:0;pointer-events:none" }, buildPoster());
  document.body.append(wrap);
  try {
    const canvas = await window.html2canvas(wrap.firstElementChild, { scale: 2, backgroundColor: PAPER, useCORS: true, logging: false });
    await new Promise((res) => canvas.toBlob((b) => (downloadBlob(b, `${fileBase()}.png`), res()), "image/png"));
  } finally {
    wrap.remove();
  }
}

// ---------------------------------------------------------------- PDF ----
/** 用隐藏 iframe 打印：无弹窗拦截，样式与主页面隔离 */
export function printPdf() {
  const itin = state.itinerary;
  const { city, startDate } = ctxInfo();
  const iframe = h("iframe", { style: "position:fixed;right:0;bottom:0;width:0;height:0;border:0", "aria-hidden": "true" });
  document.body.append(iframe);
  const doc = iframe.contentDocument;
  doc.open();
  doc.write(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${fileBase()}</title><style>
    @page{margin:16mm}
    body{font-family:${SANS};color:${INK};line-height:1.6;margin:0}
    h1{font:900 30px ${SERIF};margin:0 0 4px;border-bottom:3px solid ${SEAL};padding-bottom:8px}
    .sum{color:#5a5046;margin:8px 0 18px}
    .day{break-inside:avoid;margin-bottom:18px}
    .day h2{font:900 18px ${SERIF};color:${SEAL};margin:0 0 6px}
    .row{display:flex;gap:12px;padding:6px 0;border-bottom:1px solid #eee;font-size:14px}
    .t{font-family:${MONO};color:#8a7f71;min-width:48px}
    .n{font-weight:700}.note{color:#6b6155;font-size:12px}
    .tips{background:#faf3e0;padding:12px 16px;border-radius:8px;margin-top:16px;font-size:13px}
    .foot{text-align:center;color:#aaa;font-size:11px;margin-top:24px}
  </style></head><body></body></html>`);
  doc.close();

  const node = h("div", null,
    h("h1", null, `${city}${itin.days.length}日行程`),
    itin.summary && h("p", { class: "sum" }, itin.summary),
    itin.days.map((d, di) => {
      const dt = dayDate(startDate, di);
      return h("section", { class: "day" }, h("h2", null, `${d.title || `Day ${di + 1}`}${dt ? " · " + fmtDate(dt) : ""}`),
        d.items.map((it) => h("div", { class: "row" }, h("span", { class: "t" }, it.time || ""), h("div", null, h("div", { class: "n" }, stopName(it)), it.notes && h("div", { class: "note" }, it.notes)))));
    }),
    itin.tips?.length && h("div", { class: "tips" }, h("b", null, "旅行小贴士"), h("ul", null, itin.tips.map((t) => h("li", null, t)))),
    h("div", { class: "foot" }, `由 一拍迹合 AI 生成 · ${isoDate(new Date())}`));
  doc.body.append(doc.importNode(node, true));

  setTimeout(() => {
    iframe.contentWindow.focus();
    iframe.contentWindow.print();
    setTimeout(() => iframe.remove(), 2000);
  }, 300);
}

// ------------------------------------------------------ ICS / 文本 / MD ----
export function downloadIcs(startDate) {
  const ics = buildIcs(state.itinerary, { startDate, city: ctxInfo().city, uidSeed: state.tripId || "draft" });
  downloadBlob(new Blob([ics], { type: "text/calendar;charset=utf-8" }), `${fileBase()}.ics`);
}

export const shareText = () => toShareText(state.itinerary, { ...ctxInfo(), cost: estimateCost(state.itinerary, { budget: state.trip.budget }) });

export function downloadMarkdown() {
  const itin = state.itinerary;
  const { city, startDate } = ctxInfo();
  let md = `# ${city}${itin.days.length}日行程攻略\n\n${itin.summary || ""}\n\n`;
  itin.days.forEach((d, di) => {
    const dt = dayDate(startDate, di);
    md += `## ${d.title || `Day ${di + 1}`}${dt ? " · " + fmtDate(dt) : ""}\n\n`;
    d.items.forEach((it) => {
      const loc = stopLocation(it);
      md += `### ${it.time || ""} ${stopName(it)}\n`;
      if (it.notes) md += `> 💡 ${it.notes}\n\n`;
      if (loc.description) md += `${loc.description}\n\n`;
      if (loc.address) md += `- 地址：${loc.address}\n`;
      if (loc.best_time) md += `- 建议时段：${loc.best_time}\n`;
      md += "\n";
    });
  });
  if (itin.tips?.length) md += `---\n\n## 旅行小贴士\n\n${itin.tips.map((t) => `- ${t}`).join("\n")}\n\n`;
  md += `---\n*由 一拍迹合 AI 生成 · ${isoDate(new Date())}*\n`;
  downloadBlob(new Blob([md], { type: "text/markdown;charset=utf-8" }), `${fileBase()}.md`);
}
