import { h, mountInto, debounce } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { api } from "../core/api.js";
import { state, bus, persistDraft } from "../core/state.js";
import { dayHex, dayColorVar } from "../core/config.js";
import { createMapView, searchPlaces } from "../services/map.js";
import {
  toMin, fromMin, snap15, hasCoords, haversine, stopLocation, stopName, stopDuration, stopEnd, fmtDuration, estimateTravel,
  daySegments, dayStats, dayWarnings, reflowDay, optimizeDay, estimateCost, weatherInfo, weatherAdvice, dayDate, fmtDate, PACES,
  isMeal, mealBlock, insights, TRAVEL_MODES,
} from "../services/planner.js";
import { navUrl, nearbyUrl, douyinUrl, anchorBefore } from "../services/links.js";
import { newStopId, generateItinerary } from "../services/itinerary.js";
import { saveTrip, autosave } from "../services/trips.js";
import { stopCard, travelConnector, budgetPanel, checklistPanel } from "./itinerary-parts.js";
import { toast, toastError } from "../ui/toast.js";
import { confirmDialog } from "../ui/modal.js";

const TRANSPORT = [["transfer", "公交", "transit"], ["walking", "步行", "walk"], ["driving", "驾车", "taxi"], ["riding", "骑行", "route"]];
const pad = (n) => String(n).padStart(2, "0");
const clock = (d = new Date()) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;

