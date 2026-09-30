import { h, mountInto, clamp, copyText } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { api } from "../core/api.js";
import { state } from "../core/state.js";
import { personaImg, decoFromFile } from "../core/config.js";
import { savePersona } from "../services/auth.js";
import { toast, toastError } from "../ui/toast.js";

const LETTERS = ["A", "B", "C", "D", "E"];
const SLIDER_STOPS = ["完全偏左", "更偏左一些", "我都要", "更偏右一些", "完全偏右"];
const sliderText = (v) => SLIDER_STOPS[v < 12.5 ? 0 : v < 37.5 ? 1 : v <= 62.5 ? 2 : v < 87.5 ? 3 : 4];

// ===================================================================
// 人格卡片（结果页 & 弹窗共用）
// ===================================================================
export function personaCard(result, { modal = false } = {}) {
  const p = result.personality;
  const paras = (p.description || "").split("\n").filter((l) => l.trim());
  const dims = result.dimensions || [];

  return h(
    "article",
    { class: ["persona-card", modal && "persona-card--modal"], style: { "--persona": p.color || "var(--seal)" } },
    h(
      "div",
      { class: "persona-art" },
      h("div", { class: "persona-frame" }, h("img", { src: personaImg(p.image), alt: `${p.name} 插画`, width: 1200, height: 1200, decoding: "async" }), h("i", { class: "tape tape--l" }), h("i", { class: "tape tape--r" })),
      h("div", { class: "stamp persona-stamp", style: { "--c": "var(--seal)" } }, h("span", null, "TRAVEL TYPE"), h("b", null, result.mbti))
    ),
    h(
      "div",
      { class: "persona-info" },
      h("p", { class: "eyebrow" }, p.subtitle),
      h("h2", { class: "persona-name" }, h("span", { class: "persona-emoji" }, p.emoji), p.name),
      h("p", { class: "persona-full" }, p.full_name),
      h("div", { class: "persona-desc" }, paras.map((t) => h("p", null, t))),
      p.style_tags?.length ? h("div", { class: "chip-row" }, p.style_tags.map((t) => h("span", { class: "chip" }, t))) : null,
      dims.length
        ? h(
            "div",
            { class: "dims" },
            dims.map((d, i) => {
              const pct = d.total ? (d.score_a / d.total) * 100 : 50;
              const aWins = d.score_a >= d.score_b;
              return h(
                "div",
                { class: "dim rise", style: { "--i": i + 2 } },
                h("div", { class: "dim-name mono" }, d.name),
                h("div", { class: "dim-poles" }, h("span", { class: aWins && "on" }, d.label_a), h("span", { class: !aWins && "on" }, d.label_b)),
                h("div", { class: "dim-bar", role: "img", "aria-label": `${d.name}：${aWins ? d.label_a : d.label_b}` }, h("i", { style: { left: `${clamp(pct, 4, 96)}%` } }))
              );
            })
          )
        : null,
      p.strengths?.length ? h("div", { class: "strengths" }, p.strengths.map((s) => h("span", { class: "tag tag--seal" }, s))) : null
    )
  );
}

// ===================================================================
// 深度画像（可选）：把提示词发给常用 AI，再把 JSON 贴回来
// ===================================================================
const DEEP_PROMPT = `你是我最常使用、最了解我的 AI 助手。我正在使用一个旅行规划产品，需要你根据你对我的了解，输出一份「我的旅行偏好画像」，帮助这个产品更精准地为我推荐旅行内容与路线。

请只输出一个 JSON（放进 \`\`\`json 代码块里），不要任何多余文字。字段如下：
{
  "interests": ["我感兴趣的旅行主题/内容关键词，最多6个，如 摄影、咖啡、历史、美食、自然、夜生活"],
  "food_preferences": "我的饮食偏好与忌口（一句话）",
  "pace_preference": "我偏好的旅行节奏，如 慢节奏深度 / 紧凑高效 / 随性灵活",
  "budget_attitude": "我的消费态度，如 注重性价比 / 愿为体验付费 / 严格控制预算",
  "social_preference": "我偏好独自还是结伴，及和谁（一句话）",
  "avoid": ["我明显想避免的东西，最多5个，如 人多排队、过度商业化、早起"],
  "hidden_insights": "你观察到的、我自己可能都没意识到的旅行相关倾向（1-3句）",
  "summary": "用一句话概括我的旅行风格"
}
如果某项你确实不了解，就给空字符串或空数组，不要编造。`;

