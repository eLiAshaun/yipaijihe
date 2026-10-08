/**
 * 行程引擎 —— 纯函数，无 DOM 依赖，可在 Node 里直接单测。
 *
 * 数据模型沿用后端 / 历史记录里的形状，保证旧数据可读：
 *   itinerary = { summary, days: [{ title, items: [stop] }], tips, recommendations }
 *   stop      = { time: "HH:MM", activity, notes, location_id, duration_min?, location: { name, lat, lng, type, duration_min, cost_level } }
 */

// ---------------------------------------------------------------- 时间 ----
export function toMin(t) {
  if (typeof t !== "string") return null;
  const m = /^(\d{1,2}):(\d{2})$/.exec(t.trim());
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

export function fromMin(total) {
  const t = Math.max(0, Math.min(Math.round(total), 24 * 60 - 1));
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

export const snap15 = (min) => Math.round(min / 15) * 15;

export function fmtDuration(min) {
  const m = Math.round(min);
  if (m < 60) return `${m} 分钟`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h} 小时 ${r} 分` : `${h} 小时`;
}

// ---------------------------------------------------------------- 地理 ----
export function hasCoords(loc) {
  return !!loc && Number.isFinite(Number(loc.lat)) && Number.isFinite(Number(loc.lng)) && !!Number(loc.lat) && !!Number(loc.lng);
}

/** 两点球面距离（米） */
export function haversine(a, b) {
  const R = 6371000;
  const rad = (d) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(s), Math.sqrt(1 - s));
}

export const TRAVEL_MODES = {
  walk: { label: "步行", icon: "walk" },
  transit: { label: "地铁/公交", icon: "transit" },
  taxi: { label: "打车", icon: "taxi" },
};

/**
 * 估算两点通勤：直线距离 ×1.3 ≈ 实际路网距离。
 *  ≤1.3km 步行 · ≤9km 公共交通（含候车/换乘）· 更远建议打车
 */
export function estimateTravel(from, to) {
  if (!hasCoords(from) || !hasCoords(to)) return null;
  const meters = Math.round(haversine(from, to) * 1.3);
  const km = meters / 1000;
  let mode, minutes;
  if (km <= 1.3) {
    mode = "walk";
    minutes = (km / 4.8) * 60;
  } else if (km <= 9) {
    mode = "transit";
    minutes = (km / 24) * 60 + 12;
  } else {
    mode = "taxi";
    minutes = (km / 30) * 60 + 6;
  }
  return { meters, minutes: Math.max(3, snap5(minutes)), mode };
}
const snap5 = (m) => Math.max(1, Math.round(m / 5) * 5);

// ---------------------------------------------------------------- 景点 ----
export function stopLocation(stop) {
  return stop?.location || {};
}

export function stopName(stop) {
  return stopLocation(stop).name || stop?.activity || "未命名地点";
}

const DEFAULT_DURATION = { food: 75, nature: 90, culture: 100, landmark: 60, street: 90 };

export function stopDuration(stop) {
  const loc = stopLocation(stop);
  const d = Number(stop?.duration_min ?? loc.duration_min);
  if (Number.isFinite(d) && d >= 10) return d;
  return DEFAULT_DURATION[loc.type] || 75;
}

export function stopEnd(stop) {
  const s = toMin(stop.time);
  return s == null ? null : s + stopDuration(stop);
}

// ---------------------------------------------------------------- 节奏 ----
export const PACES = {
  relaxed: { key: "relaxed", label: "悠闲", maxStops: 4, maxSpanH: 10, hint: "每天 3–4 个点，留足停留和发呆的时间" },
  balanced: { key: "balanced", label: "适中", maxStops: 5, maxSpanH: 11.5, hint: "每天 4–5 个点，松紧适度" },
  packed: { key: "packed", label: "紧凑", maxStops: 7, maxSpanH: 13, hint: "每天 6–7 个点，效率优先" },
};

/** 由旅行人格推断默认节奏：覆盖打卡型→紧凑，深度停留型→悠闲 */
export function paceFromPersona(persona) {
  const cd = persona?.dimensions?.[3]?.value || persona?.mbti?.[3];
  if (cd === "C") return "packed";
  if (cd === "T") return "relaxed";
  return "balanced";
}

// ------------------------------------------------------------ 景点洞察 ----
const WEEKDAY_CN = "一二三四五六日";
const WINDOW_WORDS = [
  ["清晨", [7 * 60, 10 * 60]],
  ["早上", [7 * 60, 10 * 60]],
  ["上午", [8 * 60 + 30, 12 * 60]],
  ["中午", [11 * 60, 14 * 60]],
  ["下午", [13 * 60, 17 * 60 + 30]],
  ["傍晚", [17 * 60, 19 * 60 + 30]],
  ["日落", [17 * 60, 19 * 60 + 30]],
  ["夜间", [19 * 60, 22 * 60]],
  ["夜晚", [19 * 60, 22 * 60]],
  ["晚上", [19 * 60, 22 * 60]],
];
const insightCache = new WeakMap();

/**
 * 从景点的「建议时段 / 贴士 / 风险」文字里解析结构化信息（与后端 planner.insights 规则一致）：
 *  closedWeekdays  0=周一 … 6=周日
 *  needsBooking    需预约 / 订位
 *  lastTime        末班时间（分钟）
 *  window          建议时段 [开始, 结束]（分钟）
 *  weekdayOnly     建议工作日前往
 */
export function insights(loc) {
  if (!loc || typeof loc !== "object") return { closedWeekdays: [], needsBooking: false, lastTime: null, window: null, weekdayOnly: false };
  if (insightCache.has(loc)) return insightCache.get(loc);
  const text = ["tips", "risks", "best_time", "description"].map((k) => loc[k] || "").join(" ");
  const closed = new Set();
  for (const m of text.matchAll(/周([一二三四五六日天])[^，。；,;]{0,6}?(闭馆|休息|休馆|不开放|关闭|闭园)/g)) closed.add(WEEKDAY_CN.indexOf(m[1].replace("天", "日")));
  const needsBooking = /(?<!无需|不需|不用)(预约|订位|提前订|需购票)/.test(text);
  const last = /末班[^0-9]{0,4}(\d{1,2})[:：](\d{2})/.exec(text);
  const best = String(loc.best_time || "");
  const spans = WINDOW_WORDS.filter(([w]) => best.includes(w)).map(([, span]) => span);
  const out = {
    closedWeekdays: [...closed].sort(),
    needsBooking,
    lastTime: last ? Number(last[1]) * 60 + Number(last[2]) : null,
    window: spans.length && !best.includes("全天") ? [Math.min(...spans.map((x) => x[0])), Math.max(...spans.map((x) => x[1]))] : null,
    weekdayOnly: best.includes("工作日"),
  };
  insightCache.set(loc, out);
  return out;
}

/** 预留的用餐时段（没有具体餐厅，由行程引擎插入或用户添加） */
export const isMeal = (stop) => stop?.kind === "meal";

export function mealBlock(kind = "lunch") {
  const label = kind === "lunch" ? "午餐" : "晚餐";
  return { time: "", kind: "meal", activity: label, notes: "预留 1 小时用餐，在附近找家店", location: { name: `${label} · 附近觅食`, type: "food", duration_min: 60 } };
}

const windowRank = (stop) => {
  const w = isMeal(stop) ? null : insights(stopLocation(stop)).window;
  if (!w) return 1;
  return w[0] < 11 * 60 ? 0 : w[0] >= 17 * 60 ? 3 : w[0] >= 13 * 60 ? 2 : 1;
};

// ---------------------------------------------------------------- 一天 ----
/**
 * 每一段（含时间与通勤）的展开视图，用于渲染与校验。
 * 用餐时段没有坐标：到它的通勤记为 0（就近吃），它之后的一站从「上一个有坐标的地点」算通勤。
 */
export function daySegments(day) {
  const items = (day?.items || []).filter(Boolean);
  let lastGeo = null;
  return items.map((stop, i) => {
    const start = toMin(stop.time);
    const dur = stopDuration(stop);
    const prev = items[i - 1];
    let travel = null;
    if (prev) travel = isMeal(stop) ? { meters: 0, minutes: 0, mode: "walk", virtual: true } : estimateTravel(lastGeo || stopLocation(prev), stopLocation(stop));
    const prevEnd = prev ? stopEnd(prev) : null;
    const slack = travel && prevEnd != null && start != null ? start - prevEnd - travel.minutes : null;
    if (hasCoords(stopLocation(stop))) lastGeo = stopLocation(stop);
    return { stop, index: i, start, end: start == null ? null : start + dur, duration: dur, travel, slack };
  });
}

export function dayStats(day) {
  const segs = daySegments(day);
  const timed = segs.filter((s) => s.start != null);
  const travelMin = segs.reduce((n, s) => n + (s.travel?.minutes || 0), 0);
  const meters = segs.reduce((n, s) => n + (s.travel?.meters || 0), 0);
  const visitMin = segs.reduce((n, s) => n + s.duration, 0);
  const start = timed.length ? Math.min(...timed.map((s) => s.start)) : null;
  const end = timed.length ? Math.max(...timed.map((s) => s.end)) : null;
  return { count: segs.filter((s) => !isMeal(s.stop)).length, visitMin, travelMin, meters, start, end, spanMin: start == null ? 0 : end - start };
}

/**
 * 可行性检查：
 *  time-conflict  上一站结束 + 通勤 > 下一站开始
 *  closed         这天不开放（需要出发日期）
 *  last-time      超过末班时间
 *  overload       景点数超过节奏建议
 *  too-late       结束时间晚于 22:30
 *  too-long       一天跨度超过上限
 *  long-hop       相邻两点 > 12km
 *  no-meal        跨过饭点却没有餐饮
 *  booking        需要提前预约 / 订位
 *  best-time      和建议时段差得较远
 *  weekend        建议工作日去，却排在周末
 *  no-coords      缺少坐标，无法估算通勤 / 上图
 */
export function dayWarnings(day, paceKey = "balanced", { date = null } = {}) {
  const pace = PACES[paceKey] || PACES.balanced;
  const segs = daySegments(day);
  const out = [];
  const stats = dayStats(day);
  const wd = date ? (date.getDay() + 6) % 7 : null; // 0=周一

  segs.forEach((s) => {
    const id = s.stop.__stopId;
    const name = stopName(s.stop);
    if (s.slack != null && s.slack < -5 && !s.travel?.virtual) {
      out.push({ level: "warn", code: "time-conflict", stopId: id, message: `「${name}」赶不上：上一站结束后通勤约需 ${s.travel.minutes} 分钟，还差 ${Math.abs(Math.round(s.slack))} 分钟` });
    } else if (s.slack != null && s.slack < -5) {
      out.push({ level: "warn", code: "time-conflict", stopId: id, message: `「${name}」和上一站时间重叠了 ${Math.abs(Math.round(s.slack))} 分钟` });
    }
    if (isMeal(s.stop)) return;
    const info = insights(stopLocation(s.stop));
    if (wd != null && info.closedWeekdays.includes(wd)) {
      out.push({ level: "warn", code: "closed", stopId: id, message: `「${name}」周${WEEKDAY_CN[wd]}不开放，换一天或换个地方` });
    }
    if (info.lastTime != null && s.end != null && s.end > info.lastTime) {
      out.push({ level: "warn", code: "last-time", stopId: id, message: `「${name}」末班约 ${fromMin(info.lastTime)}，按现在的安排赶不上` });
    }
    if (info.needsBooking) out.push({ level: "info", code: "booking", stopId: id, message: `「${name}」需要提前预约 / 订位` });
    if (info.window && s.start != null && (s.start < info.window[0] - 60 || s.start > info.window[1])) {
      out.push({ level: "info", code: "best-time", stopId: id, message: `「${name}」建议${stopLocation(s.stop).best_time}去，现在排在 ${fromMin(s.start)}` });
    }
    if (info.weekdayOnly && wd != null && wd >= 5) out.push({ level: "info", code: "weekend", stopId: id, message: `「${name}」建议工作日去，周末可能部分不开放或人多` });
    if (s.travel && s.travel.meters > 12000) {
      out.push({ level: "info", code: "long-hop", stopId: id, message: `到「${name}」距离较远（约 ${(s.travel.meters / 1000).toFixed(1)} km），建议打车或调整顺序` });
    }
    if (!hasCoords(stopLocation(s.stop))) out.push({ level: "info", code: "no-coords", stopId: id, message: `「${name}」没有坐标，无法估算通勤` });
  });

  if (stats.count > pace.maxStops) out.push({ level: "warn", code: "overload", message: `今天安排了 ${stats.count} 个点，超过「${pace.label}」节奏建议的 ${pace.maxStops} 个` });
  if (stats.end != null && stats.end > 22.5 * 60) out.push({ level: "warn", code: "too-late", message: `预计 ${fromMin(stats.end)} 才结束，太晚了` });
  if (stats.spanMin > pace.maxSpanH * 60) out.push({ level: "warn", code: "too-long", message: `全天跨度约 ${(stats.spanMin / 60).toFixed(1)} 小时，容易疲劳` });
  const coversLunch = stats.start != null && stats.start <= MEAL.lunch[0] + 30 && stats.end >= MEAL.lunch[1];
  if (coversLunch && !segs.some((s) => isMeal(s.stop) || stopLocation(s.stop).type === "food")) {
    out.push({ level: "info", code: "no-meal", message: "这天跨过了饭点却没有安排吃饭，可以点「添加景点」或从推荐里加一家" });
  }
  return out;
}

// ------------------------------------------------------------ 自动排时间 ----
const MEAL = { lunch: [11 * 60 + 30, 13 * 60 + 30], dinner: [17 * 60 + 30, 19 * 60 + 30] };

/**
 * 按当前顺序重新排布一天的时间（与后端 planner.schedule 规则一致）：
 *  · 逐站「停留 + 通勤」，15 分钟取整
 *  · 锁定时间的景点（订好的餐厅 / 门票）原样保留
 *  · 有建议时段的景点在合理等待范围内等到时段开始（傍晚 / 夜间、最后一站可多等）
 *  · 用餐时段与餐饮点落在饭点窗口
 * 返回新的 day（不修改入参）。
 */
export function reflowDay(day, { startTime = "09:00" } = {}) {
  const items = (day.items || []).filter(Boolean).map((s) => ({ ...s }));
  let cursor = toMin(startTime) ?? 9 * 60;
  let lastGeo = null;
  let lunchUsed = false;
  let dinnerUsed = false;
  const last = items.length - 1;

  items.forEach((stop, i) => {
    const loc = stopLocation(stop);
    if (i > 0) {
      if (isMeal(stop)) cursor += 0;
      else {
        const t = estimateTravel(lastGeo || stopLocation(items[i - 1]), loc);
        cursor += t ? t.minutes : 15;
      }
    }
    if (stop.locked && toMin(stop.time) != null) {
      cursor = toMin(stop.time);
    } else {
      let win = null;
      if (isMeal(stop)) win = stop.activity === "晚餐" ? MEAL.dinner : MEAL.lunch;
      else if (insights(loc).window) win = insights(loc).window;
      else if (loc.type === "food") {
        if (!lunchUsed && cursor < MEAL.lunch[1] && cursor >= 9 * 60) {
          win = MEAL.lunch;
          lunchUsed = true;
        } else if (!dinnerUsed && cursor < MEAL.dinner[1] && cursor >= 15 * 60) {
          win = MEAL.dinner;
          dinnerUsed = true;
        }
      }
      if (win && cursor < win[0]) {
        // 剩下的都是傍晚 / 夜间景点：下午留给自由活动，到点再去
        const eveningTail = win[0] >= 17 * 60 && items.slice(i).filter((x) => !isMeal(x)).every((x) => (insights(stopLocation(x)).window?.[0] ?? 0) >= 17 * 60);
        const patient = i === last || win[0] >= 17 * 60 || isMeal(stop) || loc.type === "food";
        if (eveningTail || win[0] - cursor <= (patient ? 150 : 60)) cursor = win[0];
      }
      cursor = snap15(cursor);
      stop.time = fromMin(cursor);
    }
    cursor += stopDuration(stop);
    if (hasCoords(loc)) lastGeo = loc;
  });
  return { ...day, items };
}

// ------------------------------------------------------------- 路线优化 ----
/** 路径总长（米），open path */
function pathLength(points) {
  let d = 0;
  for (let i = 1; i < points.length; i++) d += haversine(points[i - 1], points[i]);
  return d;
}

function* permutations(arr) {
  if (arr.length <= 1) {
    yield arr;
    return;
  }
  for (let i = 0; i < arr.length; i++) {
    const rest = [...arr.slice(0, i), ...arr.slice(i + 1)];
    for (const p of permutations(rest)) yield [arr[i], ...p];
  }
}

/** 路程 + 时段倒挂惩罚（夜景排在白天景点前面代价很高），与后端 _order_day 一致 */
function routeCost(entries) {
  let inversions = 0;
  for (let i = 0; i < entries.length; i++) for (let j = i + 1; j < entries.length; j++) if (entries[i].rank > entries[j].rank) inversions++;
  return pathLength(entries.map((e) => e.loc)) + inversions * 15000;
}

function twoOpt(entries) {
  let best = entries.slice();
  let improved = true;
  while (improved) {
    improved = false;
    for (let i = 0; i < best.length - 1; i++) {
      for (let j = i + 1; j < best.length; j++) {
        const cand = [...best.slice(0, i), ...best.slice(i, j + 1).reverse(), ...best.slice(j + 1)];
        if (routeCost(cand) + 1 < routeCost(best)) {
          best = cand;
          improved = true;
        }
      }
    }
  }
  return best;
}

/** 按排好的时间把用餐时段放回合适的位置（饭点之前的最后一站之后） */
function placeMeals(items, meals, startTime) {
  if (!meals.length) return items;
  const timed = reflowDay({ items }, { startTime }).items;
  const out = [...items];
  meals.forEach((meal) => {
    const lo = meal.activity === "晚餐" ? MEAL.dinner[0] : MEAL.lunch[0];
    const idx = timed.findIndex((s) => toMin(s.time) >= lo);
    const at = idx < 0 ? out.length : Math.max(1, out.indexOf(items[idx]));
    out.splice(at, 0, meal);
  });
  return out;
}

/**
 * 重排当天景点使总通勤最短，同时尽量让「傍晚 / 夜间最佳」的景点排在后面。
 * 默认保持第一站不变；≤8 个点暴力枚举（最优），更多用 2-opt。
 * 用餐时段不参与排序，排完后按时间放回饭点位置；无坐标的点放在末尾。
 * 返回 { day, savedMeters }。
 */
export function optimizeDay(day, { lockFirst = true } = {}) {
  const items = (day.items || []).filter(Boolean);
  const meals = items.filter(isMeal);
  const geo = items.filter((s) => !isMeal(s) && hasCoords(stopLocation(s))).map((s) => ({ s, loc: stopLocation(s), rank: windowRank(s) }));
  const rest = items.filter((s) => !isMeal(s) && !hasCoords(stopLocation(s)));
  if (geo.length < 3) return { day, savedMeters: 0 };

  const head = lockFirst ? [geo[0]] : [];
  const movable = lockFirst ? geo.slice(1) : geo;
  const before = routeCost(geo);
  const beforeLen = pathLength(geo.map((g) => g.loc));

  let best;
  if (movable.length <= 8) {
    let min = Infinity;
    for (const perm of permutations(movable)) {
      const c = routeCost([...head, ...perm]);
      if (c < min) {
        min = c;
        best = perm;
      }
    }
  } else {
    best = twoOpt([...head, ...movable]).slice(head.length);
  }

  const ordered = [...head, ...best];
  if (routeCost(ordered) >= before - 50) return { day, savedMeters: 0 };
  const startTime = items.find((s) => toMin(s.time) != null)?.time || "09:30";
  const next = placeMeals([...ordered.map((g) => g.s), ...rest], meals, startTime);
  return { day: { ...day, items: next }, savedMeters: Math.max(0, Math.round((beforeLen - pathLength(ordered.map((g) => g.loc))) * 1.3)) };
}

// ------------------------------------------------------------------ 预算 ----
/** 人均消费档位 → 元。餐饮与景点/体验的档位含义不同，分开估价。 */
export const COST_LEVEL_YUAN = {
  food: { 免费: 0, 低: 35, 中等: 80, 较高: 150, 高: 300 },
  spot: { 免费: 0, 低: 20, 中等: 50, 较高: 100, 高: 200 },
};
const TRANSPORT_YUAN = { walk: 0, transit: 4, taxi: (m) => 14 + 2.6 * (m / 1000) };

/** 人均花费：景点/餐饮按 cost_level 估价，通勤按方式计费。 */
export function estimateCost(itinerary, { budget = 0 } = {}) {
  let food = 0;
  let spots = 0;
  let transport = 0;
  const perDay = [];
  (itinerary?.days || []).forEach((day) => {
    let dFood = 0;
    let dSpots = 0;
    let dTrans = 0;
    const segs = daySegments(day);
    segs.forEach((s) => {
      const loc = stopLocation(s.stop);
      const kind = loc.type === "food" ? "food" : "spot";
      const yuan = COST_LEVEL_YUAN[kind][loc.cost_level] ?? (kind === "food" ? 80 : 30);
      if (kind === "food") dFood += yuan;
      else dSpots += yuan;
      if (s.travel) {
        const rule = TRANSPORT_YUAN[s.travel.mode];
        dTrans += typeof rule === "function" ? rule(s.travel.meters) : rule;
      }
    });
    food += dFood;
    spots += dSpots;
    transport += dTrans;
    perDay.push({ food: Math.round(dFood), spots: Math.round(dSpots), transport: Math.round(dTrans), total: Math.round(dFood + dSpots + dTrans) });
  });
  const total = Math.round(food + spots + transport);
  const out = { per_person: total, food: Math.round(food), spots: Math.round(spots), transport: Math.round(transport), perDay, currency: "¥" };
  if (budget > 0) {
    out.budget = budget;
    out.diff = budget - total;
    out.within_budget = total <= budget;
    out.ratio = total / budget;
  }
  return out;
}

// ------------------------------------------------------------------ 天气 ----
/** WMO weather code → 文案 / 图标键 / 是否需要雨具 */
export function weatherInfo(code) {
  if (code === 0) return { label: "晴", icon: "sun", rain: false };
  if (code <= 2) return { label: "晴间多云", icon: "partly", rain: false };
  if (code === 3) return { label: "阴", icon: "cloud", rain: false };
  if (code === 45 || code === 48) return { label: "雾", icon: "cloud", rain: false };
  if (code >= 51 && code <= 57) return { label: "毛毛雨", icon: "rain", rain: true };
  if (code >= 61 && code <= 67) return { label: "雨", icon: "rain", rain: true };
  if (code >= 71 && code <= 77) return { label: "雪", icon: "snow", rain: false };
  if (code >= 80 && code <= 82) return { label: "阵雨", icon: "rain", rain: true };
  if (code >= 95) return { label: "雷雨", icon: "storm", rain: true };
  return { label: "多云", icon: "cloud", rain: false };
}

export function weatherAdvice(w) {
  if (!w) return "";
  const info = weatherInfo(w.code);
  if (info.rain || (w.rain_prob ?? 0) >= 60) return "有雨，建议把户外点换成室内（博物馆 / 商场 / 咖啡馆）并带伞";
  if ((w.tmax ?? 0) >= 33) return "天气炎热，户外安排放在早晚，中午留给室内";
  if ((w.tmin ?? 20) <= 5) return "天气偏冷，注意保暖，减少长时间户外停留";
  return "";
}

// -------------------------------------------------------------- 行前清单 ----
/**
 * 基于天数、天气、人格与行程内容生成行前清单。
 * 返回 [{ id, title, items: [{ id, text, why? }] }]
 */
export function buildPackingList({ days = 2, weather = [], persona = null, itinerary = null, hasBuddy = false } = {}) {
  const groups = [];
  const g = (id, title, items) => items.length && groups.push({ id, title, items: items.map(([key, text, why]) => ({ id: `${id}:${key}`, text, why })) });

  g("docs", "证件与支付", [
    ["id", "身份证 / 护照"],
    ["pay", "手机支付 + 一张备用银行卡"],
    ["tickets", "车票 / 酒店预订截图", "网络不好时也能出示"],
  ]);

  const digital = [
    ["power", "充电宝 + 充电线", "地图导航和拍照很耗电"],
    ["sim", "手机流量充足 / 离线地图"],
  ];
  const dims = persona?.dimensions || [];
  const recorder = dims[0]?.value === "D";
  if (recorder) digital.push(["cam", "相机 / 存储卡 / 备用电池", "你是记录表达型，出片是刚需"]);
  else digital.push(["earphone", "耳机", "沉浸感受型：走路时听点音乐 / 播客"]);
  g("digital", "电子设备", digital);

  const wear = [["shoes", "舒适的步行鞋", "预计每天步行较多"]];
  const tmax = Math.max(...weather.map((w) => w.tmax ?? -Infinity), -Infinity);
  const tmin = Math.min(...weather.map((w) => w.tmin ?? Infinity), Infinity);
  if (Number.isFinite(tmax) && tmax >= 30) wear.push(["sun", "防晒霜 / 帽子 / 墨镜", `最高 ${Math.round(tmax)}℃`]);
  if (Number.isFinite(tmin) && tmin <= 10) wear.push(["warm", "保暖外套", `最低 ${Math.round(tmin)}℃`]);
  if (weather.some((w) => weatherInfo(w.code).rain || (w.rain_prob ?? 0) >= 50)) wear.push(["rain", "折叠伞 / 雨衣", "行程期间有降雨"]);
  if (days >= 3) wear.push(["clothes", `换洗衣物 ×${Math.min(days - 1, 4)}`]);
  g("wear", "衣物与鞋", wear);

  const carry = [
    ["water", "随身水杯"],
    ["tissue", "纸巾 / 湿巾"],
    ["meds", "常用药（肠胃药、创可贴）"],
  ];
  const foodStops = (itinerary?.days || []).flatMap((d) => d.items || []).filter((s) => stopLocation(s).type === "food").length;
  if (foodStops >= 4) carry.push(["stomach", "肠胃药", `行程里有 ${foodStops} 顿美食，胃要争气`]);
  g("carry", "随身小物", carry);

  // 行程里真正需要预约 / 有末班时间 / 有闭馆日的地点（来自景点数据，不是泛泛提醒）
  const stops = (itinerary?.days || []).flatMap((d) => d.items || []).filter((s) => !isMeal(s));
  const plan = [];
  stops.forEach((s) => {
    const info = insights(stopLocation(s));
    const name = stopName(s);
    if (info.needsBooking) plan.push([`book-${name}`, `预约 / 订位：${name}`, stopLocation(s).tips || "热门时段容易约满"]);
    if (info.lastTime != null) plan.push([`last-${name}`, `记下末班时间：${name} ${fromMin(info.lastTime)}`]);
    if (info.closedWeekdays.length) plan.push([`closed-${name}`, `确认开放日：${name}（周${info.closedWeekdays.map((w) => WEEKDAY_CN[w]).join("、")}不开放）`]);
  });
  g("plan", "出发前确认", plan);

  const extra = [];
  if (persona?.mbti?.[2] === "P" && !plan.length) extra.push(["book", "热门场馆提前看看是否需要预约", "计划依赖型：提前确认更安心"]);
  if (hasBuddy) extra.push(["split", "和搭子约好集合点与 AA 规则"]);
  g("extra", "个性化提醒", extra);

  return groups;
}

// -------------------------------------------------------------- 文本导出 ----
export function dayDate(startDate, dayIdx) {
  if (!startDate) return null;
  const [y, m, d] = startDate.split("-").map(Number);
  if (!y) return null;
  const dt = new Date(y, m - 1, d + dayIdx);
  return dt;
}

const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
export function fmtDate(dt) {
  return dt ? `${dt.getMonth() + 1}月${dt.getDate()}日 ${WEEK[dt.getDay()]}` : "";
}
export const isoDate = (dt) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;

/** 适合粘贴到微信 / 备忘录的纯文本行程 */
export function toShareText(itinerary, { city = "", startDate = "", cost = null } = {}) {
  const lines = [`✈️ ${city}${itinerary.days.length}日行程 · 一拍迹合`];
  if (itinerary.summary) lines.push(itinerary.summary);
  if (cost?.per_person != null) lines.push(`💰 预计人均 ¥${cost.per_person}`);
  itinerary.days.forEach((day, i) => {
    const dt = dayDate(startDate, i);
    lines.push("", `【${day.title || `Day ${i + 1}`}】${dt ? " " + fmtDate(dt) : ""}`);
    (day.items || []).forEach((s) => {
      lines.push(`${s.time || "--:--"}  ${stopName(s)}${s.notes ? `（${s.notes}）` : ""}`);
    });
  });
  if (itinerary.tips?.length) lines.push("", "💡 小贴士", ...itinerary.tips.map((t) => `· ${t}`));
  return lines.join("\n");
}

// ---------------------------------------------------------------- 日历 ----
const icsEscape = (s) => String(s ?? "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");

function foldLine(line) {
  // RFC5545：每行 ≤75 八位字节；这里按字符粗略折行，避免中文被截断在多字节中间
  const out = [];
  let cur = "";
  let bytes = 0;
  for (const ch of line) {
    const b = new TextEncoder().encode(ch).length;
    if (bytes + b > 72) {
      out.push(cur);
      cur = " " + ch;
      bytes = 1 + b;
    } else {
      cur += ch;
      bytes += b;
    }
  }
  out.push(cur);
  return out.join("\r\n");
}

/** 生成 iCalendar（.ics），每个景点一个事件，可导入手机日历 */
export function buildIcs(itinerary, { startDate, city = "", uidSeed = "trip" } = {}) {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//一拍迹合//Trip Planner//ZH", "CALSCALE:GREGORIAN", `X-WR-CALNAME:${icsEscape(city + "旅行")}`, "X-WR-TIMEZONE:Asia/Shanghai"];
  (itinerary.days || []).forEach((day, di) => {
    const dt = dayDate(startDate, di);
    if (!dt) return;
    const ymd = isoDate(dt).replace(/-/g, "");
    (day.items || []).forEach((s, si) => {
      const start = toMin(s.time);
      if (start == null) return;
      const end = start + stopDuration(s);
      const local = (min) => `${ymd}T${String(Math.floor(min / 60) % 24).padStart(2, "0")}${String(min % 60).padStart(2, "0")}00`;
      const loc = stopLocation(s);
      const ev = [
        "BEGIN:VEVENT",
        `UID:${uidSeed}-${di}-${si}@yipaijihe`,
        `DTSTAMP:${stamp}Z`,
        `DTSTART;TZID=Asia/Shanghai:${local(start)}`,
        `DTEND;TZID=Asia/Shanghai:${local(end)}`,
        `SUMMARY:${icsEscape(stopName(s))}`,
      ];
      if (loc.address || loc.name) ev.push(`LOCATION:${icsEscape(loc.address || loc.name)}`);
      if (hasCoords(loc)) ev.push(`GEO:${Number(loc.lat).toFixed(6)};${Number(loc.lng).toFixed(6)}`);
      const desc = [s.activity, s.notes, loc.tips].filter(Boolean).join("\n");
      if (desc) ev.push(`DESCRIPTION:${icsEscape(desc)}`);
      ev.push("BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY", `DESCRIPTION:${icsEscape("30 分钟后：" + stopName(s))}`, "END:VALARM", "END:VEVENT");
      lines.push(...ev);
    });
  });
  lines.push("END:VCALENDAR");
  return lines.map(foldLine).join("\r\n") + "\r\n";
}

// ------------------------------------------------------------ 搭子兼容度 ----
const DIM_HINT = {
  0: ["记录表达型 × 沉浸感受型", "一个负责出片，一个负责感受——约好拍照时间，别互相催。"],
  1: ["精致风格型 × 本地烟火型", "餐厅可以一顿精致、一顿苍蝇馆子，各取所好。"],
  2: ["计划依赖型 × 灵感优先型", "把 60% 行程定死，留 40% 空白给临时起意。"],
  3: ["覆盖打卡型 × 深度停留型", "节奏容易冲突：分上午打卡、下午慢逛两段。"],
};

/** 两个人的旅行人格差异 → 同行建议 */
export function buddyCompatibility(mine, theirs) {
  if (!mine || !theirs || mine.length < 4 || theirs.length < 4) return null;
  const same = [];
  const diff = [];
  for (let i = 0; i < 4; i++) (mine[i] === theirs[i] ? same : diff).push(i);
  return {
    score: Math.round((same.length / 4) * 100),
    same: same.length,
    tips: diff.map((i) => DIM_HINT[i][1]),
    labels: diff.map((i) => DIM_HINT[i][0]),
  };
}
