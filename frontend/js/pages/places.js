import { h, mountInto, debounce } from "../core/dom.js";
import { icon, typeIcon, typeLabel, TYPE_LABEL } from "../core/icons.js";
import { api } from "../core/api.js";
import { state, persistDraft } from "../core/state.js";
import { TYPE_HEX } from "../core/config.js";
import { createMapView, searchPlaces } from "../services/map.js";
import { hasCoords, PACES } from "../services/planner.js";
import { isPersonalityMatch, styleProfile } from "../services/persona-fit.js";
import { generateItinerary } from "../services/itinerary.js";
import { toast, toastError } from "../ui/toast.js";

const VALID_TYPES = Object.keys(TYPE_LABEL);
const douyinUrl = (name) => `https://www.douyin.com/search/${encodeURIComponent(`${name} 攻略`)}`;

function normalize(loc, i, source) {
  return {
    ...loc,
    id: loc.id || `${source}_${i + 1}_${Math.random().toString(36).slice(2, 6)}`,
    type: VALID_TYPES.includes(loc.type) ? loc.type : "landmark",
    keywords: loc.keywords || loc.tags || [],
    reason: loc.reason || loc.video_hint || loc.description || loc.tips || "",
    source: loc.source || source,
  };
}

export default {
  title: () => "地点筛选",

  mount(root, ctx) {
    const page = h("section", { class: "page page--wide" });
    root.append(page);

    let map = null;
    let query = "";
    const typeFilter = new Set();
    let personaOnly = false;
    let hoverId = null;

    const list = h("div", { class: "place-list", role: "list" });
    const echo = h("p", { class: "echo" });
    const bar = h("div", { class: "action-bar" });
    const mapEl = h("div", { class: "map-canvas", role: "region", "aria-label": "景点地图" });
    const filters = h("div", { class: "place-filters" });
    const notice = h("div", { class: "place-notice" });

    const places = () => state.places;
    const hasMbti = () => !!state.persona?.mbti;
    const visible = () =>
      places().filter((p) => {
        if (query && !`${p.name}${(p.keywords || []).join("")}${p.reason}`.toLowerCase().includes(query.toLowerCase())) return false;
        if (typeFilter.size && !typeFilter.has(p.type)) return false;
        if (personaOnly && hasMbti() && !isPersonalityMatch(p)) return false;
        return true;
      });
    const selected = () => places().filter((p) => state.selectedIds.has(p.id));

    // ------------------------------------------------ 数据加载 ----
    async function load() {
      if (places().length) return;
      mountInto(list, Array.from({ length: 5 }, () => h("div", { class: "skeleton", style: { height: "104px" } })));
      notice.replaceChildren(h("div", { class: "banner banner--info" }, icon("sparkles"), `AI 正在联网搜索「${state.trip.city}${state.trip.days}日游」里常被提到的景点，并按你的旅行人格筛选…（约 10–30 秒）`));
      let got = [];
      try {
        const data = await api.post("/api/locations/default-recommend", { profile: styleProfile(), city: state.trip.city, days: state.trip.days }, { signal: ctx.signal });
        got = (data.attractions || []).map((l, i) => normalize(l, i, data.source === "web_search" ? "ai_discover" : "builtin"));
        if (data.fallback) toast(data.fallback_message || "联网搜索暂不可用，已使用本地精选景点库", { error: true });
      } catch (e) {
        if (e.name === "AbortError") return;
      }
      if (!got.length) {
        try {
          const data = await api.get(`/api/locations/list?city=${encodeURIComponent(state.trip.city)}`, { signal: ctx.signal });
          got = (data.locations || []).map((l, i) => normalize(l, i, "builtin"));
        } catch (e) {
          if (e.name === "AbortError") return;
          toastError(e);
        }
      }
      state.places = got;
      state.selectedIds = new Set(got.filter((p) => hasCoords(p) && isPersonalityMatch(p)).map((p) => p.id));
      persistDraft();
    }

    /** 视频里提取的地点常缺坐标 → 用地图 POI 搜索自动补全 */
    async function geocodeMissing() {
      const missing = places().filter((p) => !hasCoords(p) && !p._geocoded);
      if (!missing.length) return;
      let fixed = 0;
      for (const p of missing) {
        if (!ctx.alive()) return;
        p._geocoded = true;
        const [hit] = await searchPlaces(p.name, state.trip.city);
        if (hit && Number.isFinite(hit.lng)) {
          Object.assign(p, { lat: hit.lat, lng: hit.lng, address: p.address || hit.address });
          state.selectedIds.add(p.id);
          fixed++;
        }
      }
      if (fixed && ctx.alive()) {
        toast(`已自动定位 ${fixed} 个缺少坐标的地点`);
        persistDraft();
        renderAll();
      }
    }

    // ------------------------------------------------ 渲染 ----
    const numberOf = (p) => places().indexOf(p) + 1;

    function markerList() {
      return places().filter(hasCoords).map((p) => {
        const on = state.selectedIds.has(p.id);
        return { id: p.id, lng: p.lng, lat: p.lat, label: String(numberOf(p)), color: on ? TYPE_HEX[p.type] || "#8a7f71" : "#a89f92", dim: !on, title: p.name };
      });
    }

    function card(p, i) {
      const on = state.selectedIds.has(p.id);
      const ok = hasCoords(p);
      const match = !hasMbti() || isPersonalityMatch(p);
      const cb = h("input", { type: "checkbox", checked: on, disabled: !ok, "aria-label": `选择 ${p.name}`, onchange: (e) => toggle(p.id, e.target.checked) });
      return h(
        "article",
        { class: ["place rise", on && "is-on", !match && "is-off-style"], role: "listitem", "data-id": p.id, "data-type": p.type, style: { "--i": Math.min(i, 6) },
          onmouseenter: () => map?.focus(p.id), onmouseleave: () => (hoverId = null) },
        h("label", { class: "place-main" },
          h("span", { class: "check" }, cb, h("span", { class: "check-box" }, icon("check"))),
          h("span", { class: "place-num mono", style: { background: TYPE_HEX[p.type] } }, numberOf(p)),
          h("span", { class: "place-body" },
            h("span", { class: "place-name" }, p.name,
              h("span", { class: "type-badge", "data-type": p.type }, icon(typeIcon(p.type)), typeLabel(p.type)),
              !match && h("span", { class: "tag" }, "风格不太搭"),
              !ok && h("span", { class: "tag tag--seal" }, "缺少坐标"),
              p.source === "video" && h("span", { class: "tag tag--sea" }, "来自视频"),
              p.source === "custom" && h("span", { class: "tag tag--sun" }, "自己添加")),
            p.reason && h("span", { class: "place-reason" }, p.reason),
            h("span", { class: "place-meta" },
              (p.keywords || []).slice(0, 3).map((k) => h("span", { class: "tag" }, k)),
              p.duration_min && h("span", { class: "faint" }, icon("clock"), `约 ${p.duration_min} 分钟`),
              h("a", { class: "place-link", href: p.douyin_search_url || douyinUrl(p.name), target: "_blank", rel: "noopener noreferrer", onclick: (e) => e.stopPropagation() }, "在抖音看看", icon("external"))))
        )
      );
    }

    function renderFilters() {
      const counts = {};
      places().forEach((p) => (counts[p.type] = (counts[p.type] || 0) + 1));
      const shown = visible();
      const allOn = shown.length && shown.every((p) => state.selectedIds.has(p.id) || !hasCoords(p));
      mountInto(
        filters,
        h("div", { class: "filter-search" }, icon("list"), h("input", { class: "input", type: "search", placeholder: "搜索景点、关键词…", "aria-label": "搜索地点", value: query, oninput: debounce((e) => ((query = e.target.value.trim()), renderList()), 160) })),
        h("div", { class: "chip-row" },
          Object.keys(counts).map((t) => h("button", { class: "chip", type: "button", "aria-pressed": String(typeFilter.has(t)), onclick: () => (typeFilter.has(t) ? typeFilter.delete(t) : typeFilter.add(t), renderAll()) }, icon(typeIcon(t)), `${typeLabel(t)} ${counts[t]}`))),
        h("div", { class: "filter-row" },
          hasMbti() && h("label", { class: "switch" }, h("input", { type: "checkbox", checked: personaOnly, onchange: (e) => {
            personaOnly = e.target.checked;
            if (personaOnly) places().forEach((p) => !isPersonalityMatch(p) && state.selectedIds.delete(p.id));
            renderAll();
          } }), h("span", { class: "switch-track" }), "只看符合我风格的"),
          h("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: () => {
            shown.forEach((p) => hasCoords(p) && (allOn ? state.selectedIds.delete(p.id) : state.selectedIds.add(p.id)));
            renderAll();
          } }, allOn ? "取消全选" : "全选当前")
        )
      );
    }

    function renderList() {
      const v = visible();
      mountInto(list, v.length ? v.map(card) : h("div", { class: "empty" }, h("h3", null, places().length ? "没有符合筛选条件的地点" : "还没有地点"), h("p", null, places().length ? "换个关键词或取消筛选试试" : "可以在下方手动添加想去的地方")));
    }

    function renderBar() {
      const n = selected().length;
      const d = state.trip.days;
      const pace = PACES[state.trip.pace] || PACES.balanced;
      const lo = d * 3;
      const hi = d * pace.maxStops;
      const tip = n === 0 ? "至少选一个地点" : n < lo ? `${d} 天建议选 ${lo}–${hi} 个，目前偏少，行程会比较空` : n > hi ? `${d} 天建议 ${lo}–${hi} 个，目前偏多，可能排不下` : "数量刚刚好 👌";
      const busy = bar.dataset.busy === "1";
      mountInto(
        bar,
        h("div", { class: "action-sum" }, h("b", null, `已选 ${n} 个地点`), h("span", { class: n && (n < lo || n > hi) ? "warn" : "faint" }, tip)),
        h("button", { class: ["btn btn--primary btn--lg", busy && "is-loading"], type: "button", disabled: !n || busy, onclick: generate }, busy ? "AI 正在排路线…" : "AI 生成旅行计划", !busy && icon("arrow-right", "i-arrow"))
      );
    }

    function renderEcho() {
      const p = state.persona;
      if (!p?.mbti) return echo.replaceChildren();
      const pr = styleProfile();
      const tags = [pr.di_label, pr.rl_label, pr.ps_label, pr.cd_label].join(" · ");
      const hasVideo = places().some((x) => x.source === "video");
      mountInto(echo, icon("compass"), h("span", null, "根据你的旅行人格 ", h("b", null, `${p.personality?.name}（${p.mbti}）`), `，${hasVideo ? "从视频中提取" : "为你准备"}了 `, h("b", null, places().length), " 个地点，已按「", tags, "」预选。"));
    }

    function refreshMap() {
      map?.setMarkers(markerList());
    }
    function renderAll() {
      renderEcho();
      renderFilters();
      renderList();
      renderBar();
      refreshMap();
    }

    function toggle(id, on) {
      on ? state.selectedIds.add(id) : state.selectedIds.delete(id);
      persistDraft();
      list.querySelector(`[data-id="${CSS.escape(id)}"]`)?.classList.toggle("is-on", on);
      renderBar();
      refreshMap();
      renderFilters();
    }

    async function generate() {
      bar.dataset.busy = "1";
      renderBar();
      try {
        await generateItinerary(selected());
        if (ctx.alive()) ctx.navigate("itinerary");
        else toast("行程已生成，点击步骤条进入路线编辑");
      } catch (e) {
        toastError(e);
      } finally {
        bar.dataset.busy = "0";
        if (ctx.alive()) renderBar();
      }
    }

    // ------------------------------------------------ 手动添加 ----
    function addBox() {
      const input = h("input", { class: "input", type: "text", placeholder: "想去的地方，如「武康大楼」「%Arabica」", "aria-label": "添加地点", autocomplete: "off" });
      const results = h("ul", { class: "suggest", role: "listbox" });
      const run = debounce(async () => {
        const q = input.value.trim();
        if (!q) return results.replaceChildren();
        const hits = await searchPlaces(q, state.trip.city);
        mountInto(
          results,
          hits.length
            ? hits.map((hit) => h("li", null, h("button", { type: "button", role: "option", onclick: () => {
                const p = normalize({ ...hit, source: "custom", reason: hit.address, keywords: [hit.category] }, places().length, "custom");
                state.places = [...places(), p];
                state.selectedIds.add(p.id);
                persistDraft();
                input.value = "";
                results.replaceChildren();
                toast(`已添加「${p.name}」`);
                renderAll();
                map?.focus(p.id);
              } }, h("b", null, hit.name), h("small", null, hit.address))))
            : h("li", { class: "suggest-empty" }, "没有搜到结果（地图服务不可用时无法搜索）")
        );
      }, 300);
      input.addEventListener("input", run);
      return h("div", { class: "add-place" }, h("label", { class: "field-label" }, icon("plus"), "手动添加想去的地点"), input, results);
    }

    // ------------------------------------------------ 组装 ----
    mountInto(
      page,
      h("a", { class: "back-link", href: "#/videos" }, icon("arrow-left"), "返回上一步"),
      h("div", { class: "page-head" }, h("p", { class: "eyebrow" }, "STEP 05 · 地点筛选"), h("h1", null, "挑出", h("span", { class: "mark" }, "真正想去"), "的地方"), echo),
      notice,
      h("div", { class: "split places-split" },
        h("div", { class: "places-col" }, filters, list, addBox()),
        h("div", { class: "sticky" }, h("div", { class: "map-frame" }, mapEl))),
      bar
    );

    (async () => {
      await load();
      if (!ctx.alive()) return;
      notice.replaceChildren();
      map = await createMapView(mapEl, {
        onMarkerClick: (id) => {
          const el = list.querySelector(`[data-id="${CSS.escape(id)}"]`);
          if (!el) return;
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.add("flash");
          setTimeout(() => el.classList.remove("flash"), 1200);
        },
      });
      if (!ctx.alive()) return map.destroy();
      ctx.disposer.add(() => map?.destroy());
      renderAll();
      map.fit();
      geocodeMissing();
    })();
    renderAll();
  },
};
