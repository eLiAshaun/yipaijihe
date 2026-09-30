/** 行程页的展示部件：景点卡片 / 通勤连接线 / 预算面板 / 行前清单 */
import { h } from "../core/dom.js";
import { icon, typeIcon, typeLabel } from "../core/icons.js";
import { storage, state } from "../core/state.js";
import { STORAGE } from "../core/config.js";
import { toMin, fromMin, fmtDuration, TRAVEL_MODES, stopName, stopLocation, stopDuration, buildPackingList } from "../services/planner.js";

// --------------------------------------------------------------- 时间选项 ----
function timeOptions(selected) {
  const opts = [];
  const vals = new Set();
  for (let m = 6 * 60; m < 24 * 60; m += 15) vals.add(fromMin(m));
  if (selected && !vals.has(selected)) vals.add(selected);
  [...vals].sort().forEach((v) => opts.push(h("option", { value: v, selected: v === selected }, v)));
  return opts;
}

const DURATIONS = [30, 45, 60, 75, 90, 120, 150, 180, 240];
function durationOptions(cur) {
  const list = [...new Set([...DURATIONS, cur])].sort((a, b) => a - b);
  return list.map((d) => h("option", { value: d, selected: d === cur }, fmtDuration(d)));
}

const FEEDBACK = {
  like: { icon: "thumbs-up", label: "感兴趣", tag: "tag--sea" },
  must: { icon: "star", label: "必去", tag: "tag--sun" },
  dislike: { icon: "thumbs-down", label: "换一个" },
};

// ---------------------------------------------------------------- 景点卡片 ----
/** act: { select, move, moveDay, remove, feedback, time, duration } */
export function stopCard({ stop, di, si, count, days, active, feedback, warn }, act) {
  const loc = stopLocation(stop);
  const name = stopName(stop);
  const dur = stopDuration(stop);
  const fb = feedback && FEEDBACK[feedback];

  return h(
    "li",
    { class: ["stop", active && "is-active", warn && "has-warn"], "data-id": stop.__stopId, "data-di": di, "data-si": si },
    h("div", { class: "stop-time" },
      h("select", { class: "select select--time", "aria-label": `${name} 开始时间`, onchange: (e) => act.time(stop.__stopId, e.target.value), onclick: (e) => e.stopPropagation() }, timeOptions(stop.time))),
    h("div", { class: "stop-rail", "aria-hidden": "true" }, h("i", { class: "stop-dot" })),
    h(
      "div",
      { class: "stop-card", tabindex: 0, role: "button", "aria-label": `${name}，点击在地图上查看`, onclick: () => act.select(stop.__stopId), onkeydown: (e) => (e.key === "Enter" || e.key === " ") && e.target === e.currentTarget && (e.preventDefault(), act.select(stop.__stopId)) },
      h("div", { class: "stop-top" },
        h("span", { class: "stop-grip", "data-grip": "", title: "拖动排序", "aria-hidden": "true" }, icon("grip")),
        h("h4", { class: "stop-name" }, name),
        loc.type && h("span", { class: "type-badge", "data-type": loc.type }, icon(typeIcon(loc.type)), typeLabel(loc.type)),
        fb && h("span", { class: ["tag", fb.tag] }, fb.label === "换一个" ? "已换" : fb.label)),
      (stop.activity && stop.activity !== name) || stop.notes
        ? h("p", { class: "stop-note" }, [stop.activity && stop.activity !== name ? stop.activity : "", stop.notes ? (stop.activity && stop.activity !== name ? " · " : "") + stop.notes : ""].join(""))
        : null,
      h("div", { class: "stop-tools", onclick: (e) => e.stopPropagation() },
        h("label", { class: "dur", title: "停留时长" }, icon("clock"), h("select", { "aria-label": `${name} 停留时长`, onchange: (e) => act.duration(stop.__stopId, Number(e.target.value)) }, durationOptions(dur))),
        h("span", { class: "stop-actions" },
          h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "上移", disabled: si === 0, onclick: () => act.move(di, si, -1) }, icon("arrow-up")),
          h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "下移", disabled: si === count - 1, onclick: () => act.move(di, si, 1) }, icon("arrow-down")),
          days > 1 && h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": di < days - 1 ? "移到下一天" : "移到上一天", title: di < days - 1 ? "移到下一天" : "移到上一天", onclick: () => act.moveDay(di, si, di < days - 1 ? 1 : -1) }, icon(di < days - 1 ? "chevron-right" : "arrow-left")),
          ["like", "must"].map((k) => h("button", { class: ["icon-btn icon-btn--sm", feedback === k && "is-on"], type: "button", "aria-pressed": String(feedback === k), "aria-label": FEEDBACK[k].label, title: FEEDBACK[k].label, onclick: () => act.feedback(stop.__stopId, k) }, icon(FEEDBACK[k].icon))),
          h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "换一个类似的", title: "换一个类似的", onclick: () => act.feedback(stop.__stopId, "dislike") }, icon("refresh")),
          h("button", { class: "icon-btn icon-btn--sm danger", type: "button", "aria-label": `删除 ${name}`, title: "删除", onclick: () => act.remove(stop.__stopId) }, icon("trash")))
      )
    )
  );
}

