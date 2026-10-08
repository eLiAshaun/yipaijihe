import { api } from "../core/api.js";
import { state, persistDraft, bus } from "../core/state.js";
import { debounce } from "../core/dom.js";
import { estimateCost } from "./planner.js";

const metaOf = () => ({
  pace: state.trip.pace,
  feedbacks: state.feedbacks,
  hasBuddy: state.hasBuddy,
  buddy: state.buddy ? { id: state.buddy.id, username: state.buddy.username, mbti_type: state.buddy.mbti_type } : null,
});

/** 「上海2日游 · 10月2日出发」—— 比 AI 摘要更适合作为列表标题 */
export function defaultTitle() {
  const [y, m, d] = (state.trip.startDate || "").split("-").map(Number);
  return `${state.trip.city}${state.itinerary.days.length}日游${y ? ` · ${m}月${d}日出发` : ""}`;
}

const payload = () => ({
  city: state.trip.city,
  days: state.itinerary.days.length,
  budget_amount: state.trip.budget || 0,
  start_date: state.trip.startDate || "",
  companions: state.hasBuddy ? "和搭子一起" : "独自旅行",
  itinerary: state.itinerary,
  meta: metaOf(),
});

export const listTrips = () => api.get("/api/trips").then((r) => r.trips);

/** 把服务端行程装载到全局状态，供行程页继续编辑 */
export function applyTrip(trip) {
  state.tripId = trip.id;
  state.itinerary = trip.itinerary;
  state.trip = { city: trip.city, days: trip.days, budget: trip.budget || 0, startDate: trip.start_date || "", pace: trip.meta?.pace || "" };
  state.feedbacks = trip.meta?.feedbacks || {};
  state.hasBuddy = !!trip.meta?.hasBuddy;
  state.buddy = trip.meta?.buddy || null;
  state.cost = estimateCost(state.itinerary, { budget: state.trip.budget });
  state.weather = [];
  bus.emit("trip:loaded", trip);
}

/** 保存当前行程：已有 id 则更新，否则新建 */
export async function saveTrip() {
  if (!state.user || !state.itinerary) return null;
  const body = payload();
  const { trip } = state.tripId ? await api.put(`/api/trips/${state.tripId}`, body) : await api.post("/api/trips", { ...body, title: defaultTitle() });
  state.tripId = trip.id;
  persistDraft();
  bus.emit("trip:saved", trip);
  return trip;
}

/** 已保存过的行程，编辑后静默同步到云端（防抖） */
export const autosave = debounce(async () => {
  persistDraft();
  if (state.tripId && state.user && state.itinerary) {
    try {
      await api.put(`/api/trips/${state.tripId}`, payload());
      bus.emit("trip:autosaved");
    } catch (e) {
      console.warn("autosave failed", e.message);
    }
  }
}, 1200);

export const deleteTrip = (id) => api.del(`/api/trips/${id}`);

export async function shareTrip(id = state.tripId) {
  if (!id) {
    const t = await saveTrip();
    id = t.id;
  }
  const { token } = await api.post(`/api/trips/${id}/share`);
  return `${location.origin}${location.pathname}#/s/${token}`;
}

export const unshareTrip = (id) => api.del(`/api/trips/${id}/share`);
