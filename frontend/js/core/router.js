import { state, bus, hasItinerary } from "./state.js";
import { mountInto, createDisposer } from "./dom.js";

/**
 * hash 路由：#/persona  #/plan  #/s/<token> …
 * 每个页面模块 default 导出 { title, mount(root, ctx) → cleanup? }
 */
export const ROUTES = {
  login: { path: "/login", public: true, chrome: false, load: () => import("../pages/auth.js") },
  register: { path: "/register", public: true, chrome: false, load: () => import("../pages/auth.js") },
  persona: { path: "/persona", step: 1, load: () => import("../pages/persona.js") },
  plan: { path: "/plan", step: 2, load: () => import("../pages/plan.js") },
  buddy: { path: "/buddy", step: 3, load: () => import("../pages/buddy.js") },
  videos: { path: "/videos", step: 4, load: () => import("../pages/videos.js") },
  places: { path: "/places", step: 5, load: () => import("../pages/places.js") },
  itinerary: { path: "/itinerary", step: 6, needs: "itinerary", load: () => import("../pages/itinerary.js") },
  export: { path: "/export", step: 7, needs: "itinerary", load: () => import("../pages/export.js") },
  shared: { path: "/s/:token", public: true, chrome: "minimal", load: () => import("../pages/shared.js") },
};

let current = null; // { name, params, cleanup, ctrl }
let navToken = 0;

export function parseHash(hash = location.hash) {
  const path = hash.replace(/^#/, "") || "/";
  for (const [name, r] of Object.entries(ROUTES)) {
    const keys = [];
    const re = new RegExp("^" + r.path.replace(/:([a-z]+)/gi, (_, k) => (keys.push(k), "([^/]+)")) + "/?$");
    const m = re.exec(path);
    if (m) return { name, params: Object.fromEntries(keys.map((k, i) => [k, decodeURIComponent(m[i + 1])])) };
  }
  return null;
}

export function href(name, params = {}) {
  const r = ROUTES[name];
  return "#" + r.path.replace(/:([a-z]+)/gi, (_, k) => encodeURIComponent(params[k]));
}

export function navigate(name, params, { replace = false } = {}) {
  const target = href(name, params);
  if (location.hash === target) return render();
  if (replace) location.replace(target);
  else location.hash = target;
}

export const currentRoute = () => current && { name: current.name, params: current.params };

function resolveGuard(route) {
  const def = ROUTES[route.name];
  if (!def.public && !state.user) return "login";
  if (state.user && (route.name === "login" || route.name === "register")) return state.persona ? "plan" : "persona";
  if (state.user && route.name !== "persona" && !def.public && !state.persona) return "persona";
  if (def.needs === "itinerary" && !hasItinerary()) return state.places.length ? "places" : "plan";
  return null;
}

async function render() {
  const token = ++navToken;
  let route = parseHash() || { name: state.user ? "plan" : "login", params: {} };
  const redirect = resolveGuard(route);
  if (redirect) {
    route = { name: redirect, params: {} };
    history.replaceState(null, "", href(redirect));
  }

  const def = ROUTES[route.name];
  const root = document.getElementById("view");

  let mod;
  try {
    mod = (await def.load()).default;
  } catch (e) {
    console.error("route load failed", e);
    mountInto(root, Object.assign(document.createElement("p"), { className: "page", textContent: "页面加载失败，请刷新重试" }));
    return;
  }
  if (token !== navToken) return; // 期间又发生了新的导航

  const swap = () => {
    current?.cleanup?.();
    current?.ctrl.abort();
    const ctrl = new AbortController();
    const disposer = createDisposer();
    const ctx = { name: route.name, params: route.params, signal: ctrl.signal, disposer, navigate, alive: () => current?.ctrl === ctrl };
    current = { name: route.name, params: route.params, ctrl, cleanup: null };
    mountInto(root);
    const page = mod.mount(root, ctx);
    current.cleanup = () => {
      disposer.dispose();
      if (typeof page === "function") page();
    };
    document.title = `${mod.title ? mod.title(ctx) + " · " : ""}一拍迹合`;
    document.documentElement.dataset.route = route.name;
    document.documentElement.dataset.chrome = String(def.chrome ?? true);
    window.scrollTo(0, 0);
    bus.emit("route:change", { name: route.name, step: def.step || 0, chrome: def.chrome ?? true, params: route.params });
    root.focus({ preventScroll: true });
  };

  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches && current) {
    document.startViewTransition(swap);
  } else swap();
}

export function startRouter() {
  addEventListener("hashchange", render);
  return render();
}
