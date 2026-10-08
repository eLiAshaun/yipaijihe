import { api } from "../core/api.js";
import { state, setToken, resetAll, bus, clearDraft } from "../core/state.js";

function applyProfile(profile) {
  state.user = { id: profile.id, username: profile.username, created_at: profile.created_at, is_guest: !!profile.is_guest };
  state.persona = profile.mbti_result?.mbti ? profile.mbti_result : null;
  state.trips = profile.travel_history;
  bus.emit("auth:change", state.user);
}

/** 刷新页面后用本地 token 恢复会话；失败则清掉失效 token */
export async function restoreSession() {
  if (!state.token) return false;
  try {
    const { profile } = await api.get("/api/auth/profile");
    applyProfile(profile);
    return true;
  } catch (e) {
    if (e.status === 401 || e.status === 0) {
      if (e.status === 401) setToken(null);
    }
    return false;
  }
}

async function enter(data) {
  setToken(data.token);
  const { profile } = await api.get("/api/auth/profile");
  applyProfile(profile);
  return profile;
}

export async function login(username, password) {
  return enter(await api.post("/api/auth/login", { username, password }));
}

export async function register(username, password) {
  return enter(await api.post("/api/auth/register", { username, password }));
}

/** 游客模式：不注册直接开始，之后可以「设置账号」转为正式账号 */
export async function guest() {
  return enter(await api.post("/api/auth/guest"));
}

export async function claimAccount(username, password) {
  const { user } = await api.put("/api/auth/account", { username, password });
  state.user = { ...state.user, username: user.username, is_guest: false };
  bus.emit("auth:change", state.user);
  return user;
}

export async function logout({ remote = true } = {}) {
  if (remote && state.token) await api.post("/api/auth/logout").catch(() => {});
  setToken(null);
  clearDraft();
  resetAll();
  bus.emit("auth:change", null);
}

export async function savePersona(result) {
  state.persona = result;
  if (state.user) await api.put("/api/auth/mbti", { mbti_type: result.mbti, mbti_result: result }).catch(() => {});
  bus.emit("persona:change", result);
}
