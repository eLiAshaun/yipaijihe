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
/** 视频平台：抖音走分享页解析，其他平台由后端的 yt-dlp 下载；其余链接当作文章，读正文 */
const VIDEO_HOST = /(^|\.)(douyin\.com|iesdouyin\.com|amemv\.com|bilibili\.com|b23\.tv|youtube\.com|youtu\.be|xiaohongshu\.com|xhslink\.com|ixigua\.com)$/i;
const isVideo = (u) => VIDEO_HOST.test(host(u));
const MAX_ARTICLES = 5;
/** 去掉链接后剩下的文字（小红书笔记、攻略、地名清单…） */
const textOnly = (text) => text.replace(/https?:\/\/\S+/g, " ").replace(/[ \t]+/g, " ").replace(/ *\n[\s]*/g, "\n").trim(); // 保留换行：识别时按句引用原文
const hasWords = (text) => (text.match(/[一-龥A-Za-z]/g) || []).length >= 2;

const SOURCE = { video: ["film", "来自视频"], inspiration: ["file", "来自文字"] };

/** 告诉用户抖音视频会被怎样分析（听语音 / 看画面 / 只读标题） */
function capText(c) {
  const asr = c.asr_status || {};
  const eye = c.vision ? "让大模型看画面里的字幕和招牌" : "";
  let ear = "";
  if (asr.engine === "mimo") ear = "用 MiMo 听视频讲解";
  else if (asr.engine === "local" && asr.ready) ear = "用本地 Whisper 听视频讲解";
  const parts = [ear, eye].filter(Boolean);
  const platforms = (c.video_platforms || ["抖音"]).join(" / ");
  let text = parts.length ? `视频链接（${platforms}）会下载下来，${parts.join("，并")}，再识别其中的地点。` : `视频链接（${platforms}）会读取标题和你粘贴的文案来识别地点。`;
  if (c.reader) text = `${text}文章链接（公众号、知乎、马蜂窝、携程…）会读取正文。`;
  if (asr.engine === "local" && !asr.ready) {
    text += asr.state === "error" ? "（本地语音模型加载失败，暂时不听语音）" : `（本地语音模型正在后台准备${asr.progress != null ? ` ${asr.progress}%` : ""}，好了之后会自动开始听语音）`;
  } else if (asr.engine === "none" && c.vision) {
    text += "（安装 requirements-video.txt 后还能听语音）";
  }
  return text;
}

