import { api } from "../core/api.js";
import { state, bus, persistDraft } from "../core/state.js";
import { styleProfile } from "./persona-fit.js";
import { estimateCost, hasCoords } from "./planner.js";

const cloneJson = (v) => JSON.parse(JSON.stringify(v));
let seq = 0;
export const newStopId = (hint = "stop") => `${hint}-${Date.now().toString(36)}-${(seq++).toString(36)}`;

/** 保证每个景点都有稳定 id、完整 location，便于拖拽 / 反馈 / 地图联动 */
export function normalizeItinerary(itin, catalog = []) {
  const it = cloneJson(itin);
  const byId = Object.fromEntries(catalog.filter((l) => l?.id).map((l) => [l.id, l]));
  it.days = (it.days || []).map((day, di) => ({
    ...day,
    title: day.title || `Day ${di + 1}`,
    items: (day.items || []).filter(Boolean).map((item) => {
      const loc = { ...(byId[item.location_id] || {}), ...(item.location || {}) };
      return { ...item, location: loc, __stopId: item.__stopId || newStopId(item.location_id || "s") };
    }),
  }));
  it.recommendations = (it.recommendations || []).map((r) => ({ ...r, location: { ...(byId[r.location_id] || {}), ...(r.location || {}) } }));
  return it;
}

export function requestBody() {
  const t = state.trip;
  return {
    destination: t.city,
    days: t.days,
    pace: t.pace,
    start_date: t.startDate || "",
    companions: state.hasBuddy ? "和搭子一起" : "独自旅行",
    companion_type: state.hasBuddy ? "friends" : "solo",
    budget: t.budget ? `人均 ¥${t.budget}` : "",
    budget_amount: t.budget || 0,
    profile: styleProfile(),
  };
}

/** 基于用户在「地点筛选」里勾选的地点生成行程 */
export async function generateItinerary(selected) {
  const body = requestBody();
  const usable = selected.filter(hasCoords);
  if (usable.length) body.preview_locations = usable;
  else body.selected_locations = [...state.selectedIds];
  const data = await api.post("/api/itinerary/generate", body);
  const itin = applyGenerated(data, usable);
  await seedRecommendations(itin);
  persistDraft();
  bus.emit("itinerary:ready");
  return itin;
}

const slim = (p) => ({ name: p.name, lat: p.lat, lng: p.lng, type: p.type, category: p.category, description: p.description, address: p.address, duration_min: p.duration_min, cost_level: p.cost_level, best_time: p.best_time, tips: p.tips });

/**
 * 推荐池：后端没给（或给得少）时，用「用户没勾选的地点」+「本地精选库」补足到 8 个，
 * 餐饮优先——这样「换一个」「补一顿饭」永远有东西可用。
 */
export async function seedRecommendations(itin, want = 8) {
  const out = [...(itin.recommendations || [])];
  if (out.length >= want) return out;
  const taken = new Set([...itin.days.flatMap((d) => d.items.map((s) => s.location?.name)), ...out.map((r) => r.location?.name || r.activity)]);
  let pool = state.places.filter((p) => !state.selectedIds.has(p.id) && hasCoords(p));
  try {
    const { locations } = await api.get(`/api/locations/list?city=${encodeURIComponent(state.trip.city)}`);
    pool = [...pool, ...(locations || [])];
  } catch {
    /* 本地库拿不到就只用未勾选的 */
  }
  pool.sort((a, b) => (b.type === "food") - (a.type === "food"));
  for (const p of pool) {
    if (out.length >= want) break;
    if (!p.name || taken.has(p.name)) continue;
    taken.add(p.name);
    out.push({ location_id: p.id, activity: `探索${p.name}`, reason: p.reason || p.description || p.tips || "", location: slim(p) });
  }
  itin.recommendations = out;
  return out;
}

export function applyGenerated(data, extraCatalog = []) {
  const catalog = [...(data.locations_used || []), ...extraCatalog];
  state.itinerary = normalizeItinerary(data.itinerary, catalog);
  state.itinerary.engine = data.engine || "local";
  state.tripId = null;
  state.feedbacks = {};
  state.weather = [];
  state.cost = estimateCost(state.itinerary, { budget: state.trip.budget });
  persistDraft();
  bus.emit("itinerary:ready");
  return state.itinerary;
}
