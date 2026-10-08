import { h, mountInto, clamp } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { state, hasItinerary } from "../core/state.js";
import { personaThumb } from "../core/config.js";
import { PACES, paceFromPersona, fmtDate, isoDate } from "../services/planner.js";
import { listTrips, applyTrip } from "../services/trips.js";
import { api } from "../core/api.js";
import { openTripsModal } from "../ui/header.js";
import { getConfig } from "../services/config.js";
import { toast } from "../ui/toast.js";

const BUDGET_PRESETS = [300, 500, 1000, 2000, 3500];
const today = () => isoDate(new Date());

export default {
  title: () => "行程规划",

  mount(root, ctx) {
    const t = state.trip;
    if (!t.pace) t.pace = paceFromPersona(state.persona);
    const recommended = paceFromPersona(state.persona);

    const page = h("section", { class: "page page--tight" });
    root.append(page);

    // ------ 继续之前的行程 ------
    const resume = h("div", { class: "resume" });
    if (hasItinerary()) {
      resume.append(
        h(
          "div",
          { class: "resume-card card" },
          h("div", null, h("p", { class: "eyebrow" }, "未完成的行程"), h("h3", null, state.itinerary.summary || `${t.city}${state.itinerary.days.length}日游`), h("p", { class: "faint" }, `${state.itinerary.days.length} 天 · 自动保存于本机`)),
          h("button", { class: "btn btn--ink btn--sm", type: "button", onclick: () => ctx.navigate("itinerary") }, "继续编辑", icon("arrow-right", "i-arrow"))
        )
      );
    }
    if (state.user) {
      listTrips()
        .then((trips) => {
          if (!ctx.alive() || !trips.length) return;
          const latest = trips.slice(0, 2);
          resume.append(
            h(
              "div",
              { class: "resume-list" },
              h("div", { class: "resume-head" }, h("span", { class: "eyebrow" }, "我的行程"), trips.length > 2 && h("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: openTripsModal }, `查看全部 ${trips.length} 个`)),
              latest.map((tr) =>
                h(
                  "button",
                  { class: "trip-chip", type: "button", onclick: async () => {
                    try {
                      applyTrip((await api.get(`/api/trips/${tr.id}`)).trip);
                      ctx.navigate("itinerary");
                    } catch (e) {
                      toast(e.message, { error: true });
                    }
                  } },
                  h("b", null, tr.title || `${tr.city}${tr.days}日游`),
                  h("small", null, `${tr.days} 天 · ${tr.stops} 个地点${tr.start_date ? " · " + tr.start_date : ""}`),
                  icon("arrow-right", "i-arrow")
                )
              )
            )
          );
        })
        .catch(() => {});
    }

    // ------ 人格提示 ------
    const p = state.persona?.personality;
    const personaStrip = p
      ? h(
          "div",
          { class: "persona-strip" },
          h("img", { src: personaThumb(p.image), alt: "", width: 56, height: 56 }),
          h("div", null, h("small", { class: "mono faint" }, "你的旅行人格"), h("b", null, `${p.emoji} ${p.name}`), h("span", { class: "faint" }, p.subtitle)),
          h("a", { class: "btn btn--ghost btn--sm", href: "#/persona" }, "重测")
        )
      : null;

    // ------ 表单控件 ------
    const summary = h("p", { class: "plan-summary", "aria-live": "polite" });

    const date = h("input", { class: "input", id: "f-date", type: "date", min: today(), value: t.startDate || "", onchange: (e) => ((t.startDate = e.target.value), refresh()) });

    const daysNum = h("output", { class: "days-num", "aria-live": "polite" });
    const setDays = (v) => ((t.days = clamp(Math.round(v) || 1, 1, 14)), refresh());
    const daysCtl = h(
      "div",
      { class: "days-ctl", role: "group", "aria-label": "旅行天数" },
      h("button", { class: "icon-btn round", type: "button", "aria-label": "减少一天", onclick: () => setDays(t.days - 1) }, icon("minus")),
      daysNum,
      h("button", { class: "icon-btn round", type: "button", "aria-label": "增加一天", onclick: () => setDays(t.days + 1) }, icon("plus"))
    );

    const paceHint = h("p", { class: "hint" });
    const paceSeg = h(
      "div",
      { class: "segmented", role: "group", "aria-label": "旅行节奏" },
      Object.values(PACES).map((pc) =>
        h("button", { type: "button", "data-pace": pc.key, "aria-pressed": String(t.pace === pc.key), onclick: () => ((t.pace = pc.key), refresh()) }, pc.label, pc.key === recommended && h("small", { class: "rec-dot", title: "根据你的旅行人格推荐" }, "荐"))
      )
    );

    const budgetNum = h("input", { class: "input budget-num", id: "f-budget", type: "number", min: 0, max: 100000, step: 50, inputmode: "numeric", value: t.budget, "aria-label": "人均预算（元）", oninput: (e) => ((t.budget = clamp(parseInt(e.target.value, 10) || 0, 0, 100000)), refresh(true)), onblur: refresh });
    const budgetRange = h("input", { class: "slider", type: "range", min: 0, max: 5000, step: 50, "aria-label": "人均预算滑块", oninput: (e) => ((t.budget = Number(e.target.value)), refresh()) });
    const presets = h("div", { class: "chip-row" }, BUDGET_PRESETS.map((v) => h("button", { class: "chip", type: "button", "data-v": v, onclick: () => ((t.budget = v), refresh()) }, `¥${v}`)));

    function refresh(keepInput) {
      daysNum.textContent = t.days;
      paceSeg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.pace === t.pace)));
      paceHint.textContent = PACES[t.pace].hint;
      if (!keepInput) budgetNum.value = t.budget;
      budgetRange.value = Math.min(t.budget, 5000);
      budgetRange.style.setProperty("--v", `${(Math.min(t.budget, 5000) / 5000) * 100}%`);
      presets.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(Number(c.dataset.v) === t.budget)));
      const per = t.budget && t.days ? Math.round(t.budget / t.days) : 0;
      const [y, m, d] = (t.startDate || "").split("-").map(Number);
      const range = y ? `${fmtDate(new Date(y, m - 1, d))} 出发` : "日期待定";
      summary.replaceChildren(h("b", null, `${t.city} · ${t.days} 天`), ` · ${range} · ${PACES[t.pace].label}节奏 · 人均 ¥${t.budget}`, per ? h("span", { class: "faint" }, `（约 ¥${per}/天）`) : null);
    }

    const field = (label, ...kids) => h("div", { class: "field" }, h("span", { class: "field-label" }, label), ...kids);

    // ------ 目的地：有内置景点库的城市 + 开启联网搜索后的任意城市 ------
    const cityBox = h("div", { class: "city-box" }, h("span", { class: "chip is-active" }, icon("pin"), t.city));
    const setCity = (name) => {
      name = (name || "").trim();
      if (!name || name === t.city) return;
      t.city = name;
      // 换城市后，之前城市的地点池和视频分析结果不再适用
      state.places = [];
      state.selectedIds = new Set();
      state.videoAnalysis = null;
      state.discovery = null;
      renderCities();
      refresh();
    };
    let cfg = null;
    function renderCities() {
      if (!cfg) return;
      const known = cfg.cities.map((c) => c.name);
      const chips = [...new Set([...known, t.city])].map((name) => {
        const c = cfg.cities.find((x) => x.name === name);
        return h("button", { class: "chip", type: "button", "aria-pressed": String(name === t.city), onclick: () => setCity(name) }, icon("pin"), name, c ? h("small", { class: "faint" }, ` ${c.places} 个地点`) : null);
      });
      const other = cfg.web_search
        ? [h("form", { class: "city-other", onsubmit: (e) => (e.preventDefault(), setCity(e.target.city.value)) }, h("input", { class: "input", name: "city", placeholder: "其他城市，如 杭州", "aria-label": "其他城市" }), h("button", { class: "btn btn--quiet btn--sm", type: "submit" }, "去这里")),
           h("p", { class: "hint" }, "已开启联网搜索：任何城市都会搜索最新攻略来推荐地点。")]
        : h("p", { class: "hint" }, "目前内置了上海的景点库。想规划其他城市，在 .env 里填上 DEEPSEEK_API_KEY 开启联网搜索。");
      mountInto(cityBox, h("div", { class: "chip-row" }, chips), other);
    }
    getConfig().then((c) => ((cfg = c), ctx.alive() && renderCities())).catch(() => {});

    const form = h(
      "div",
      { class: "plan-form ticket", style: { "--stub": "100%" } },
      h("div", { class: "plan-grid" },
        field("目的地", cityBox),
        h("div", { class: "field" }, h("label", { for: "f-date" }, "出发日期", h("span", { class: "faint" }, "（选填）")), date, h("span", { class: "hint" }, "填写后可查看逐日天气，并导出到手机日历")),
        field("旅行天数", daysCtl),
        field("旅行节奏", paceSeg, paceHint),
        h("div", { class: "field span-2" },
          h("label", { for: "f-budget" }, "人均预算（整趟）"),
          h("div", { class: "budget-row" }, h("span", { class: "budget-prefix" }, "¥"), budgetNum, budgetRange),
          presets,
          h("span", { class: "hint" }, "预算会随你编辑路线实时对比，超出时会提醒。")
        )
      ),
      h("hr", { class: "perf" }),
      h("div", { class: "plan-foot" }, summary, h("button", { class: "btn btn--primary btn--lg", type: "button", onclick: () => ctx.navigate("buddy") }, "下一步：旅行搭子", icon("arrow-right", "i-arrow")))
    );

    mountInto(
      page,
      h("div", { class: "page-head" }, h("p", { class: "eyebrow" }, "STEP 02 · 行程规划"), h("h1", null, "这一趟，", h("span", { class: "mark" }, "怎么走"), "？"), h("p", null, "几个关键信息，决定后面路线排得松还是紧。")),
      resume,
      personaStrip,
      form
    );
    refresh();
  },
};
