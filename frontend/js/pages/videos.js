import { h, mountInto } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { api } from "../core/api.js";
import { state, persistDraft } from "../core/state.js";
import { toast, toastError } from "../ui/toast.js";
import { nudgeChat, addMessage, closeChatIfIdle } from "../ui/chat.js";

/** 从粘贴的分享文案里抽出 URL（抖音分享文案常夹杂中文标点） */
export function extractUrls(text) {
  const found = text.match(/https?:\/\/[^\s，。！？、；：“”‘’"'）)\]}>]+/gi) || [];
  return [...new Set(found.map((u) => u.replace(/[，。！？、；：“”‘’）\]}>]+$/, "")).filter((u) => u.length > 10))];
}

const host = (u) => {
  try {
    return new URL(u).host.replace(/^www\./, "");
  } catch {
    return u.slice(0, 24);
  }
};

const STAGES = [
  ["下载视频", 0, 30],
  ["语音转写", 30, 62],
  ["提取景点", 62, 100],
];

export default {
  title: () => "精选视频",

  mount(root, ctx) {
    const page = h("section", { class: "page page--tight" });
    root.append(page);

    const ta = h("textarea", { class: "textarea video-ta", id: "f-links", rows: 5, placeholder: "粘贴抖音分享链接或整段分享文案，每行一个\n例如：https://v.douyin.com/xxxxx", "aria-label": "视频链接", value: state.videoLinks.join("\n") });
    const chips = h("div", { class: "chip-row link-chips", "aria-live": "polite" });
    const analyzeBtn = h("button", { class: "btn btn--primary btn--lg", type: "button", onclick: analyze }, icon("sparkles"), "AI 分析视频");
    const skipBtn = h("button", { class: "btn btn--ghost", type: "button", onclick: () => ((state.videoAnalysis = null), (state.places = []), (state.selectedIds = new Set()), ctx.navigate("places")) }, "跳过，直接由 AI 推荐地点");
    const stage = h("div", { class: "analysis", hidden: true });
    const results = h("div", { class: "analysis-results" });

    const updateChips = () => {
      const urls = extractUrls(ta.value);
      mountInto(chips, urls.length ? [h("span", { class: "faint", style: { fontSize: "var(--fs-sm)" } }, `识别到 ${urls.length} 条链接：`), urls.map((u) => h("span", { class: "chip" }, icon("link"), host(u)))] : h("span", { class: "hint" }, "还没有识别到链接"));
    };
    ta.addEventListener("input", updateChips);

    async function analyze() {
      const urls = extractUrls(ta.value);
      if (!urls.length) return toast("没找到有效链接，请检查粘贴内容", { error: true });
      const bad = urls.filter((u) => !/(^|\.)(douyin|iesdouyin|amemv)\.com$/i.test(host(u)));
      if (bad.length) return toast(`目前只支持抖音视频链接，请移除：${host(bad[0])}`, { error: true });
      ta.value = urls.join("\n");
      state.videoLinks = urls;
      updateChips();
      analyzeBtn.disabled = true;
      results.replaceChildren();

      const bar = h("div", { class: "progress" }, h("i"));
      const label = h("p", { class: "analysis-label" });
      const list = h("ol", { class: "stages" }, STAGES.map(([t]) => h("li", null, h("span", { class: "stage-dot" }), t)));
      mountInto(stage, h("div", { class: "analysis-top" }, h("b", null, `并行处理 ${urls.length} 个视频`), h("span", { class: "mono faint" }, "预计 1–2 分钟")), bar, list, label);
      stage.hidden = false;

      nudgeChat(`正在并行分析 ${urls.length} 个视频，需要 1–2 分钟 ⏳\n\n等的时候可以问我：\n- 这座城市的美食推荐\n- 适合拍照的地方\n- 当地天气和穿搭建议`);

      let pct = 3;
      const t0 = Date.now();
      const tick = setInterval(() => {
        pct = Math.min(pct + Math.random() * 5, 90);
        bar.firstChild.style.setProperty("--v", `${pct}%`);
        bar.firstChild.style.width = `${pct}%`;
        const cur = STAGES.findIndex(([, a, b]) => pct >= a && pct < b);
        [...list.children].forEach((li, i) => li.classList.toggle("on", i === cur) || li.classList.toggle("done", i < cur));
        label.textContent = `${STAGES[Math.max(cur, 0)][0]}中… 已用 ${Math.round((Date.now() - t0) / 1000)} 秒`;
      }, 900);

      try {
        const p = state.persona;
        const data = await api.post("/api/video/analyze", { urls, personality: p ? { mbti: p.mbti, personality_name: p.personality?.name } : {} });
        clearInterval(tick);
        state.videoAnalysis = data;
        state.places = (data.locations || []).map((l, i) => ({ ...l, id: l.id || `video_${i + 1}`, source: l.source || "video", keywords: l.keywords || [], reason: l.reason || "" }));
        state.selectedIds = new Set(state.places.map((l) => l.id));
        persistDraft();
        if (state.places.length) addMessage("ai", `分析完成 ✅ 成功处理 ${data.success_count || 0}/${urls.length} 个视频，提取了 ${state.places.length} 个景点。\n\n可以继续问我这些景点的问题，或点击「进入地点筛选」。`);
        setTimeout(closeChatIfIdle, 2500);
        if (!ctx.alive()) return;
        bar.firstChild.style.width = "100%";
        list.querySelectorAll("li").forEach((li) => (li.className = "done"));
        label.textContent = `分析完成，用时 ${Math.round((Date.now() - t0) / 1000)} 秒`;
        setTimeout(() => ctx.alive() && ((stage.hidden = true), renderResults()), 700);
      } catch (e) {
        clearInterval(tick);
        if (ctx.alive()) ((stage.hidden = true), toastError(e));
      } finally {
        if (ctx.alive()) analyzeBtn.disabled = false;
      }
    }

    function renderResults() {
      const data = state.videoAnalysis;
      if (!data) return results.replaceChildren();
      const places = state.places;
      const rm = (id) => {
        state.places = state.places.filter((p) => p.id !== id);
        state.selectedIds.delete(id);
        persistDraft();
        renderResults();
      };
      mountInto(
        results,
        data.fallback && h("div", { class: "banner banner--warn" }, icon("alert"), "语音转写暂不可用，以下为演示数据"),
        data.errors?.length
          ? h("details", { class: "banner banner--err" }, h("summary", null, icon("alert"), `${data.errors.length} 个视频处理失败`), h("ul", null, data.errors.map((e) => h("li", null, h("code", null, host(e.url || String(e))), "：", e.error || "处理失败"))), h("p", { class: "hint" }, "请确认是有效的抖音链接，且视频未被删除或设为私密"))
          : null,
        data.transcripts?.length ? h("p", { class: "faint", style: { fontSize: "var(--fs-sm)" } }, `已成功解析：${data.transcripts.map((t) => t.title || host(t.url)).join("；")}`) : null,
        places.length
          ? [
              h("div", { class: "results-head" }, h("h2", null, `提取到 ${places.length} 个地点`), h("span", { class: "faint" }, "不需要的可以先移除，下一步还能勾选")),
              h("div", { class: "found-grid" }, places.map((l, i) => h("article", { class: "found rise", style: { "--i": Math.min(i, 8) } },
                h("button", { class: "icon-btn icon-btn--sm found-x", type: "button", "aria-label": `移除 ${l.name}`, onclick: () => rm(l.id) }, icon("x")),
                h("h3", null, icon("pin"), l.name),
                l.reason && h("p", { class: "muted" }, l.reason),
                h("div", { class: "chip-row" }, (l.keywords || []).slice(0, 4).map((k) => h("span", { class: "tag" }, k)))
              ))),
              h("div", { class: "page-foot" }, h("button", { class: "btn btn--primary btn--lg", type: "button", onclick: () => ctx.navigate("places") }, "进入地点筛选", icon("arrow-right", "i-arrow")))
            ]
          : h("div", { class: "empty" }, h("h3", null, "没有提取到有效地点"), h("p", null, "换几个介绍具体景点、店铺的视频试试，或直接跳过让 AI 推荐。"))
      );
    }

    mountInto(
      page,
      h("a", { class: "back-link", href: "#/buddy" }, icon("arrow-left"), "返回上一步"),
      h("div", { class: "page-head" }, h("p", { class: "eyebrow" }, "STEP 04 · 精选视频"), h("h1", null, "收藏了哪些", h("span", { class: "mark" }, "旅行视频"), "？"), h("p", null, "粘贴抖音收藏里的视频链接，AI 会听视频、认地点，把它们变成可以上地图的景点。")),
      h("div", { class: "video-box card card--pad" }, h("label", { class: "field-label", for: "f-links" }, "视频链接（支持整段分享文案）"), ta, chips, h("div", { class: "video-actions" }, analyzeBtn, skipBtn)),
      stage,
      results
    );
    updateChips();
    if (state.videoAnalysis) renderResults();
  },
};
