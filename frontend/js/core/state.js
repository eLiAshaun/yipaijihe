import { STORAGE } from "./config.js";
import { debounce } from "./dom.js";

/** 轻量事件总线 */
const listeners = new Map();
export const bus = {
  on(evt, fn) {
    if (!listeners.has(evt)) listeners.set(evt, new Set());
    listeners.get(evt).add(fn);
    return () => listeners.get(evt)?.delete(fn);
  },
  emit(evt, payload) {
    listeners.get(evt)?.forEach((fn) => {
      try {
        fn(payload);
      } catch (e) {
        console.error(`[bus:${evt}]`, e);
      }
    });
  },
};

const safe = {
  get(k) {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set(k, v) {
    try {
      localStorage.setItem(k, v);
    } catch {}
  },
  del(k) {
    try {
      localStorage.removeItem(k);
    } catch {}
  },
};
export const storage = safe;

export const freshTrip = () => ({ city: "上海", days: 2, budget: 500, startDate: "", pace: "" });

/** 全局应用状态（单一来源）。页面只读写这里，不互相引用。 */
export const state = {
  token: safe.get(STORAGE.token) || safe.get(STORAGE.legacyToken),
  user: null, // { id, username, ... }
  persona: null, // /api/mbti/calculate 的结果
  mbtiAnswers: {},

  trip: freshTrip(),
  hasBuddy: false,
  buddy: null, // { id, username, mbti_type }
  buddyPlans: [],

  videoLinks: [],
  videoAnalysis: null,
  places: [], // 地点池（视频提取 / 联网搜索 / 本地库）
  discovery: null, // 联网搜索的元信息：{ mode, sources, city }
  selectedIds: new Set(),
  placesSource: "",

  itinerary: null,
  tripId: null, // 已保存到服务端的行程 id
  cost: null,
  weather: [], // 逐日天气
  feedbacks: {}, // stopId -> like | must | dislike
  transport: "transfer",

  chatHistory: [],
};

/** 是否存在可继续的行程 */
export const hasItinerary = () => !!state.itinerary?.days?.length;

export function setToken(token) {
  state.token = token || null;
  if (token) {
    safe.set(STORAGE.token, token);
    safe.del(STORAGE.legacyToken);
  } else {
    safe.del(STORAGE.token);
    safe.del(STORAGE.legacyToken);
  }
}

/** 重置「一次旅行」相关状态，保留登录与人格 */
export function resetTrip() {
  state.trip = freshTrip();
  state.hasBuddy = false;
  state.buddy = null;
  state.buddyPlans = [];
  state.videoLinks = [];
  state.videoAnalysis = null;
  state.places = [];
  state.discovery = null;
  state.selectedIds = new Set();
  state.placesSource = "";
  state.itinerary = null;
  state.tripId = null;
  state.cost = null;
  state.weather = [];
  state.feedbacks = {};
  state.chatHistory = [];
  clearDraft();
}

export function resetAll() {
  resetTrip();
  state.user = null;
  state.persona = null;
  state.mbtiAnswers = {};
}

// ------------------------------------------------------------------ 草稿 ----
/** 浏览器刷新 / 误关页面不丢进度：行程与选项自动落到 localStorage */
const DRAFT_KEYS = ["trip", "hasBuddy", "buddy", "places", "placesSource", "discovery", "itinerary", "tripId", "feedbacks", "transport"];

export const persistDraft = debounce(() => {
  if (!state.user) return;
  const draft = { uid: state.user.id, savedAt: Date.now(), selectedIds: [...state.selectedIds] };
  DRAFT_KEYS.forEach((k) => (draft[k] = state[k]));
  safe.set(STORAGE.draft, JSON.stringify(draft));
}, 400);

export function loadDraft() {
  const raw = safe.get(STORAGE.draft);
  if (!raw) return null;
  try {
    const d = JSON.parse(raw);
    if (!state.user || d.uid !== state.user.id) return null;
    return d;
  } catch {
    return null;
  }
}

export function applyDraft(d) {
  DRAFT_KEYS.forEach((k) => d[k] !== undefined && (state[k] = d[k]));
  state.selectedIds = new Set(d.selectedIds || []);
}

export function clearDraft() {
  persistDraft.cancel();
  safe.del(STORAGE.draft);
}