/** 后端阶段 → 进度（0-6） */
const STAGE_STEP = { 排队中: 0, 读取视频信息: 1, 下载视频: 2, 看图片: 3, 听语音: 3, 校对转写: 4, 看画面: 4, 识别地点: 5, 完成: 6, 没有识别到地点: 6 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 提交视频分析任务并轮询进度；onItems 每次拿到最新的逐条进度 */
async function runVideoJob(body, onItems, alive) {
  const { job_id } = await api.post("/api/video/jobs", body);
  for (;;) {
    await sleep(1200);
    if (!alive()) throw Object.assign(new Error("aborted"), { name: "AbortError" });
    const job = await api.get(`/api/video/jobs/${job_id}`);
    onItems(job.items || [], job.elapsed || 0);
    if (job.status === "done") return job.result;
    if (job.status === "error") throw new Error(job.error || "视频分析失败");
  }
}

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
      placeholder: "粘贴任何旅行灵感：\n· 抖音 / B 站 / 小红书 / YouTube 链接或整段分享文案\n· 公众号、知乎、马蜂窝攻略链接，朋友发的清单\n例如：早上去武康大楼拍照，下午安福路喝咖啡，晚上外滩看夜景",
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
      if (urls.length) parts.push(h("span", { class: "faint", style: { fontSize: "var(--fs-sm)" } }, `${urls.length} 条链接：`), urls.map((u) => h("span", { class: "chip", title: isVideo(u) ? "视频：听讲解、看画面" : "文章：读取正文" }, icon(isVideo(u) ? "film" : "file"), host(u))));
      if (hasWords(words)) parts.push(h("span", { class: "chip" }, icon("file"), `${words.length} 字文字`));
      mountInto(chips, parts.length ? parts : h("span", { class: "hint" }, "还没有内容"));
    };
    ta.addEventListener("input", updateChips);

    getConfig().then((c) => {
      caps = c;
      if (!ctx.alive()) return;
      capNote.textContent = capText(c);
    }).catch(() => {});

    async function analyze() {
      const raw = ta.value.trim();
      if (!raw) return toast("先粘贴一些内容：抖音链接、笔记或地名都行", { error: true });
      const urls = extractUrls(raw);
      const douyin = urls.filter(isVideo).slice(0, 10);
      const words = textOnly(raw);
      const articles = urls.filter((u) => !isVideo(u)).slice(0, MAX_ARTICLES);
      if (!douyin.length && !articles.length && !hasWords(words)) return toast("没有可分析的内容：粘贴视频 / 文章链接，或者带地名的文字", { error: true });

      state.videoLinks = raw.split("\n");
      analyzeBtn.disabled = true;
      results.replaceChildren();

      const bar = h("div", { class: "progress" }, h("i"));
      const label = h("p", { class: "analysis-label" });
      const rows = h("ol", { class: "video-rows" }, douyin.map((u) => h("li", null, h("span", { class: "stage-dot" }), h("code", null, host(u)), h("span", { class: "video-stage" }, "排队中"))));
      const readText = hasWords(words) || articles.length;
      const textRow = readText ? h("p", { class: "analysis-label" }, icon("file"), articles.length ? ` 正在读取 ${articles.length} 篇文章并识别地点…` : ` 正在识别 ${words.length} 字文字里的地点…`) : null;
      const head = [douyin.length && `${douyin.length} 个视频`, articles.length && `${articles.length} 篇文章`, hasWords(words) && `${words.length} 字文字`].filter(Boolean).join(" + ");
      const slow = douyin.length && (caps.asr || caps.vision);
      mountInto(stage, h("div", { class: "analysis-top" }, h("b", null, `正在分析 ${head}`), h("span", { class: "mono faint" }, slow ? "每个视频约 0.5–2 分钟" : "几秒钟")), bar, douyin.length ? rows : null, textRow, label);
      stage.hidden = false;
      if (slow) nudgeChat(`正在分析 ${douyin.length} 个视频（下载、听讲解、看画面），每个约 0.5–2 分钟 ⏳\n\n等的时候可以问我：\n- ${state.trip.city}有什么好吃的\n- 适合拍照的地方`);

      const t0 = Date.now();
      let pct = 3;
      const tick = setInterval(() => {
        if (!douyin.length) pct = Math.min(pct + 15, 92);
        bar.firstChild.style.width = `${pct}%`;
        label.textContent = `已用 ${Math.round((Date.now() - t0) / 1000)} 秒`;
      }, 700);
      const onItems = (items) => {
        // 「听语音 45%」这类带百分比的阶段：按名称取进度，并把百分比折算进去
        const stepOf = (stage) => {
          const [name, pct] = stage.split(" ");
          return (STAGE_STEP[name] ?? 1) + (pct ? parseInt(pct, 10) / 100 : 0);
        };
        const total = items.reduce((n, it) => n + stepOf(it.stage), 0);
        pct = Math.max(pct, Math.min(96, Math.round((total / (6 * items.length)) * 100)));
        items.forEach((it, i) => {
          const li = rows.children[i];
          if (!li) return;
          li.querySelector(".video-stage").textContent = it.stage;
          const n = stepOf(it.stage);
          li.className = n >= 6 ? "done" : n > 0 ? "on" : "";
        });
      };

      const p = state.persona;
      const city = state.trip.city;
      const jobs = [];
      if (douyin.length) jobs.push(runVideoJob({ urls: douyin, text: raw, city, personality: p ? { mbti: p.mbti, personality_name: p.personality?.name } : {} }, onItems, ctx.alive).then((d) => ({ kind: "video", d })));
      if (readText) jobs.push(api.post("/api/inspiration/extract", { text: hasWords(words) ? words : "", urls: articles, city }).then((d) => ((textRow && (textRow.textContent = `✓ ${articles.length ? "文章和文字" : "文字"}里找到 ${d.count} 个地点`)), { kind: "text", d })));

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
        state.videoAnalysis = { errors: video?.errors || [], transcripts: video?.transcripts || [], links: text?.links || [], asr: !!video?.asr, vision: !!video?.vision, count: merged.length };
        state.places = merged;
        state.selectedIds = new Set(merged.filter((l) => l.lat && l.lng).map((l) => l.id));
        persistDraft();
        failed.forEach((f) => toastError(f.reason));
        if (merged.length) addMessage("ai", `识别完成 ✅ 找到 ${merged.length} 个地点。点「进入地点筛选」继续，或者问我这些地方的问题。`);
        setTimeout(closeChatIfIdle, 2500);
        if (!ctx.alive()) return;
        bar.firstChild.style.width = "100%";
        label.textContent = `完成，用时 ${Math.round((Date.now() - t0) / 1000)} 秒`;
        setTimeout(() => ctx.alive() && ((stage.hidden = true), renderResults()), 500);
      } catch (e) {
        clearInterval(tick);
        if (ctx.alive() && e.name !== "AbortError") ((stage.hidden = true), toastError(e));
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
        data.links?.length ? h("div", { class: "video-done" }, data.links.map((l) => h("div", { class: ["video-heard", "link-read", !l.ok && "is-failed"] },
          icon(l.ok ? "file" : "alert"), h("b", null, l.ok ? `《${(l.title || host(l.url)).slice(0, 30)}》` : host(l.url)),
          h("span", { class: "faint" }, l.ok ? ` 读了正文 ${l.chars} 字` : ` 没读到正文（${l.error || "需要登录"}），已用你粘贴的文字`)))) : null,
        data.transcripts?.length ? h("div", { class: "video-done" }, data.transcripts.map((t) => h("details", { class: "video-heard" },
          h("summary", null, icon("film"), h("b", null, t.title ? `「${t.title.slice(0, 28)}」` : host(t.url)), h("span", { class: "faint" }, ` ${(t.done || []).join(" · ") || "读了你粘贴的文案"}`)),
          (t.notes || []).map((n) => h("p", { class: "hint" }, n)),
          t.text && h("p", null, h("b", null, "听到："), t.text.length > 400 ? `${t.text.slice(0, 400)}…` : t.text),
          t.screen && h("p", null, h("b", null, "看到："), t.screen.length > 300 ? `${t.screen.slice(0, 300)}…` : t.screen)))) : null,
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