function parseDeepProfile(raw) {
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const brace = raw.match(/\{[\s\S]*\}/);
  const text = fence ? fence[1] : brace ? brace[0] : raw;
  try {
    const obj = JSON.parse(text);
    return obj && typeof obj === "object" && !Array.isArray(obj) ? obj : null;
  } catch {
    return null;
  }
}

function deepProfileCard(result) {
  const box = h("div", { class: "deep" });
  const render = () => {
    const dp = result.deep_profile;
    if (dp && (dp.summary || dp.interests?.length)) {
      return mountInto(
        box,
        h(
          "div",
          { class: "deep-done" },
          h("div", { class: "deep-head" }, icon("sparkles"), h("b", null, "深度画像已记录"), h("span", { class: "faint" }, "推荐与排程会更懂你")),
          dp.summary && h("p", null, dp.summary),
          dp.interests?.length ? h("div", { class: "chip-row" }, dp.interests.map((t) => h("span", { class: "chip" }, t))) : null,
          h("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: () => ((result.deep_profile = null), render()) }, "重新填写")
        )
      );
    }
    const status = h("p", { class: "form-error", role: "alert" });
    const paste = h("textarea", { class: "textarea", rows: 5, placeholder: "把 AI 返回的内容（含 { } 的 JSON）整段粘贴到这里", "aria-label": "AI 返回的偏好画像" });
    mountInto(
      box,
      h(
        "details",
        { class: "deep-edit" },
        h("summary", null, icon("sparkles"), "想让推荐更懂你？让你常用的 AI 帮你写一份偏好画像（选做）", icon("chevron-down", "deep-caret")),
        h("div", { class: "deep-body" },
          h("p", { class: "muted" }, "把下面的提示词复制给你最常用的 AI（豆包 / Kimi / ChatGPT），再把它的回复整段粘回来。"),
          h("textarea", { class: "textarea deep-prompt", readonly: true, rows: 6, "aria-label": "提示词" }, DEEP_PROMPT),
          h("button", { class: "btn btn--quiet btn--sm", type: "button", onclick: async () => toast((await copyText(DEEP_PROMPT)) ? "提示词已复制" : "复制失败，请手动选择复制", { error: false }) }, icon("copy"), "复制提示词"),
          paste,
          status,
          h("button", { class: "btn btn--ink btn--sm", type: "button", onclick: async () => {
            const raw = paste.value.trim();
            const setErr = (m) => ((status.textContent = m), status.classList.add("is-visible"));
            if (!raw) return setErr("请先粘贴 AI 返回的内容");
            const parsed = parseDeepProfile(raw);
            if (!parsed) return setErr("没能识别出 JSON，请把含大括号的那一段整段粘贴进来");
            result.deep_profile = parsed;
            await savePersona(result);
            toast("已记录你的深度画像");
            render();
          } }, "提交深度画像")
        )
      )
    );
  };
  render();
  return box;
}

// ===================================================================
// 页面：答题向导 → 结果
// ===================================================================
export default {
  title: () => "旅行人格",

  mount(root, ctx) {
    const page = h("section", { class: "page page--tight persona-page" });
    root.append(page);
    let questions = [];
    let idx = 0;

    const showResult = (result, { fresh = false } = {}) => {
      mountInto(
        page,
        h("div", { class: "page-head page-head--center" }, h("p", { class: "eyebrow" }, "STEP 01 · 你的旅行人格"), h("h1", null, fresh ? "你的旅行人格是……" : "你的旅行人格")),
        personaCard(result),
        deepProfileCard(result),
        h(
          "div",
          { class: "page-foot" },
          h("button", { class: "btn btn--quiet", type: "button", onclick: () => ((state.mbtiAnswers = {}), startQuiz()) }, icon("refresh"), "重新测试"),
          h("button", { class: "btn btn--primary btn--lg", type: "button", onclick: () => ctx.navigate("plan") }, "下一步：行程规划", icon("arrow-right", "i-arrow"))
        )
      );
    };

    const isAnswered = (q) => {
      const a = state.mbtiAnswers[q.id];
      return a !== undefined && a !== null && (!Array.isArray(a) || a.length > 0);
    };

    async function startQuiz() {
      mountInto(page, h("div", { class: "skeleton", style: { height: "420px" } }));
      try {
        questions = (await api.get("/api/mbti/questions", { signal: ctx.signal })).questions;
      } catch (e) {
        if (!ctx.alive()) return;
        return mountInto(page, h("div", { class: "empty" }, h("h3", null, "题目加载失败"), h("p", null, e.message), h("button", { class: "btn btn--ink", onclick: startQuiz }, "重试")));
      }
      // 排序题：默认顺序即为初始答案
      questions.forEach((q) => q.type === "ranking" && !state.mbtiAnswers[q.id] && (state.mbtiAnswers[q.id] = q.options.map((o) => o.id)));
      idx = Math.max(0, questions.findIndex((q) => !isAnswered(q)));
      if (idx < 0) idx = 0;
      renderQuestion(1);
    }

    function renderQuestion(dir = 1) {
      const q = questions[idx];
      const last = idx === questions.length - 1;
      const next = h("button", { class: "btn btn--primary", type: "button", disabled: !isAnswered(q), onclick: advance }, last ? "查看结果" : "下一题", icon("arrow-right", "i-arrow"));
      const sync = () => (next.disabled = !isAnswered(q));

      const [main, hint] = (() => {
        const i = q.question.indexOf("（");
        return i >= 0 ? [q.question.slice(0, i), q.question.slice(i)] : [q.question, ""];
      })();

      const body = q.type === "single" ? single(q, sync, () => setTimeout(() => !last && advance(), 320)) : q.type === "ranking" ? ranking(q, sync) : slider(q, sync);

      const progress = h(
        "ol",
        { class: "quiz-progress", "aria-label": "答题进度" },
        questions.map((qq, i) => h("li", null, h("button", { type: "button", class: [i === idx && "on", isAnswered(qq) && i !== idx && "done"], "aria-label": `第 ${i + 1} 题`, "aria-current": i === idx ? "step" : null, disabled: i > idx && !isAnswered(questions[i - 1]), onclick: () => {
          const dir = i > idx ? 1 : -1;
          idx = i;
          renderQuestion(dir);
        } })))
      );

      mountInto(
        page,
        h("div", { class: "page-head page-head--center" }, h("p", { class: "eyebrow" }, "STEP 01 · 旅行人格"), h("h1", null, "先聊聊你的", h("span", { class: "mark" }, "旅行风格")), h("p", null, "旅行人格相对稳定，一次测试，之后每次规划都会用到。")),
        progress,
        h(
          "div",
          { class: ["question", dir > 0 ? "from-right" : "from-left"], "data-type": q.type },
          q.deco_image && h("img", { class: ["sticker", "q-sticker", q.deco_position === "left" ? "q-left" : "q-right"], src: decoFromFile(q.deco_image), alt: "", width: 160, height: 160 }),
          h("p", { class: "q-num mono" }, `Q${String(idx + 1).padStart(2, "0")} / ${String(questions.length).padStart(2, "0")}`),
          h("h2", { class: "q-text" }, main, hint && h("small", null, hint)),
          body
        ),
        h(
          "div",
          { class: "quiz-nav" },
          h("button", { class: "btn btn--ghost", type: "button", disabled: idx === 0, onclick: () => (idx--, renderQuestion(-1)) }, icon("arrow-left"), "上一题"),
          next
        )
      );
      page.querySelector(".q-text")?.setAttribute("tabindex", "-1");
    }

    async function advance() {
      const q = questions[idx];
      if (!isAnswered(q)) return;
      if (idx < questions.length - 1) return (idx++, renderQuestion(1));
      mountInto(page, h("div", { class: "quiz-loading" }, h("div", { class: "stamp", style: { animation: "spin 1.6s linear infinite" } }, h("b", null, "…")), h("p", null, "正在为你盖章定型")));
      try {
        const result = await api.post("/api/mbti/calculate", { answers: state.mbtiAnswers });
        await savePersona(result);
        if (ctx.alive()) showResult(result, { fresh: true });
      } catch (e) {
        toastError(e);
        if (ctx.alive()) renderQuestion(-1);
      }
    }

    // ---------------- 单选 ----------------
    function single(q, sync, after) {
      const wrap = h("div", { class: "opts", role: "radiogroup", "aria-label": q.question });
      q.options.forEach((o, i) => {
        const btn = h(
          "button",
          { class: "opt", type: "button", role: "radio", "aria-checked": String(state.mbtiAnswers[q.id] === o.id), onclick: () => {
            state.mbtiAnswers[q.id] = o.id;
            wrap.querySelectorAll(".opt").forEach((b) => b.setAttribute("aria-checked", String(b === btn)));
            sync();
            after();
          } },
          h("span", { class: "opt-key mono" }, LETTERS[i]),
          h("span", { class: "opt-text" }, o.text)
        );
        wrap.append(btn);
      });
      // 数字键快捷选择
      const onKey = (e) => {
        const n = Number(e.key);
        if (n >= 1 && n <= q.options.length && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName)) wrap.children[n - 1].click();
      };
      ctx.disposer.listen(document, "keydown", onKey);
      return wrap;
    }

    // ---------------- 排序 ----------------
    function ranking(q, sync) {
      const byId = Object.fromEntries(q.options.map((o) => [o.id, o]));
      const list = h("ol", { class: "rank" });
      let dragId = null;

      const commit = () => {
        state.mbtiAnswers[q.id] = [...list.children].map((li) => li.dataset.id);
        [...list.children].forEach((li, i) => (li.querySelector(".rank-n").textContent = i + 1));
        sync();
      };
      const move = (li, delta) => {
        const sib = delta < 0 ? li.previousElementSibling : li.nextElementSibling;
        if (!sib) return;
        delta < 0 ? list.insertBefore(li, sib) : list.insertBefore(sib, li);
        commit();
        li.querySelector(delta < 0 ? ".up" : ".down")?.focus();
      };

      (state.mbtiAnswers[q.id] || q.options.map((o) => o.id)).forEach((id, i) => {
        const li = h(
          "li",
          { class: "rank-item", draggable: true, "data-id": id },
          h("span", { class: "rank-n mono" }, i + 1),
          h("span", { class: "rank-text" }, byId[id].text),
          h("span", { class: "rank-btns" },
            h("button", { class: "icon-btn icon-btn--sm up", type: "button", "aria-label": "上移", onclick: () => move(li, -1) }, icon("arrow-up")),
            h("button", { class: "icon-btn icon-btn--sm down", type: "button", "aria-label": "下移", onclick: () => move(li, 1) }, icon("arrow-down"))),
          h("span", { class: "rank-grip", "aria-hidden": "true" }, icon("grip"))
        );
        li.addEventListener("dragstart", (e) => ((dragId = id), li.classList.add("dragging"), (e.dataTransfer.effectAllowed = "move"), e.dataTransfer.setData("text/plain", id)));
        li.addEventListener("dragend", () => (li.classList.remove("dragging"), (dragId = null), commit()));
        list.append(li);
      });
      list.addEventListener("dragover", (e) => {
        e.preventDefault();
        const dragging = list.querySelector(".dragging");
        if (!dragging) return;
        const after = [...list.querySelectorAll(".rank-item:not(.dragging)")].find((el) => e.clientY < el.getBoundingClientRect().top + el.offsetHeight / 2);
        after ? list.insertBefore(dragging, after) : list.append(dragging);
      });
      return h("div", null, h("p", { class: "hint", style: { marginBottom: "12px" } }, "拖动卡片，或用右侧箭头调整顺序（上 = 最想，下 = 最不想）"), list);
    }

    // ---------------- 滑块 ----------------
    function slider(q, sync) {
      const has = state.mbtiAnswers[q.id] !== undefined;
      const val = has ? state.mbtiAnswers[q.id] : 50;
      const readout = h("div", { class: ["slider-read", !has && "empty"] }, has ? sliderText(val) : "拖动圆点作答");
      const input = h("input", { class: "slider", type: "range", min: 0, max: 100, step: 1, value: val, "aria-label": `${q.label_a} 与 ${q.label_b} 之间`, style: { "--v": `${val}%` }, oninput: (e) => {
        const v = Number(e.target.value);
        state.mbtiAnswers[q.id] = v;
        e.target.style.setProperty("--v", `${v}%`);
        readout.classList.remove("empty");
        readout.textContent = sliderText(v);
        sync();
      } });
      return h(
        "div",
        { class: "slide" },
        h("div", { class: "slide-poles" }, h("span", null, q.label_a), h("span", null, q.label_b)),
        h("div", { class: "slide-track" }, input, h("div", { class: "slide-ticks" }, [0, 25, 50, 75, 100].map((p) => h("i", { style: { left: `${p}%` } })))),
        readout
      );
    }

    // ---------------- 入口 ----------------
    if (state.persona) showResult(state.persona);
    else startQuiz();
  },
};
