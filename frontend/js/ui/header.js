import { h, mountInto } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { state, bus, storage, hasItinerary } from "../core/state.js";
import { STORAGE, STEPS } from "../core/config.js";
import { navigate, href } from "../core/router.js";
import { logout, claimAccount } from "../services/auth.js";
import { toast } from "./toast.js";
import { openModal, confirmDialog } from "./modal.js";
import { listTrips, applyTrip, deleteTrip } from "../services/trips.js";

const stepper = () => document.getElementById("stepper");
const actions = () => document.getElementById("topbar-actions");
let currentStep = 0;
let menuOpen = false;

// -------------------------------------------------------------- 主题 ----
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  storage.set(STORAGE.theme, t);
  bus.emit("theme:change", t);
  renderActions();
}
const toggleTheme = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");

// ------------------------------------------------------------ 步骤条 ----
/** 某一步现在是否可以直接跳过去 */
function reachable(step) {
  if (!state.persona) return step === 1;
  if (step <= 5) return true;
  return hasItinerary();
}

function renderStepper(step, chrome) {
  const nav = stepper();
  currentStep = step;
  nav.hidden = !step || chrome !== true;
  if (nav.hidden) return;
  const progress = (step - 1) / (STEPS.length - 1);
  const track = h(
    "ol",
    { class: "stepper-track", style: { "--progress": progress } },
    STEPS.map((s) => {
      const st = s.n < step ? "done" : s.n === step ? "current" : "todo";
      const can = s.n !== step && reachable(s.n);
      return h(
        "li",
        null,
        h(
          "button",
          {
            class: "step-dot",
            type: "button",
            "data-state": st,
            "aria-current": st === "current" ? "step" : null,
            "aria-label": `第 ${s.n} 步 ${s.label}`,
            disabled: !can && st !== "current",
            onclick: () => can && navigate(s.route),
          },
          st === "done" ? icon("check", "step-check") : String(s.n),
          h("span", { class: "step-label" }, s.label)
        )
      );
    })
  );
  const label = STEPS[step - 1];
  mountInto(nav, track, h("div", { class: "step-compact" }, h("b", null, `${String(step).padStart(2, "0")}`), ` / 0${STEPS.length} · ${label.label}`));
}

// ------------------------------------------------------------ 用户菜单 ----
async function showPersona() {
  const { personaCard } = await import("../pages/persona.js");
  if (!state.persona) return toast("请先完成旅行人格测试", { error: true });
  openModal({ title: "我的旅行人格", width: 620, body: personaCard(state.persona, { modal: true }) });
}

export async function openTripsModal() {
  const body = h("div", { class: "trips-list" }, h("div", { class: "skeleton", style: { height: "72px" } }));
  const m = openModal({ title: "我的行程", width: 620, body });
  try {
    const trips = await listTrips();
    const render = (list) => {
      if (!list.length) {
        return mountInto(body, h("div", { class: "empty" }, h("h3", null, "还没有保存的行程"), h("p", null, "生成路线后点「保存行程」，之后就能在这里继续编辑。")));
      }
      mountInto(
        body,
        list.map((t) =>
          h(
            "article",
            { class: "trip-row" },
            h(
              "div",
              { class: "trip-row-main" },
              h("h3", null, t.title || `${t.city}${t.days}日游`),
              h(
                "p",
                { class: "faint" },
                `${t.city} · ${t.days} 天 · ${t.stops} 个地点`,
                t.start_date ? ` · ${t.start_date} 出发` : "",
                t.shared ? h("span", { class: "tag tag--sea", style: { marginLeft: "8px" } }, "已分享") : null
              )
            ),
            h(
              "div",
              { class: "trip-row-actions" },
              h(
                "button",
                {
                  class: "btn btn--sm btn--ink",
                  type: "button",
                  onclick: async () => {
                    const { trip } = await import("../core/api.js").then((a) => a.api.get(`/api/trips/${t.id}`));
                    applyTrip(trip);
                    m.close();
                    navigate("itinerary");
                    toast("已打开行程，可继续编辑");
                  },
                },
                "继续编辑"
              ),
              h(
                "button",
                {
                  class: "icon-btn",
                  type: "button",
                  "aria-label": `删除 ${t.title}`,
                  onclick: async () => {
                    if (!(await confirmDialog({ title: "删除这个行程？", message: "删除后无法恢复；已生成的分享链接也会失效。", confirmText: "删除", danger: true }))) return;
                    await deleteTrip(t.id);
                    if (state.tripId === t.id) state.tripId = null;
                    toast("已删除");
                    render(list.filter((x) => x.id !== t.id));
                  },
                },
                icon("trash")
              )
            )
          )
        )
      );
    };
    render(trips);
  } catch (e) {
    mountInto(body, h("p", { class: "muted" }, e.message));
  }
}