export default {
  title: () => "路线编辑",

  mount(root, ctx) {
    let tab = "route";
    let dayFilter = -1;
    let activeId = null;
    let map = null;
    let saveState = state.tripId ? "saved" : "new";
    let savedAt = null;
    const undoStack = [];
    const redoStack = [];

    const itin = () => state.itinerary;
    const days = () => itin().days;

    const page = h("section", { class: "page page--wide itin" });
    root.append(page);

    const headEl = h("header", { class: "itin-head" });
    const tabsEl = h("div", { class: "itin-tabs", role: "tablist" });
    const bodyEl = h("div", { class: "itin-body" });
    const mapEl = h("div", { class: "map-canvas", role: "region", "aria-label": "路线地图" });
    const cardEl = h("aside", { class: "map-card", hidden: true });
    const mapHead = h("div", { class: "map-head" });
    const dragState = { current: null };

    // ================================================= 历史（撤销 / 重做） ====
    const snap = () => JSON.stringify({ it: itin(), fb: state.feedbacks });
    const restore = (s) => {
      const { it, fb } = JSON.parse(s);
      state.itinerary = it;
      state.feedbacks = fb;
    };

    function commit(mutator, { reflow = [], message } = {}) {
      undoStack.push(snap());
      if (undoStack.length > 40) undoStack.shift();
      redoStack.length = 0;
      mutator();
      reflow.forEach(reflowAt);
      changed();
      message && toast(message);
    }
    function undo() {
      if (!undoStack.length) return;
      redoStack.push(snap());
      restore(undoStack.pop());
      changed();
      toast("已撤销");
    }
    function redo() {
      if (!redoStack.length) return;
      undoStack.push(snap());
      restore(redoStack.pop());
      changed();
      toast("已重做");
    }
    function changed() {
      state.cost = estimateCost(itin(), { budget: state.trip.budget });
      if (activeId && !findStop(activeId)) activeId = null;
      saveState = state.tripId ? "dirty" : "new";
      renderAll();
      redraw();
      autosave();
    }

    // ===================================================== 数据操作 ====
    function findStop(id) {
      for (let di = 0; di < days().length; di++) {
        const si = days()[di].items.findIndex((s) => s.__stopId === id);
        if (si >= 0) return { di, si, stop: days()[di].items[si] };
      }
      return null;
    }

    function reflowAt(di) {
      const day = days()[di];
      if (!day?.items.length) return;
      const times = day.items.map((s) => toMin(s.time)).filter((v) => v != null);
      const start = times.length ? Math.min(...times) : 9 * 60;
      days()[di] = reflowDay(day, { startTime: fromMin(start) });
    }

    /** 追加到某天末尾时的默认开始时间：上一站结束 + 通勤 */
    function nextTime(di, stop) {
      const items = days()[di].items;
      const last = items[items.length - 1];
      if (!last) return "09:30";
      const end = stopEnd(last);
      if (end == null) return "10:00";
      const t = estimateTravel(stopLocation(last), stopLocation(stop));
      return fromMin(Math.min(snap15(end + (t ? t.minutes : 15)), 23 * 60));
    }

    const recToStop = (rec) => ({ time: "", location_id: rec.location_id, activity: rec.activity || `探索${rec.location?.name || ""}`, notes: rec.reason || "", location: rec.location || {}, __stopId: newStopId("rec") });

    const act = {
      select(id) {
        activeId = id;
        const f = findStop(id);
        if (f && hasCoords(stopLocation(f.stop))) map?.focus(id);
        renderActive();
      },
      move(di, si, delta) {
        commit(() => {
          const items = days()[di].items;
          const [it] = items.splice(si, 1);
          items.splice(si + delta, 0, it);
        }, { reflow: [di] });
      },
      moveDay(di, si, dir) {
        const to = di + dir;
        if (!days()[to]) return;
        commit(() => {
          const [it] = days()[di].items.splice(si, 1);
          it.time = nextTime(to, it);
          days()[to].items.push(it);
        }, { reflow: [di, to], message: `已移到 ${days()[to].title}` });
      },
      remove(id) {
        const f = findStop(id);
        if (!f) return;
        commit(() => {
          days()[f.di].items.splice(f.si, 1);
          delete state.feedbacks[id];
        }, { message: `已删除「${stopName(f.stop)}」，可点 ↶ 撤销` });
      },
      feedback(id, kind) {
        const f = findStop(id);
        if (!f) return;
        if (kind === "dislike") return replaceWithSimilar(f);
        commit(() => {
          state.feedbacks[id] === kind ? delete state.feedbacks[id] : (state.feedbacks[id] = kind);
        });
      },
      time(id, value) {
        const f = findStop(id);
        if (!f) return;
        commit(() => {
          f.stop.time = value;
          days()[f.di].items.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
        });
      },
      duration(id, v) {
        const f = findStop(id);
        f && commit(() => (f.stop.duration_min = v));
      },
      lock(id) {
        const f = findStop(id);
        if (!f) return;
        commit(() => (f.stop.locked = !f.stop.locked), { message: f.stop.locked ? "已取消锁定" : `已锁定 ${f.stop.time}：自动排时间、优化顺序都不会改动它` });
      },
    };

    /** 同一个地点不重复加入：提示它已经在第几天，并高亮出来 */
    function alreadyIn(name) {
      for (let di = 0; di < days().length; di++) {
        const hit = days()[di].items.find((s) => !isMeal(s) && stopName(s) === name);
        if (hit) {
          toast(`「${name}」已经在 ${days()[di].title} 里了`, { error: true });
          const el = bodyEl.querySelector(`.stop[data-id="${CSS.escape(hit.__stopId)}"]`);
          el?.scrollIntoView({ behavior: "smooth", block: "center" });
          el?.classList.add("flash");
          setTimeout(() => el?.classList.remove("flash"), 1200);
          return true;
        }
      }
      return false;
    }

    /** 「换一个」：从推荐池挑同类型、最近的景点替换，原景点回到推荐池 */
    function replaceWithSimilar({ di, si, stop }) {
      const recs = itin().recommendations || [];
      const loc = stopLocation(stop);
      let best = -1;
      let bestScore = Infinity;
      recs.forEach((r, i) => {
        const rl = r.location || {};
        const score = (rl.type === loc.type ? 0 : 5e6) + (hasCoords(rl) && hasCoords(loc) ? haversine(loc, rl) : 1e5);
        if (score < bestScore) [bestScore, best] = [score, i];
      });
      if (best < 0) return toast("推荐池里暂时没有可替换的景点，可以手动添加", { error: true });
      const newName = recs[best].location?.name || recs[best].activity || "新景点";
      commit(() => {
        const [rec] = recs.splice(best, 1);
        const repl = recToStop(rec);
        repl.time = stop.time;
        days()[di].items.splice(si, 1, repl);
        recs.push({ location_id: stop.location_id, activity: stop.activity, reason: "之前的安排", location: loc });
        delete state.feedbacks[stop.__stopId];
      }, { reflow: [di], message: `已换成「${newName}」，原景点放回了推荐池` });
    }

    function addRec(recIdx, di, idx) {
      const recs = itin().recommendations || [];
      if (!recs[recIdx] || !days()[di]) return;
      if (alreadyIn(recs[recIdx].location?.name || recs[recIdx].activity)) return;
      commit(() => {
        const [rec] = recs.splice(recIdx, 1);
        const s = recToStop(rec);
        const items = days()[di].items;
        s.time = idx == null || idx >= items.length ? nextTime(di, s) : items[idx]?.time || "10:00";
        items.splice(idx ?? items.length, 0, s);
      }, { reflow: [di], message: `已添加到 ${days()[di].title}` });
    }

    function moveStop(id, toDi, idx) {
      const f = findStop(id);
      if (!f) return;
      commit(() => {
        const [it] = days()[f.di].items.splice(f.si, 1);
        let at = idx;
        if (f.di === toDi && at > f.si) at--;
        days()[toDi].items.splice(Math.max(0, Math.min(at, days()[toDi].items.length)), 0, it);
      }, { reflow: [...new Set([f.di, toDi])] });
    }

    function optimize(di) {
      const { day, savedMeters } = optimizeDay(days()[di]);
      if (!savedMeters) return toast("当前顺序已经是最顺路的了 👍");
      commit(() => {
        days()[di] = day;
        reflowAt(di);
      }, { message: `已优化 ${days()[di].title}：少走约 ${(savedMeters / 1000).toFixed(1)} km，并重排了时间` });
    }

    // ============================================================= 渲染 ====
    function weatherChip(di) {
      const w = state.weather[di];
      if (!w || w.code == null) return null;
      const info = weatherInfo(w.code);
      return h("span", { class: ["wx", info.rain && "wx--rain"], title: weatherAdvice(w) || info.label }, icon(info.icon), `${info.label} ${Math.round(w.tmin)}–${Math.round(w.tmax)}℃`, w.rain_prob >= 30 && h("small", null, `降水 ${w.rain_prob}%`));
    }

    /** 出发前：倒计时与待确认事项；旅行中：今天的下一站（含导航） */
    function tripBanner() {
      const start = dayDate(state.trip.startDate, 0);
      if (!start) return null;
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const diff = Math.round((start - today) / 86400000);
      if (diff > 0) {
        const todo = days().flatMap((d) => d.items).filter((s) => !isMeal(s) && insights(stopLocation(s)).needsBooking).map(stopName);
        return h("div", { class: "trip-banner" }, icon("calendar"), h("span", null, h("b", null, `距离出发还有 ${diff} 天`), todo.length ? `，记得提前预约：${todo.join("、")}` : "，行前清单里有为你准备的待办"));
      }
      const di = -diff;
      if (di < 0 || di >= days().length) return null;
      const now = new Date().getHours() * 60 + new Date().getMinutes();
      const segs = daySegments(days()[di]).filter((x) => !isMeal(x.stop));
      const cur = segs.find((x) => x.start != null && x.start <= now && x.end > now);
      const next = segs.find((x) => x.start != null && x.start > now);
      if (!cur && !next) return h("div", { class: "trip-banner" }, icon("check"), h("span", null, h("b", null, `今天是 Day ${di + 1}`), "，今天的行程已经走完，好好休息"));
      const target = next || cur;
      const loc = stopLocation(target.stop);
      const t = cur && next ? estimateTravel(stopLocation(cur.stop), loc) : null;
      const left = next ? next.start - now : 0;
      return h(
        "div",
        { class: "trip-banner trip-banner--live" },
        icon("nav"),
        h("span", null,
          h("b", null, `今天 Day ${di + 1}`),
          cur ? ` · 正在「${stopName(cur.stop)}」` : "",
          next ? ` · 下一站「${stopName(next.stop)}」${fromMin(next.start)}（还有 ${fmtDuration(left)}）` : " · 这是今天最后一站",
          t ? ` · ${TRAVEL_MODES[t.mode].label}约 ${t.minutes} 分钟` : ""),
        h("a", { class: "btn btn--sm btn--ink", href: navUrl(loc), target: "_blank", rel: "noopener noreferrer" }, icon("nav"), "导航")
      );
    }

    function renderHead() {
      const c = state.cost || estimateCost(itin(), { budget: state.trip.budget });
      const allStats = days().map(dayStats);
      const stops = allStats.reduce((n, s) => n + s.count, 0);
      const travel = allStats.reduce((n, s) => n + s.travelMin, 0);
      const warnCount = days().reduce((n, d, di) => n + dayWarnings(d, state.trip.pace, { date: dayDate(state.trip.startDate, di) }).filter((w) => w.level === "warn").length, 0);
      const over = c.budget && !c.within_budget;

      const saveLabel = saveState === "saved" ? `已保存 ${savedAt || ""}` : saveState === "dirty" ? "有未同步的修改" : "尚未保存";
      mountInto(
        headEl,
        h("a", { class: "back-link", href: "#/places" }, icon("arrow-left"), "返回地点筛选"),
        h("div", { class: "itin-title" },
          h("div", null, h("p", { class: "eyebrow" }, "STEP 06 · 路线编辑"), h("h1", null, "你的", h("span", { class: "mark" }, "专属路线")), h("p", { class: "muted" }, itin().summary || `${state.trip.city} ${days().length} 日行程`), itin().engine && h("p", { class: "engine-note" }, icon(itin().engine === "llm" ? "sparkles" : "route"), itin().engine === "llm" ? "大模型编排，行程引擎校验过时间与地点" : "行程引擎编排：按地理分天、建议时段、通勤与饭点排时间")),
          h("div", { class: "itin-tools" },
            h("div", { class: "tool-group" },
              h("button", { class: "icon-btn", type: "button", "aria-label": "撤销", title: "撤销 (Ctrl+Z)", disabled: !undoStack.length, onclick: undo }, icon("undo")),
              h("button", { class: "icon-btn", type: "button", "aria-label": "重做", title: "重做", disabled: !redoStack.length, onclick: redo }, icon("redo"))),
            h("button", { class: "btn btn--quiet btn--sm", type: "button", onclick: regenerate }, icon("refresh"), "重新生成"),
            h("button", { class: "btn btn--ink btn--sm", type: "button", onclick: save }, icon("download"), "保存行程"))),
        h("div", { class: "itin-meta" },
          h("label", { class: "date-pick" }, icon("calendar"), h("input", { type: "date", value: state.trip.startDate || "", "aria-label": "出发日期", onchange: (e) => { state.trip.startDate = e.target.value; loadWeather(); changed(); } }), !state.trip.startDate && h("small", null, "设置出发日期查看天气")),
          h("span", { class: "faint save-state", role: "status" }, saveLabel)),
        h("div", { class: "stats" },
          stat("天数", `${days().length}`, "天"),
          stat("地点", `${stops}`, "个"),
          stat("通勤", fmtDuration(travel).replace(" 小时 ", "h").replace(" 分钟", "m").replace(" 小时", "h").replace(" 分", "m"), "全程"),
          h("button", { class: ["stat stat--btn", over && "is-over"], type: "button", onclick: () => setTab("budget") }, h("small", null, over ? "超出预算" : "人均预计"), h("b", null, `¥${c.per_person}`), h("span", null, c.budget ? `预算 ¥${c.budget}` : "设置预算 →"))),
        tripBanner(),
        warnCount ? h("button", { class: "banner banner--warn banner--btn", type: "button", onclick: () => setTab("route") }, icon("alert"), `有 ${warnCount} 处安排需要留意，已在对应的天里标出`) : null
      );
    }
    const stat = (label, value, unit) => h("div", { class: "stat" }, h("small", null, label), h("b", null, value), h("span", null, unit));

    function setTab(t) {
      tab = t;
      renderTabs();
      renderBody();
    }

    function renderTabs() {
      const defs = [["route", "行程", "route"], ["budget", "预算", "wallet"], ["pack", "行前清单", "luggage"]];
      mountInto(tabsEl, defs.map(([k, label, ic]) => h("button", { class: "tab", role: "tab", type: "button", "aria-selected": String(tab === k), onclick: () => setTab(k) }, icon(ic), label)));
    }

    function renderDayBar() {
      const all = h("button", { class: "day-tab", type: "button", "aria-pressed": String(dayFilter < 0), onclick: () => filterDay(-1) }, h("b", null, "全部"), h("small", null, `${days().length} 天`));
      return h("div", { class: "day-bar", role: "group", "aria-label": "按天筛选" }, all, days().map((d, di) => {
        const dt = dayDate(state.trip.startDate, di);
        const w = state.weather[di];
        return h("button", { class: "day-tab", type: "button", style: { "--dc": dayColorVar(di) }, "aria-pressed": String(dayFilter === di), onclick: () => filterDay(di) },
          h("i", { class: "day-dot" }), h("b", null, `Day ${di + 1}`), h("small", null, dt ? `${dt.getMonth() + 1}/${dt.getDate()}` : `${d.items.length} 个点`), w?.code != null && icon(weatherInfo(w.code).icon, "day-wx"));
      }));
    }

    function filterDay(i) {
      dayFilter = i;
      renderBody();
      redraw({ fit: true });
    }

    function daySection(day, di) {
      const stats = dayStats(day);
      const warns = dayWarnings(day, state.trip.pace, { date: dayDate(state.trip.startDate, di) });
      const segs = daySegments(day);
      const dt = dayDate(state.trip.startDate, di);
      const conflict = warns.some((w) => w.code === "time-conflict");
      const advice = weatherAdvice(state.weather[di]);
      const warnIds = new Set(warns.filter((w) => w.stopId && w.level === "warn").map((w) => w.stopId));

      const list = h("ol", { class: "stops", "data-di": di });
      segs.forEach((seg) => {
        if (seg.index > 0) list.append(travelConnector(seg));
        list.append(stopCard({ stop: seg.stop, di, si: seg.index, count: segs.length, days: days().length, active: seg.stop.__stopId === activeId, feedback: state.feedbacks[seg.stop.__stopId], warn: warnIds.has(seg.stop.__stopId), anchor: isMeal(seg.stop) ? anchorBefore(day.items, seg.index) : null, city: state.trip.city }, act));
      });
      if (!segs.length) list.append(h("li", { class: "day-empty" }, "这天还是空的：把下方推荐拖进来，或点「添加景点」"));

      const addSlot = h("div", { class: "add-slot" });

      return h(
        "section",
        { class: "day", "data-di": di, style: { "--dc": dayColorVar(di) } },
        h("header", { class: "day-head" },
          h("span", { class: "day-badge mono" }, `D${di + 1}`),
          h("div", { class: "day-title" }, h("h3", null, day.title), h("small", { class: "faint" }, dt ? fmtDate(dt) : "")),
          weatherChip(di),
          h("div", { class: "day-actions" },
            h("button", { class: "btn btn--ghost btn--sm", type: "button", title: "调整顺序，让路线最顺路", disabled: segs.length < 3, onclick: () => optimize(di) }, icon("zap"), "优化顺序"),
            h("button", { class: "btn btn--ghost btn--sm", type: "button", title: "按停留时长和通勤重新排布时间", disabled: !segs.length, onclick: () => commit(() => reflowAt(di), { message: "已按停留与通勤重排时间" }) }, icon("clock"), "重排时间"))),
        segs.length ? h("p", { class: "day-stats mono" }, `${stats.count} 个点 · 游玩 ${fmtDuration(stats.visitMin)} · 通勤 ${fmtDuration(stats.travelMin)} · ${(stats.meters / 1000).toFixed(1)} km`, stats.start != null && ` · ${fromMin(stats.start)}–${fromMin(stats.end)}`) : null,
        advice && h("p", { class: "day-advice" }, icon("info"), advice),
        warns.filter((w) => w.level === "warn" || w.code === "no-meal" || w.code === "long-hop").length
          ? h("ul", { class: "warns" }, warns.filter((w) => w.level === "warn" || w.code === "no-meal" || w.code === "long-hop").slice(0, 4).map((w) => h("li", { class: `warn warn--${w.level}` }, icon(w.level === "warn" ? "alert" : "info"), w.message)),
              conflict && h("li", null, h("button", { class: "btn btn--sm btn--ink", type: "button", onclick: () => commit(() => reflowAt(di), { message: "已自动修复时间冲突" }) }, icon("wand"), "一键修复时间")))
          : null,
        list,
        addSlot,
        h("button", { class: "add-stop-btn", type: "button", onclick: (e) => openAdd(di, addSlot, e.currentTarget) }, icon("plus"), "添加景点")
      );
    }

    function recPool() {
      const recs = itin().recommendations || [];
      if (!recs.length) return null;
      return h("section", { class: "recs" },
        h("header", null, icon("sparkles"), h("h3", null, "更多推荐景点"), h("small", { class: "faint" }, "拖到某一天，或点右侧按钮加入")),
        h("div", { class: "rec-list" }, recs.map((r, i) => {
          const loc = r.location || {};
          return h("article", { class: "rec", draggable: true, "data-rec": i },
            h("div", { class: "rec-main" }, h("b", null, loc.name || r.activity), r.reason && h("small", null, r.reason)),
            h("div", { class: "rec-add" }, days().map((_, di) => h("button", { class: "chip", type: "button", style: { "--dc": dayColorVar(di) }, "aria-label": `加入 Day ${di + 1}`, onclick: () => addRec(i, di) }, `+D${di + 1}`))));
        })));
    }

    function renderBody() {
      if (tab === "budget") {
        const c = state.cost || estimateCost(itin(), { budget: state.trip.budget });
        return mountInto(bodyEl, budgetPanel(c, { days: days().length, onBudget: (v) => { state.trip.budget = v; changed(); } }));
      }
      if (tab === "pack") return mountInto(bodyEl, checklistPanel({ itinerary: itin(), weather: state.weather.filter((w) => w?.code != null), tripKey: state.tripId || "draft" }));
      mountInto(bodyEl, renderDayBar(), days().map((d, di) => (dayFilter < 0 || dayFilter === di) && daySection(d, di)), recPool());
    }

    function renderAll() {
      renderHead();
      renderTabs();
      renderBody();
      renderActive();
    }

    // ------------------------------------------------ 地图信息卡 ----
    function renderActive() {
      bodyEl.querySelectorAll(".stop").forEach((el) => el.classList.toggle("is-active", el.dataset.id === activeId));
      const f = activeId && findStop(activeId);
      if (!f) return (cardEl.hidden = true);
      const loc = stopLocation(f.stop);
      const end = stopEnd(f.stop);
      cardEl.hidden = false;
      mountInto(
        cardEl,
        h("button", { class: "icon-btn icon-btn--sm card-x", type: "button", "aria-label": "关闭", onclick: () => ((activeId = null), renderActive()) }, icon("x")),
        h("small", { class: "mono", style: { color: dayColorVar(f.di) } }, `${days()[f.di].title} · ${f.stop.time || "时间待定"}${end != null ? " – " + fromMin(end) : ""}`),
        h("h3", null, stopName(f.stop)),
        (loc.description || f.stop.notes) && h("p", { class: "muted" }, loc.description || f.stop.notes),
        h("dl", { class: "card-grid" },
          loc.best_time && [h("dt", null, "建议时段"), h("dd", null, loc.best_time)],
          loc.cost_level && [h("dt", null, "消费"), h("dd", null, loc.cost_level)],
          loc.address && [h("dt", null, "地址"), h("dd", null, loc.address)],
          loc.tips && [h("dt", null, "小贴士"), h("dd", null, loc.tips)]),
        insights(loc).needsBooking && h("p", { class: "card-flag" }, icon("alert"), "需要提前预约 / 订位"),
        insights(loc).lastTime != null && h("p", { class: "card-flag" }, icon("clock"), `末班约 ${fromMin(insights(loc).lastTime)}`),
        h("div", { class: "card-actions" },
          isMeal(f.stop)
            ? h("a", { class: "btn btn--sm btn--ink", href: nearbyUrl(anchorBefore(days()[f.di].items, f.si), "美食", state.trip.city), target: "_blank", rel: "noopener noreferrer" }, icon("food"), "附近餐厅")
            : [
                h("a", { class: "btn btn--sm btn--ink", href: navUrl(loc), target: "_blank", rel: "noopener noreferrer" }, icon("nav"), "导航"),
                h("a", { class: "btn btn--sm btn--quiet", href: nearbyUrl(loc, "美食", state.trip.city), target: "_blank", rel: "noopener noreferrer" }, icon("food"), "附近吃的"),
                h("a", { class: "btn btn--sm btn--quiet", href: douyinUrl(stopName(f.stop)), target: "_blank", rel: "noopener noreferrer" }, icon("film"), "抖音攻略"),
              ],
          h("button", { class: "btn btn--sm btn--quiet", type: "button", onclick: () => act.remove(f.stop.__stopId) }, icon("trash"), "删除"))
      );
    }

    // ============================================================ 地图 ====
    function markerList() {
      const out = [];
      days().forEach((day, di) => day.items.forEach((s, si) => {
        const loc = stopLocation(s);
        if (!hasCoords(loc)) return;
        out.push({ id: s.__stopId, lng: Number(loc.lng), lat: Number(loc.lat), label: String(si + 1), color: dayHex(di), dim: dayFilter >= 0 && dayFilter !== di, title: `${day.title} · ${stopName(s)}` });
      }));
      return out;
    }

    function segmentList() {
      const out = [];
      days().forEach((day, di) => {
        if (dayFilter >= 0 && dayFilter !== di) return;
        const pts = day.items.filter((s) => hasCoords(stopLocation(s)));
        for (let i = 0; i < pts.length - 1; i++) {
          const a = stopLocation(pts[i]);
          const b = stopLocation(pts[i + 1]);
          out.push({ id: `${di}-${i}`, from: { lng: Number(a.lng), lat: Number(a.lat) }, to: { lng: Number(b.lng), lat: Number(b.lat) }, color: dayHex(di) });
        }
      });
      return out;
    }

    const routeStatus = h("span", { class: "route-status faint", role: "status" });
    const redraw = debounce(({ fit } = {}) => {
      if (!map) return;
      map.setMarkers(markerList());
      const segs = segmentList();
      routeStatus.textContent = segs.length ? "路线绘制中…" : "";
      map.setRoutes(segs, state.transport, { city: state.trip.city, onProgress: (n, total) => (routeStatus.textContent = n >= total ? "" : `路线绘制中 ${n}/${total}`) });
      if (fit) map.fit(markerList().filter((m) => !m.dim).map((m) => m.id));
    }, 250);

    function renderMapHead() {
      mountInto(
        mapHead,
        h("div", { class: "segmented", role: "group", "aria-label": "交通方式" }, TRANSPORT.map(([k, label, ic]) => h("button", { type: "button", "aria-pressed": String(state.transport === k), onclick: () => {
          state.transport = k;
          renderMapHead();
          redraw();
        } }, icon(ic), label))),
        routeStatus,
        h("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: () => map?.fit() }, icon("target"), "全览")
      );
    }

    // ===================================================== 添加景点 ====
    let catalog = null;
    async function loadCatalog() {
      if (catalog) return catalog;
      try {
        catalog = (await api.get(`/api/locations/list?city=${encodeURIComponent(state.trip.city)}`)).locations || [];
      } catch {
        catalog = [];
      }
      return catalog;
    }

    async function openAdd(di, slot, btn) {
      if (slot.firstChild) return slot.replaceChildren();
      btn.disabled = true;
      const input = h("input", { class: "input", type: "text", placeholder: "输入景点或店名，如「武康路」", "aria-label": "景点名称", autocomplete: "off", autofocus: true });
      const results = h("ul", { class: "suggest", role: "listbox" });
      const close = () => {
        slot.replaceChildren();
        btn.disabled = false;
        btn.focus();
      };
      const pick = (loc, custom) => {
        if (alreadyIn(loc.name)) return;
        commit(() => {
          const stop = { time: "", location_id: loc.id && !String(loc.id).startsWith("poi_") ? loc.id : null, activity: `探索${loc.name}`, notes: loc.tips || loc.description || "", __stopId: newStopId(custom ? "custom" : "add"), location: { name: loc.name, lat: loc.lat, lng: loc.lng, type: loc.type || "landmark", category: loc.category, description: loc.description, address: loc.address, duration_min: loc.duration_min, cost_level: loc.cost_level, best_time: loc.best_time, tips: loc.tips } };
          stop.time = nextTime(di, stop);
          days()[di].items.push(stop);
        }, { message: `已添加「${loc.name}」` + (hasCoords(loc) ? "" : "（无坐标，不会显示在地图上）") });
      };
      const search = debounce(async () => {
        const q = input.value.trim().toLowerCase();
        if (!q) return results.replaceChildren();
        const local = (await loadCatalog()).filter((l) => l.name.toLowerCase().includes(q) || (l.tags || []).some((t) => t.toLowerCase().includes(q))).slice(0, 4);
        const remote = q.length >= 2 ? await searchPlaces(input.value.trim(), state.trip.city) : [];
        const seen = new Set(local.map((l) => l.name));
        const all = [...local.map((l) => ({ l, tag: "精选库" })), ...remote.filter((r) => !seen.has(r.name)).map((l) => ({ l, tag: "地图" }))];
        mountInto(results, [
          all.map(({ l, tag }) => h("li", null, h("button", { type: "button", role: "option", onclick: () => pick(l) }, h("b", null, l.name), h("small", null, `${tag} · ${l.category || ""} ${l.address || ""}`)))),
          h("li", null, h("button", { type: "button", onclick: () => input.value.trim() && pick({ name: input.value.trim() }, true) }, h("b", null, `＋ 自定义添加「${input.value.trim()}」`), h("small", null, "没有坐标，仅出现在行程里"))),
        ]);
      }, 250);
      input.addEventListener("input", search);
      input.addEventListener("keydown", (e) => e.key === "Escape" && close());
      const addMeal = (kind) => {
        commit(() => {
          const block = { ...mealBlock(kind), __stopId: newStopId("meal") };
          const items = days()[di].items;
          const lo = kind === "lunch" ? 11 * 60 + 30 : 17 * 60 + 30;
          const at = items.findIndex((x) => (toMin(x.time) ?? 0) >= lo);
          items.splice(at < 0 ? items.length : at, 0, block);
        }, { reflow: [di], message: `已预留${kind === "lunch" ? "午餐" : "晚餐"}时段，点卡片上的餐具图标可以搜附近餐厅` });
      };
      mountInto(
        slot,
        h("div", { class: "add-form" }, input, h("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: close }, "取消")),
        h("div", { class: "chip-row add-meal" }, h("span", { class: "faint" }, "或者："), h("button", { class: "chip", type: "button", onclick: () => addMeal("lunch") }, icon("food"), "预留午餐时段"), h("button", { class: "chip", type: "button", onclick: () => addMeal("dinner") }, icon("food"), "预留晚餐时段")),
        results
      );
      input.focus();
    }

    // ===================================================== 拖拽 ====
    function initDnd() {
      const root_ = bodyEl;
      let indicator = null;
      const clearInd = () => {
        indicator?.remove();
        indicator = null;
        root_.querySelectorAll(".drag-over").forEach((e) => e.classList.remove("drag-over"));
      };
      ctx.disposer.listen(root_, "mousedown", (e) => {
        const grip = e.target.closest("[data-grip]");
        if (grip) grip.closest(".stop").draggable = true;
      });
      ctx.disposer.listen(root_, "dragstart", (e) => {
        const stopEl = e.target.closest?.(".stop");
        const recEl = e.target.closest?.(".rec");
        if (stopEl?.draggable) dragState.current = { type: "stop", id: stopEl.dataset.id };
        else if (recEl) dragState.current = { type: "rec", idx: Number(recEl.dataset.rec) };
        else return;
        (stopEl || recEl).classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", "x");
      });
      ctx.disposer.listen(root_, "dragend", (e) => {
        e.target.closest?.(".stop, .rec")?.classList.remove("dragging");
        root_.querySelectorAll(".stop[draggable=true]").forEach((s) => (s.draggable = false));
        dragState.current = null;
        clearInd();
      });
      const slotIndex = (ol, y) => {
        const els = [...ol.querySelectorAll(".stop:not(.dragging)")];
        const after = els.find((el) => y < el.getBoundingClientRect().top + el.offsetHeight / 2);
        return { before: after || null, index: after ? Number(after.dataset.si) : ol.querySelectorAll(".stop").length };
      };
      ctx.disposer.listen(root_, "dragover", (e) => {
        const ol = e.target.closest?.(".stops");
        if (!ol || !dragState.current) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const { before } = slotIndex(ol, e.clientY);
        if (!indicator) indicator = h("li", { class: "drop-indicator" });
        before ? ol.insertBefore(indicator, before.previousElementSibling?.classList.contains("travel") ? before.previousElementSibling : before) : ol.append(indicator);
        ol.closest(".day")?.classList.add("drag-over");
      });
      ctx.disposer.listen(root_, "dragleave", (e) => {
        if (!e.relatedTarget || !root_.contains(e.relatedTarget)) clearInd();
      });
      ctx.disposer.listen(root_, "drop", (e) => {
        const ol = e.target.closest?.(".stops");
        const d = dragState.current;
        if (!ol || !d) return;
        e.preventDefault();
        const di = Number(ol.dataset.di);
        const { index } = slotIndex(ol, e.clientY);
        clearInd();
        dragState.current = null;
        d.type === "stop" ? moveStop(d.id, di, index) : addRec(d.idx, di, index);
      });
    }

    // ================================================ 保存 / 重新生成 ====
    async function save() {
      try {
        await saveTrip();
        saveState = "saved";
        savedAt = clock();
        renderHead();
        toast("已保存到「我的行程」，之后可以随时继续编辑");
      } catch (e) {
        toastError(e);
      }
    }
    bus.on("trip:autosaved", () => {
      saveState = "saved";
      savedAt = clock();
      const el = headEl.querySelector(".save-state");
      if (el) el.textContent = `已保存 ${savedAt}`;
    });

    async function regenerate() {
      const selected = state.places.filter((p) => state.selectedIds.has(p.id));
      if (!selected.length) return toast("没有可用的地点池，请回到「地点筛选」重新选择", { error: true });
      if (!(await confirmDialog({ title: "重新生成路线？", message: "会基于「地点筛选」里勾选的地点重新排一遍，当前的手动修改将被替换（可撤销）。", confirmText: "重新生成" }))) return;
      const before = snap();
      try {
        toast("正在重新排路线…");
        await generateItinerary(selected);
        undoStack.push(before);
        redoStack.length = 0;
        activeId = null;
        dayFilter = -1;
        changed();
        redraw({ fit: true });
        toast("已重新生成");
      } catch (e) {
        toastError(e);
      }
    }

    async function loadWeather() {
      if (!state.trip.startDate) return (state.weather = []);
      try {
        const r = await api.get(`/api/weather?city=${encodeURIComponent(state.trip.city)}&start=${state.trip.startDate}&days=${days().length}`, { signal: ctx.signal });
        state.weather = r.available ? r.days : [];
        if (r.available && ctx.alive()) renderAll();
      } catch {
        state.weather = [];
      }
    }

    // ================================================================ 装配 ====
    state.cost = estimateCost(itin(), { budget: state.trip.budget });
    mountInto(
      page,
      headEl,
      h("div", { class: "split itin-split" },
        h("div", { class: "editor" }, tabsEl, bodyEl,
          h("div", { class: "page-foot" }, h("button", { class: "btn btn--primary btn--lg", type: "button", onclick: () => ctx.navigate("export") }, "导出 / 分享", icon("arrow-right", "i-arrow")))),
        h("div", { class: "sticky" }, h("div", { class: "map-frame" }, mapEl, cardEl), mapHead))
    );
    renderMapHead();
    renderAll();
    initDnd();
    ctx.disposer.listen(document, "keydown", (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z" || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) return;
      e.preventDefault();
      e.shiftKey ? redo() : undo();
    });

    (async () => {
      map = await createMapView(mapEl, {
        onMarkerClick: (id) => {
          activeId = id;
          renderActive();
          bodyEl.querySelector(`.stop[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
        },
      });
      if (!ctx.alive()) return map.destroy();
      ctx.disposer.add(() => map?.destroy());
      redraw({ fit: true });
      loadWeather();
    })();
    persistDraft();
  },
};
