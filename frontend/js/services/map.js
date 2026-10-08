/**
 * 地图抽象层：优先高德 JS API；无法加载（无网络 / Key 失效 / 被墙）时
 * 自动降级为「手账示意图」SVG，保证核心流程始终可用。
 *
 *   const view = await createMapView(el, { onMarkerClick, onMarkerHover })
 *   view.setMarkers([{ id, lng, lat, label, color, title, dim }])
 *   view.setRoutes([{ id, from, to, color }], "transfer")   // Promise，可被后续调用取消
 *   view.focus(id) / view.fit(ids?) / view.destroy()
 */
import { getConfig } from "./config.js";
import { h } from "../core/dom.js";
import { hasCoords } from "./planner.js";

// ------------------------------------------------------------ 加载高德 ----
let amapPromise = null;

function loadScript(src, timeout = 9000) {
  return new Promise((resolve, reject) => {
    const s = h("script", { src, async: true });
    const t = setTimeout(() => (s.remove(), reject(new Error("timeout"))), timeout);
    s.onload = () => (clearTimeout(t), resolve());
    s.onerror = () => (clearTimeout(t), s.remove(), reject(new Error("load error")));
    document.head.append(s);
  });
}

export function loadAMap() {
  amapPromise ||= (async () => {
    const cfg = await getConfig();
    if (!cfg.amap?.key) throw new Error("no key");
    window._AMapSecurityConfig = { securityJsCode: cfg.amap.securityJsCode };
    await loadScript(`https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(cfg.amap.key)}`);
    if (!window.AMap) throw new Error("AMap missing");
    return window.AMap;
  })();
  return amapPromise;
}

const plugin = (AMap, names) => new Promise((res) => AMap.plugin(names, res));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- 图钉 ----
function pinEl({ label, color, dim, title }) {
  return h(
    "div",
    { class: ["pin", dim && "pin--dim"], style: { "--c": color }, title },
    h("div", { class: "pin-badge" }, label),
    h("div", { class: "pin-tip" })
  );
}

// ------------------------------------------------------------ 高德实现 ----
class AMapView {
  kind = "amap";

  constructor(AMap, el, opts) {
    this.AMap = AMap;
    this.opts = opts;
    this.markers = new Map();
    this.lines = [];
    this.routeToken = 0;
    this.cache = new Map(); // 同一对点 + 出行方式只查一次
    const dark = document.documentElement.dataset.theme === "dark";
    this.map = new AMap.Map(el, {
      zoom: 12,
      center: [121.4737, 31.2304],
      mapStyle: dark ? "amap://styles/dark" : "amap://styles/whitesmoke",
      viewMode: "2D",
      resizeEnable: true,
    });
    this.tip = null;
  }

  setMarkers(list) {
    this.map.remove([...this.markers.values()]);
    this.markers.clear();
    const created = list.filter(hasCoords).map((m) => {
      const marker = new this.AMap.Marker({
        position: [m.lng, m.lat],
        anchor: "bottom-center",
        content: pinEl(m),
        zIndex: m.dim ? 100 : 110,
        title: m.title,
      });
      marker.on("click", () => this.opts.onMarkerClick?.(m.id));
      const el = marker.getContent?.();
      marker._el = el;
      this.markers.set(m.id, marker);
      return marker;
    });
    this.map.add(created);
    this._lastList = list;
  }

  fit(ids) {
    const targets = ids ? ids.map((i) => this.markers.get(i)).filter(Boolean) : [...this.markers.values()];
    if (targets.length) this.map.setFitView(targets, false, [70, 70, 70, 70]);
  }

  focus(id) {
    const m = this.markers.get(id);
    if (!m) return;
    this.map.setCenter(m.getPosition());
    m.setzIndex?.(300);
    const el = m.getContent();
    el?.classList?.add("pin--bounce");
    setTimeout(() => el?.classList?.remove("pin--bounce"), 900);
  }

  clearRoutes() {
    this.routeToken++;
    if (this.lines.length) this.map.remove(this.lines);
    this.lines = [];
    this.tip?.close?.();
  }