/** 游客转正：设置用户名和密码，行程与人格结果保留 */
export function openClaimModal() {
  const err = h("p", { class: "form-error", role: "alert" });
  const user = h("input", { class: "input", id: "claim-user", placeholder: "3–20 个字符", autocomplete: "username", autofocus: true });
  const pass = h("input", { class: "input", id: "claim-pass", type: "password", placeholder: "6–20 个字符", autocomplete: "new-password" });
  const submit = h("button", { class: "btn btn--primary", type: "submit" }, "保存账号");
  const form = h(
    "form",
    { class: "auth-form", onsubmit: async (e) => {
      e.preventDefault();
      submit.classList.add("is-loading");
      try {
        await claimAccount(user.value.trim(), pass.value);
        m.close();
        toast("账号已设置，换台设备登录也能找回行程");
      } catch (ex) {
        err.textContent = ex.message;
        err.classList.add("is-visible");
      } finally {
        submit.classList.remove("is-loading");
      }
    } },
    h("p", { class: "muted" }, "游客数据只能在这台设备上找回。设置用户名和密码后，人格结果和行程都会保留。"),
    err,
    h("div", { class: "field" }, h("label", { for: "claim-user" }, "用户名"), user),
    h("div", { class: "field" }, h("label", { for: "claim-pass" }, "密码"), pass),
    submit
  );
  const m = openModal({ title: "设置账号", width: 440, body: form });
}

function userMenu() {
  const p = state.persona;
  const pop = h(
    "div",
    { class: "menu-pop", role: "menu" },
    h("div", { class: "menu-head" }, h("div", { class: "code" }, p?.mbti || "----"), h("div", { class: "name" }, p ? `${p.personality?.name || ""} · ${state.user.username}` : `${state.user.username} · 尚未测试人格`)),
    state.user.is_guest && item("lock", "设置账号（换设备也能找回）", openClaimModal),
    p && item("compass", "查看旅行人格", showPersona),
    item("refresh", p ? "重新测试人格" : "开始人格测试", () => {
      state.persona = null;
      state.mbtiAnswers = {};
      navigate("persona");
    }),
    item("history", "我的行程", openTripsModal),
    item("logout", "退出登录", async () => {
      await logout();
      navigate("login");
      toast("已退出登录");
    }, true)
  );
  function item(ic, text, fn, danger) {
    return h("button", { class: ["menu-item", danger && "danger"], role: "menuitem", type: "button", onclick: () => ((menuOpen = false), renderActions(), fn()) }, icon(ic), text);
  }
  return pop;
}

function renderActions() {
  const dark = document.documentElement.dataset.theme === "dark";
  const themeBtn = h("button", { class: "icon-btn", type: "button", "aria-label": dark ? "切换到浅色" : "切换到深色", onclick: toggleTheme }, icon(dark ? "sun" : "moon"));

  if (!state.user) return mountInto(actions(), themeBtn);

  const trigger = h(
    "button",
    { class: "btn btn--quiet btn--sm user-btn", type: "button", "aria-haspopup": "menu", "aria-expanded": String(menuOpen), onclick: (e) => ((e.stopPropagation(), (menuOpen = !menuOpen), renderActions())) },
    h("span", { class: "avatar" }, state.user.username[0].toUpperCase()),
    h("span", { class: "user-name" }, state.user.username),
    state.user.is_guest && h("span", { class: "tag tag--sun guest-tag" }, "游客"),
    icon("chevron-down")
  );
  mountInto(actions(), themeBtn, h("div", { class: "menu" }, trigger, menuOpen && userMenu()));
}

export function initHeader() {
  renderActions();
  bus.on("route:change", ({ step, chrome }) => {
    menuOpen = false;
    renderStepper(step, chrome);
    renderActions();
  });
  bus.on("auth:change", () => ((menuOpen = false), renderActions()));
  bus.on("persona:change", () => renderActions());
  // 行程生成后，步骤 6/7 变为可跳转
  bus.on("itinerary:ready", () => renderStepper(currentStep, true));
  document.addEventListener("click", (e) => {
    if (menuOpen && !e.target.closest(".menu")) ((menuOpen = false), renderActions());
  });
  document.addEventListener("keydown", (e) => e.key === "Escape" && menuOpen && ((menuOpen = false), renderActions()));
}

export { href };
