import { h, mountInto } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { api } from "../core/api.js";
import { state, persistDraft } from "../core/state.js";
import { getConfig } from "../services/config.js";
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
const isDouyin = (u) => /(^|\.)(douyin|iesdouyin|amemv)\.com$/i.test(host(u));
/** 去掉链接后剩下的文字（小红书笔记、攻略、地名清单…） */
const textOnly = (text) => text.replace(/https?:\/\/\S+/g, " ").replace(/\s+/g, " ").trim();
const hasWords = (text) => (text.match(/[一-龥A-Za-z]/g) || []).length >= 2;

const SOURCE = { video: ["film", "来自视频"], inspiration: ["file", "来自文字"] };

export default {
  title: () => "灵感素材",

  mount(root, ctx) {
    const page = h("section", { class: "page page--tight" });
    root.append(page);
    let caps = { asr: false, llm: false };

    const ta = h("textarea", {
      class: "textarea video-ta",
      id: "f-links",
      rows: 6,
      placeholder: "粘贴任何旅行灵感：\n· 抖音分享链接 / 整段分享文案\n· 小红书笔记、公众号攻略、朋友发的清单\n例如：早上去武康大楼拍照，下午安福路喝咖啡，晚上外滩看夜景",
      "aria-label": "旅行灵感素材",
      value: state.videoLinks.join("\n"),
    });
    const chips = h("div", { class: "chip-row link-chips", "aria-live": "polite" });
    const capNote = h("p", { class: "hint cap-note" });
    const analyzeBtn = h("button", { class: "btn btn--primary btn--lg", type: "button", onclick: analyze }, icon("sparkles"), "识别地点");
    const skipBtn = h("button", { class: "btn btn--ghost", type: "button", onclick: () => ((state.videoAnalysis = null), (state.places = []), (state.selectedIds = new Set()), ctx.navigate("places")) }, "跳过，直接挑地点");
    const stage = h("div", { class: "analysis", hidden: true });
    const results = h("div", { class: "analysis-results" });

    const updateChips = () => {
      const urls = extractUrls(ta.value);
      const words = textOnly(ta.value);
      const parts = [];
      if (urls.length) parts.push(h("span", { class: "faint", style: { fontSize: "var(--fs-sm)" } }, `${urls.length} 条链接：`), urls.map((u) => h("span", { class: ["chip", !isDouyin(u) && "chip--muted"], title: isDouyin(u) ? "" : "非抖音链接无法读取内容，会只分析你粘贴的文字" }, icon("link"), host(u))));
      if (hasWords(words)) parts.push(h("span", { class: "chip" }, icon("file"), `${words.length} 字文字`));
      mountInto(chips, parts.length ? parts : h("span", { class: "hint" }, "还没有内容"));
    };
    ta.addEventListener("input", updateChips);

    getConfig().then((c) => {
      caps = c;
      if (!ctx.alive()) return;
      capNote.textContent = c.asr
        ? "已开启语音转写：会听抖音视频里的讲解来识别地点。"
        : "未开启语音转写：会读取抖音视频的标题与你粘贴的文案识别地点（配置 MIMO_API_KEY 后可以听视频内容）。";
    }).catch(() => {});

    async function analyze() {
      const raw = ta.value.trim();
      if (!raw) return toast("先粘贴一些内容：抖音链接、笔记或地名都行", { error: true });
      const urls = extractUrls(raw);
      const douyin = urls.filter(isDouyin).slice(0, 10);
      const words = textOnly(raw);
      const others = urls.filter((u) => !isDouyin(u));
      if (!douyin.length && !hasWords(words)) return toast("没有可分析的内容：小红书等链接无法直接读取，请把笔记文字一起粘贴进来", { error: true });

      state.videoLinks = raw.split("\n");
      analyzeBtn.disabled = true;
      results.replaceChildren();

      const STAGES = douyin.length ? (caps.asr ? ["读取视频", "语音转写", "识别地点"] : ["读取视频标题", "识别地点"]) : ["识别地点"];
      const bar = h("div", { class: "progress" }, h("i"));
      const label = h("p", { class: "analysis-label" });
      const list = h("ol", { class: "stages" }, STAGES.map((t) => h("li", null, h("span", { class: "stage-dot" }), t)));
      const head = [douyin.length && `${douyin.length} 个抖音视频`, hasWords(words) && `${words.length} 字文字`].filter(Boolean).join(" + ");
      mountInto(stage, h("div", { class: "analysis-top" }, h("b", null, `正在分析 ${head}`), h("span", { class: "mono faint" }, douyin.length && caps.asr ? "预计 1–2 分钟" : "几秒钟")), bar, list, label);
      stage.hidden = false;
      if (douyin.length && caps.asr) nudgeChat(`正在分析 ${douyin.length} 个视频，需要 1–2 分钟 ⏳\n\n等的时候可以问我：\n- 这座城市有什么好吃的\n- 适合拍照的地方`);

      let pct = 4;
      const t0 = Date.now();
      const tick = setInterval(() => {
        pct = Math.min(pct + Math.random() * (caps.asr ? 5 : 18), 92);
        bar.firstChild.style.width = `${pct}%`;
        const cur = Math.min(STAGES.length - 1, Math.floor((pct / 100) * STAGES.length));
        [...list.children].forEach((li, i) => {
          li.classList.toggle("on", i === cur);
          li.classList.toggle("done", i < cur);
        });
        label.textContent = `${STAGES[cur]}… 已用 ${Math.round((Date.now() - t0) / 1000)} 秒`;
      }, 700);

      const p = state.persona;
      const city = state.trip.city;
      const jobs = [];
      if (douyin.length) jobs.push(api.post("/api/video/analyze", { urls: douyin, text: raw, city, personality: p ? { mbti: p.mbti, personality_name: p.personality?.name } : {} }).then((d) => ({ kind: "video", d })));
      if (hasWords(words)) jobs.push(api.post("/api/inspiration/extract", { text: words, city }).then((d) => ({ kind: "text", d })));

      try {
        const settled = await Promise.allSettled(jobs);
        clearInterval(tick);
        const failed = settled.filter((r) => r.status === "rejected");
        const ok = settled.filter((r) => r.status === "fulfilled").map((r) => r.value);
        if (!ok.length) throw failed[0].reason;

        const video = ok.find((r) => r.kind === "video")?.d || null;
        const text = ok.find((r) => r.kind === "text")?.d || null;
        const merged = [];
        const seen = new Set();
        [...(video?.locations || []).map((l) => ({ ...l, source: "video" })), ...(text?.places || [])].forEach((l, i) => {
          if (!l?.name || seen.has(l.name)) return;
          seen.add(l.name);
          merged.push({ ...l, id: l.id || `insp_${i + 1}`, keywords: l.keywords || l.tags || [], reason: l.reason || "" });
        });
        state.videoAnalysis = { errors: video?.errors || [], transcripts: video?.transcripts || [], others, asr: !!video?.asr, count: merged.length };
        state.places = merged;
        state.selectedIds = new Set(merged.filter((l) => l.lat && l.lng).map((l) => l.id));
        persistDraft();
        failed.forEach((f) => toastError(f.reason));
        if (merged.length) addMessage("ai", `识别完成 ✅ 找到 ${merged.length} 个地点。点「进入地点筛选」继续，或者问我这些地方的问题。`);
        setTimeout(closeChatIfIdle, 2500);
        if (!ctx.alive()) return;
        bar.firstChild.style.width = "100%";
        list.querySelectorAll("li").forEach((li) => (li.className = "done"));
        label.textContent = `完成，用时 ${Math.round((Date.now() - t0) / 1000)} 秒`;
        setTimeout(() => ctx.alive() && ((stage.hidden = true), renderResults()), 500);
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
        data.others?.length ? h("div", { class: "banner banner--info" }, icon("info"), `${data.others.length} 条非抖音链接（${data.others.map(host).slice(0, 2).join("、")}）无法直接读取，已分析你粘贴的文字`) : null,
        data.errors?.length
          ? h("details", { class: "banner banner--err" }, h("summary", null, icon("alert"), `${data.errors.length} 个视频没有识别到地点`), h("ul", null, data.errors.map((e) => h("li", null, h("code", null, host(e.url || String(e))), "：", e.error || "处理失败"))), h("p", { class: "hint" }, "可以把视频标题或文案一起粘贴进来，或在下一步手动添加地点"))
          : null,
        places.length
          ? [
              h("div", { class: "results-head" }, h("h2", null, `找到 ${places.length} 个地点`), h("span", { class: "faint" }, "下面是原文里提到它的那句话，不需要的可以先移除")),
              h("div", { class: "found-grid" }, places.map((l, i) => h("article", { class: "found rise", style: { "--i": Math.min(i, 8) } },
                h("button", { class: "icon-btn icon-btn--sm found-x", type: "button", "aria-label": `移除 ${l.name}`, onclick: () => rm(l.id) }, icon("x")),
                h("h3", null, icon("pin"), l.name),
                l.reason && h("p", { class: "muted quote" }, `“${l.reason}”`),
                h("div", { class: "chip-row" },
                  SOURCE[l.source] && h("span", { class: "tag tag--sea" }, SOURCE[l.source][1]),
                  !(l.lat && l.lng) && h("span", { class: "tag tag--seal" }, "待定位"),
                  (l.keywords || []).slice(0, 3).map((k) => h("span", { class: "tag" }, k)))
              ))),
              h("div", { class: "page-foot" }, h("button", { class: "btn btn--primary btn--lg", type: "button", onclick: () => ctx.navigate("places") }, "进入地点筛选", icon("arrow-right", "i-arrow")))
            ]
          : h("div", { class: "empty" }, h("h3", null, "没有识别到具体地点"), h("p", null, "试试粘贴带地名的文字，比如「武康路、外滩、豫园」；或者跳过，直接从景点库里挑。"))
      );
    }

    mountInto(
      page,
      h("a", { class: "back-link", href: "#/buddy" }, icon("arrow-left"), "返回上一步"),
      h("div", { class: "page-head" }, h("p", { class: "eyebrow" }, "STEP 04 · 灵感素材"), h("h1", null, "收藏了哪些", h("span", { class: "mark" }, "旅行灵感"), "？"), h("p", null, "抖音视频、小红书笔记、攻略文章、朋友发来的清单，统统粘贴进来，帮你把提到的地点找出来。")),
      h("div", { class: "video-box card card--pad" }, h("label", { class: "field-label", for: "f-links" }, "链接或文字（可以混在一起）"), ta, chips, capNote, h("div", { class: "video-actions" }, analyzeBtn, skipBtn)),
      stage,
      results
    );
    updateChips();
    if (state.videoAnalysis) renderResults();
  },
};