  /** 拉取真实路网并画线；同一时刻只有最后一次调用生效 */
  async setRoutes(segments, mode = "transfer", { onProgress, city = "上海" } = {}) {
    this.clearRoutes();
    const token = this.routeToken;
    const AMap = this.AMap;
    const pluginName = { transfer: "AMap.Transfer", walking: "AMap.Walking", driving: "AMap.Driving", riding: "AMap.Riding" }[mode] || "AMap.Transfer";
    try {
      await plugin(AMap, [pluginName]);
    } catch {
      /* 落到直线 */
    }
    let done = 0;
    for (const seg of segments) {
      if (token !== this.routeToken) return;
      const key = `${mode}:${seg.from.lng},${seg.from.lat}>${seg.to.lng},${seg.to.lat}`;
      const cached = this.cache.has(key);
      const info = cached ? this.cache.get(key) : await this._query(seg, mode, city);
      if (!cached) this.cache.set(key, info);
      if (token !== this.routeToken) return;
      const real = info?.path?.length >= 2;
      const line = new AMap.Polyline({
        path: real ? info.path : [[seg.from.lng, seg.from.lat], [seg.to.lng, seg.to.lat]],
        strokeColor: seg.color,
        strokeWeight: real ? 5 : 3,
        strokeOpacity: real ? 0.85 : 0.5,
        strokeStyle: real ? "solid" : "dashed",
        strokeDasharray: real ? undefined : [10, 6],
        lineJoin: "round",
        lineCap: "round",
        zIndex: 50,
      });
      line.on("click", (e) => this._showTip(e.lnglat, info, seg));
      this.map.add(line);
      this.lines.push(line);
      onProgress?.(++done, segments.length);
      if (!cached) await sleep(320); // 高德个人 Key 有 QPS 限制
    }
  }

  _query(seg, mode, city) {
    const AMap = this.AMap;
    return new Promise((resolve) => {
      try {
        const planner = mode === "walking" ? new AMap.Walking() : mode === "driving" ? new AMap.Driving() : mode === "riding" ? new AMap.Riding() : new AMap.Transfer({ city });
        planner.search([seg.from.lng, seg.from.lat], [seg.to.lng, seg.to.lat], (status, result) => {
          if (status !== "complete") return resolve(null);
          resolve(extract(mode, result));
        });
      } catch {
        resolve(null);
      }
    });
  }

  _showTip(lnglat, info, seg) {
    this.tip ||= new this.AMap.InfoWindow({ offset: new this.AMap.Pixel(0, -6), isCustom: false });
    const body = h(
      "div",
      { class: "route-tip" },
      info
        ? [h("b", null, `预计 ${Math.max(1, Math.round(info.time / 60))} 分钟`), h("span", null, `约 ${(info.distance / 1000).toFixed(1)} 公里`)]
        : [h("b", null, "暂无该方式的路线"), h("span", null, "虚线为直线示意，可切换其他交通方式")]
    );
    this.tip.setContent(body);
    this.tip.open(this.map, lnglat);
  }

  destroy() {
    this.clearRoutes();
    try {
      this.map.destroy();
    } catch {}
  }
}

function extract(mode, result) {
  try {
    if (mode === "transfer") {
      const plan = (result.plans || [])[0];
      if (!plan) return null;
      let path = plan.path;
      if (!path?.length) {
        path = [];
        (plan.segments || []).forEach((seg) => {
          seg.walking?.steps?.forEach((st) => st.path?.forEach((p) => path.push(p)));
          seg.bus?.busLines?.[0]?.path?.forEach((p) => path.push(p));
        });
      }
      return path.length >= 2 ? { path, time: plan.time || 0, distance: plan.distance || 0 } : null;
    }
    const route = (result.routes || [])[0] || result.route;
    if (!route) return null;
    const path = [];
    (route.steps || route.rides || []).forEach((st) => (st.path || []).forEach((p) => path.push(p)));
    return path.length >= 2 ? { path, time: route.time || 0, distance: route.distance || 0 } : null;
  } catch {
    return null;
  }
}

// -------------------------------------------------------- 手账示意图降级 ----
const NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}, ...kids) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) v != null && e.setAttribute(k, v);
  kids.flat().forEach((k) => k != null && e.append(k));
  return e;
};

class SchematicView {
  kind = "schematic";

  constructor(el, opts, reason) {
    this.el = el;
    this.opts = opts;
    this.markers = [];
    this.routes = [];
    this.focusId = null;
    this.reason = reason;
    this.root = h("div", { class: "schematic" });
    this.note = h("div", { class: "schematic-note" }, "示意图 · 地图服务暂不可用，位置为相对关系");
    el.replaceChildren(this.root, this.note);
    this._ro = new ResizeObserver(() => this._draw());
    this._ro.observe(el);
  }

  setMarkers(list) {
    this.markers = list.filter(hasCoords);
    this._draw();
  }

  async setRoutes(segments) {
    this.routes = segments;
    this._draw();
  }
  clearRoutes() {
    this.routes = [];
    this._draw();
  }
  fit() {}
  focus(id) {
    this.focusId = id;
    this._draw();
  }