/** 两站之间的通勤连接线 */
export function travelConnector(seg) {
  const t = seg.travel;
  if (!t) {
    return h("li", { class: "travel travel--unknown", "aria-hidden": "true" }, h("span", null, "无法估算通勤"));
  }
  const m = TRAVEL_MODES[t.mode];
  const tight = seg.slack != null && seg.slack < -5;
  return h(
    "li",
    { class: ["travel", tight && "is-tight"], "aria-label": `通勤 ${m.label} ${t.minutes} 分钟` },
    h("span", { class: "travel-pill" }, icon(m.icon), `${m.label} ${t.minutes} 分钟`, h("small", null, t.meters >= 1000 ? `${(t.meters / 1000).toFixed(1)} km` : `${t.meters} m`)),
    tight && h("span", { class: "travel-warn" }, icon("alert"), `来不及：还差 ${Math.abs(Math.round(seg.slack))} 分钟`),
    !tight && seg.slack > 60 && h("span", { class: "travel-free" }, `空档 ${fmtDuration(seg.slack)}`)
  );
}

// -------------------------------------------------------------- 预算面板 ----
export function budgetPanel(cost, { days, onBudget }) {
  const b = state.trip.budget || 0;
  const over = cost.budget && !cost.within_budget;
  const ratio = cost.budget ? Math.min(cost.ratio, 1.4) : 0;
  const rows = [["food", "餐饮", cost.food], ["ticket", "景点 / 体验", cost.spots], ["transport", "市内交通", cost.transport]];
  const total = Math.max(cost.per_person, 1);
  return h(
    "div",
    { class: "budget-panel" },
    h("div", { class: ["budget-hero", over && "is-over"] },
      h("small", { class: "mono" }, "预计人均花费"),
      h("b", null, `¥${cost.per_person}`),
      cost.budget
        ? h("span", { class: "budget-verdict" }, over ? `超出预算 ¥${Math.abs(cost.diff)}` : `预算内，还剩 ¥${cost.diff}`)
        : h("span", { class: "budget-verdict" }, "还没有设置预算")),
    cost.budget
      ? h("div", { class: "budget-meter", role: "img", "aria-label": `已用预算 ${Math.round(cost.ratio * 100)}%` }, h("i", { style: { width: `${Math.min(ratio, 1) * 100}%` } }), ratio > 1 && h("em", { style: { width: `${(ratio - 1) * 100}%` } }))
      : null,
    h("label", { class: "budget-edit" }, "人均预算 ¥", h("input", { class: "input", type: "number", min: 0, max: 100000, step: 50, value: b, onchange: (e) => onBudget(Math.max(0, parseInt(e.target.value, 10) || 0)) })),
    h("div", { class: "budget-split" },
      rows.map(([k, label, v]) => h("div", { class: "split-row" }, h("span", null, label), h("div", { class: "split-bar" }, h("i", { "data-k": k, style: { width: `${(v / total) * 100}%` } })), h("b", { class: "mono" }, `¥${v}`)))),
    days > 1 && h("div", { class: "budget-days" }, h("p", { class: "field-label" }, "每天花费"), cost.perDay.map((d, i) => h("div", { class: "split-row" }, h("span", null, `Day ${i + 1}`), h("div", { class: "split-bar" }, h("i", { style: { width: `${(d.total / Math.max(...cost.perDay.map((x) => x.total), 1)) * 100}%`, background: `var(--day-${(i % 8) + 1})` } })), h("b", { class: "mono" }, `¥${d.total}`)))),
    h("p", { class: "hint" }, "景点/餐饮按各地点的消费档位估价，交通按通勤方式与距离估算，仅供参考；住宿与大交通未计入。")
  );
}

// -------------------------------------------------------------- 行前清单 ----
const readChecks = () => {
  try {
    return JSON.parse(storage.get(STORAGE.checklist) || "{}");
  } catch {
    return {};
  }
};

export function checklistPanel({ itinerary, weather, tripKey }) {
  const groups = buildPackingList({ days: itinerary.days.length, weather, persona: state.persona, itinerary, hasBuddy: state.hasBuddy });
  const all = readChecks();
  const mine = (all[tripKey] ||= {});
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  const progress = h("div", { class: "progress" }, h("i"));
  const label = h("span", { class: "mono faint" });
  const sync = () => {
    const done = Object.values(mine).filter(Boolean).length;
    progress.firstChild.style.width = `${(Math.min(done, total) / total) * 100}%`;
    label.textContent = `${Math.min(done, total)} / ${total} 已准备`;
  };

  const root = h(
    "div",
    { class: "pack" },
    h("div", { class: "pack-head" }, h("div", null, h("b", null, "行前清单"), h("p", { class: "hint" }, "根据天数、天气、你的旅行人格和行程内容生成")), label),
    progress,
    groups.map((g) =>
      h("section", { class: "pack-group" }, h("h4", null, g.title),
        h("ul", null, g.items.map((it) =>
          h("li", null, h("label", { class: "pk" },
            h("input", { type: "checkbox", checked: !!mine[it.id], onchange: (e) => {
              mine[it.id] = e.target.checked;
              storage.set(STORAGE.checklist, JSON.stringify({ ...readChecks(), [tripKey]: mine }));
              sync();
            } }),
            h("span", { class: "pk-box" }, icon("check")),
            h("span", { class: "pk-text" }, it.text, it.why && h("small", null, it.why)))))))
    )
  );
  sync();
  return root;
}
