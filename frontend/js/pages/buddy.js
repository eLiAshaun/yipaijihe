import { h, mountInto } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { api } from "../core/api.js";
import { state, bus } from "../core/state.js";
import { buddyCompatibility } from "../services/planner.js";
import { toast, toastError } from "../ui/toast.js";

export default {
  title: () => "旅行搭子",

  mount(root, ctx) {
    const page = h("section", { class: "page page--narrow" });
    root.append(page);
    const panel = h("div", { class: "buddy-panel" });

    const choose = (yes) => {
      state.hasBuddy = yes;
      if (!yes) {
        state.buddy = null;
        state.buddyPlans = [];
        return ctx.navigate("videos");
      }
      cards.forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.k === "yes")));
      renderPanel();
      panel.querySelector("input")?.focus();
    };

    const card = (k, ic, title, desc) =>
      h("button", { class: "choice", type: "button", "data-k": k, "aria-pressed": String(k === "yes" && state.hasBuddy), onclick: () => choose(k === "yes") }, h("span", { class: "choice-ico" }, icon(ic)), h("b", null, title), h("small", null, desc));
    const cards = [card("yes", "users", "有搭子", "一起规划，看看 TA 分享的行程"), card("no", "user", "独自出发", "一个人的旅行也很精彩")];

    function renderPanel() {
      if (!state.hasBuddy) return mountInto(panel);
      const input = h("input", { class: "input", id: "f-buddy", placeholder: "输入搭子的用户名或 UID", value: state.buddy?.username || "", "aria-label": "搭子的用户名或 UID", onkeydown: (e) => e.key === "Enter" && sync() });
      const btn = h("button", { class: "btn btn--ink", type: "button", onclick: sync }, "同步搭子");
      const out = h("div", { class: "buddy-out" });

      async function sync() {
        const id = input.value.trim();
        if (!id) return toast("请输入搭子的用户名或 UID", { error: true });
        btn.classList.add("is-loading");
        try {
          const data = await api.post("/api/buddy/sync", { buddy_identifier: id });
          state.buddy = data.buddy;
          state.buddyPlans = data.shared_plans || [];
          bus.emit("buddy:change");
          renderResult();
        } catch (e) {
          mountInto(out, h("p", { class: "form-error is-visible", role: "alert" }, e.message));
        } finally {
          btn.classList.remove("is-loading");
        }
      }

      function renderResult() {
        const b = state.buddy;
        const compat = buddyCompatibility(state.persona?.mbti, b.mbti_type);
        const plans = state.buddyPlans;
        mountInto(
          out,
          h(
            "div",
            { class: "buddy-card card card--pad" },
            h("div", { class: "buddy-who" }, h("span", { class: "avatar avatar--lg" }, b.username[0].toUpperCase()), h("div", null, h("b", null, b.username), h("small", { class: "mono faint" }, b.mbti_type ? `旅行人格 ${b.mbti_type}` : "TA 还没有测试旅行人格"))),
            compat
              ? h(
                  "div",
                  { class: "compat" },
                  h("div", { class: "compat-score", style: { "--p": compat.score } }, h("b", null, compat.score), h("small", null, "契合度")),
                  h("div", null, compat.tips.length ? [h("p", { class: "field-label" }, "同行小建议"), h("ul", { class: "compat-tips" }, compat.tips.map((t) => h("li", null, t)))] : h("p", null, "你们的旅行风格几乎一致，默契满分。"))
                )
              : null
          ),
          plans.length
            ? h(
                "div",
                { class: "buddy-plans" },
                h("p", { class: "field-label" }, `${b.username} 分享的行程`),
                plans.map((pl) =>
                  h(
                    "div",
                    { class: "plan-row card" },
                    h("div", null, h("b", null, pl.title || `${pl.city}${pl.days}日游`), h("small", { class: "faint" }, `${pl.city} · ${pl.days} 天 · ${pl.stops} 个地点`)),
                    h("button", { class: "btn btn--sm btn--quiet", type: "button", onclick: async () => {
                      try {
                        const { trip } = await api.get(`/api/trips/shared/${pl.share_token}`);
                        state.itinerary = trip.itinerary;
                        state.tripId = null;
                        state.trip = { ...state.trip, city: trip.city, days: trip.days, budget: trip.budget || state.trip.budget, startDate: trip.start_date || state.trip.startDate };
                        bus.emit("itinerary:ready");
                        toast(`已采纳 ${b.username} 的行程，可以在此基础上继续修改`);
                        ctx.navigate("itinerary");
                      } catch (e) {
                        toastError(e);
                      }
                    } }, "以此为基础")
                  )
                )
              )
            : h("p", { class: "hint" }, `${b.username} 还没有分享行程。让 TA 在「导出」页点「分享链接」，就能在这里看到。`),
          h("div", { class: "page-foot" }, h("button", { class: "btn btn--primary btn--lg", type: "button", onclick: () => ctx.navigate("videos") }, "继续：精选视频", icon("arrow-right", "i-arrow")))
        );
      }

      mountInto(panel, h("div", { class: "buddy-form card card--pad" }, h("label", { class: "field-label", for: "f-buddy" }, "搭子的用户名或 UID"), h("div", { class: "buddy-input" }, input, btn), h("p", { class: "hint" }, "搭子需要也注册了一拍迹合。只有 TA 主动开启分享的行程才会被看到。")), out);
      if (state.buddy) renderResult();
    }

    mountInto(
      page,
      h("a", { class: "back-link", href: "#/plan" }, icon("arrow-left"), "返回上一步"),
      h("div", { class: "page-head page-head--center" }, h("p", { class: "eyebrow" }, "STEP 03 · 旅行搭子"), h("h1", null, "这次旅行，", h("span", { class: "mark" }, "有搭子"), "吗？"), h("p", null, "有搭子就对比一下旅行人格，也能直接借用 TA 分享的行程。")),
      h("div", { class: "choices" }, cards),
      panel
    );
    renderPanel();
  },
};