  _draw() {
    const w = this.el.clientWidth || 600;
    const hgt = this.el.clientHeight || 420;
    const pts = [...this.markers, ...this.routes.flatMap((r) => [r.from, r.to])];
    if (!pts.length) return this.root.replaceChildren(h("div", { class: "schematic-empty" }, "还没有可显示的地点"));
    const lats = pts.map((p) => p.lat);
    const lngs = pts.map((p) => p.lng);
    const [minLat, maxLat, minLng, maxLng] = [Math.min(...lats), Math.max(...lats), Math.min(...lngs), Math.max(...lngs)];
    const kx = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
    const spanX = Math.max((maxLng - minLng) * kx, 0.004);
    const spanY = Math.max(maxLat - minLat, 0.004);
    const pad = 56;
    const scale = Math.min((w - pad * 2) / spanX, (hgt - pad * 2) / spanY);
    const ox = (w - spanX * scale) / 2;
    const oy = (hgt - spanY * scale) / 2;
    const px = (lng) => ox + (lng - minLng) * kx * scale;
    const py = (lat) => oy + (maxLat - lat) * scale;

    const svg = svgEl("svg", { viewBox: `0 0 ${w} ${hgt}`, width: "100%", height: "100%", role: "img", "aria-label": "路线示意图" });
    svg.append(
      svgEl("defs", {}, svgEl("pattern", { id: "grid", width: 28, height: 28, patternUnits: "userSpaceOnUse" }, svgEl("path", { d: "M28 0H0V28", fill: "none", stroke: "var(--line-2)", "stroke-width": 1 }))),
      svgEl("rect", { width: w, height: hgt, fill: "url(#grid)" })
    );
    this.routes.forEach((r) => {
      svg.append(svgEl("line", { x1: px(r.from.lng), y1: py(r.from.lat), x2: px(r.to.lng), y2: py(r.to.lat), stroke: r.color, "stroke-width": 3.5, "stroke-dasharray": "2 8", "stroke-linecap": "round", opacity: 0.9 }));
    });
    this.markers.forEach((m) => {
      const x = px(m.lng);
      const y = py(m.lat);
      const active = m.id === this.focusId;
      const g = svgEl(
        "g",
        { class: "sch-pin", tabindex: 0, role: "button", "aria-label": m.title, transform: `translate(${x},${y})`, opacity: m.dim ? 0.4 : 1, style: "cursor:pointer" },
        svgEl("circle", { r: active ? 17 : 13, fill: m.color, stroke: "var(--card-2)", "stroke-width": 3 }),
        Object.assign(svgEl("text", { "text-anchor": "middle", dy: "0.35em", fill: "#fff", "font-size": 11, "font-weight": 700, "font-family": "var(--font-mono)" }), { textContent: m.label }),
        Object.assign(svgEl("text", { x: 19, y: 4, "font-size": 12, fill: "var(--ink)", "font-weight": 500, style: "paint-order:stroke;stroke:var(--card);stroke-width:4px" }), { textContent: (m.title || "").split(" · ").pop().slice(0, 10) })
      );
      g.addEventListener("click", () => this.opts.onMarkerClick?.(m.id));
      g.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), this.opts.onMarkerClick?.(m.id)));
      svg.append(g);
    });
    this.root.replaceChildren(svg);
  }

  destroy() {
    this._ro.disconnect();
  }
}

// ---------------------------------------------------------------- 入口 ----
export async function createMapView(container, opts = {}) {
  container.replaceChildren(h("div", { class: "map-loading" }, h("span", { class: "skeleton", style: { width: "100%", height: "100%" } })));
  try {
    const AMap = await loadAMap();
    container.replaceChildren();
    return new AMapView(AMap, container, opts);
  } catch (e) {
    console.info("[map] 高德不可用，使用示意图：", e.message);
    return new SchematicView(container, opts, e.message);
  }
}

// ------------------------------------------------------------- 地点搜索 ----
/** 搜索真实地点（用于「添加自定义景点」拿到坐标）。地图不可用时返回 []。 */
export async function searchPlaces(query, city = "上海") {
  try {
    const AMap = await loadAMap();
    await plugin(AMap, ["AMap.PlaceSearch"]);
    return await new Promise((resolve) => {
      const ps = new AMap.PlaceSearch({ city, pageSize: 6, citylimit: true });
      ps.search(query, (status, res) => {
        if (status !== "complete") return resolve([]);
        resolve(
          (res.poiList?.pois || []).map((p) => ({
            id: `poi_${p.id}`,
            name: p.name,
            address: [p.pname, p.cityname, p.adname, p.address].filter((v) => typeof v === "string").join(""),
            lng: p.location?.lng,
            lat: p.location?.lat,
            type: guessType(p.type),
            category: (p.type || "").split(";")[0] || "地点",
          }))
        );
      });
    });
  } catch {
    return [];
  }
}

function guessType(t = "") {
  if (/餐饮|咖啡|茶|小吃|甜品/.test(t)) return "food";
  if (/公园|风景|自然|植物/.test(t)) return "nature";
  if (/博物|美术|展览|文化|寺|教堂|纪念/.test(t)) return "culture";
  if (/购物|商场|步行街|市场/.test(t)) return "street";
  return "landmark";
}
