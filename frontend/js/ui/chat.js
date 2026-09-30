import { h, mountInto } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { api } from "../core/api.js";
import { state, bus, hasItinerary } from "../core/state.js";

let fab, drawer, list, input, sendBtn;
let open = false;
let waiting = false;
let welcomed = false;

const QUICK = {
  default: [["☕ 找咖啡店", "我走累了，附近有咖啡店吗？"], ["🌧️ 下雨调整", "下雨了，帮我调整路线"], ["🍜 找美食", "这里有什么好吃的？"], ["📸 找拍照点", "帮我找个拍照点"]],
  itinerary: [["🌧️ 下雨怎么调", "如果那天下雨，帮我把户外景点换成室内的"], ["⏱ 这天太赶吗", "帮我看看每天的节奏是否合理，哪里可以删减"], ["🍜 补一顿饭", "帮我在行程里补充午餐和晚餐的推荐"], ["💰 省钱建议", "怎样在不影响体验的情况下节省预算？"]],
};

// ------------------------------------------------- 安全的轻量 Markdown ----
/** **粗体**、`- ` / `1.` 列表、空行分段 → DOM（不使用 innerHTML） */
export function richText(text) {
  const frag = document.createDocumentFragment();
  const inline = (s) => {
    const out = [];
    s.split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
      if (/^\*\*[^*]+\*\*$/.test(part)) out.push(h("strong", null, part.slice(2, -2)));
      else if (part) out.push(part);
    });
    return out;
  };
  let ul = null;
  String(text || "").split("\n").forEach((raw) => {
    const line = raw.trim();
    const li = /^([-*•]|\d+[.、])\s+(.*)$/.exec(line);
    if (li) {
      if (!ul) frag.append((ul = h("ul", { class: "rt-list" })));
      ul.append(h("li", null, inline(li[2])));
      return;
    }
    ul = null;
    if (!line) return frag.append(h("div", { class: "rt-gap" }));
    frag.append(h("p", null, inline(line)));
  });
  return frag;
}

function bubble(role, content) {
  return h("div", { class: ["msg", `msg--${role}`] }, h("div", { class: "msg-avatar", "aria-hidden": "true" }, role === "ai" ? icon("compass") : icon("user")), h("div", { class: "msg-bubble" }, content));
}

function scrollDown() {
  list.scrollTop = list.scrollHeight;
}

export function addMessage(role, text, suggestions) {
  list.querySelector(".chat-welcome")?.remove();
  list.append(bubble(role, role === "ai" ? richText(text) : text));
  if (suggestions?.length) {
    list.append(h("div", { class: "msg-suggest" }, suggestions.map((s) => h("button", { class: "chip", type: "button", onclick: () => ask(s) }, s))));
  }
  scrollDown();
}

function welcome() {
  const route = document.documentElement.dataset.route === "itinerary" ? "itinerary" : "default";
  return h(
    "div",
    { class: "chat-welcome" },
    h("div", { class: "chat-welcome-mark" }, icon("compass")),
    h("h3", null, "我是你的旅行搭子"),
    h("p", { class: "muted" }, "行程里任何问题都可以问我：吃什么、怎么走、下雨怎么办。"),
    h("div", { class: "chip-row", style: { justifyContent: "center" } }, QUICK[route].map(([label, q]) => h("button", { class: "chip", type: "button", onclick: () => ask(q) }, label)))
  );
}

async function ask(text) {
  const message = (text ?? input.value).trim();
  if (!message || waiting) return;
  input.value = "";
  autosize();
  addMessage("user", message);
  state.chatHistory.push({ role: "user", content: message });
  waiting = true;
  sendBtn.disabled = input.disabled = true;
  const thinking = h("div", { class: "msg msg--ai" }, h("div", { class: "msg-avatar" }, icon("compass")), h("div", { class: "msg-bubble thinking" }, h("i"), h("i"), h("i")));
  list.append(thinking);
  scrollDown();

  try {
    const data = await api.post("/api/chat/message", {
      message,
      context: {
        itinerary: hasItinerary() ? state.itinerary : null,
        profile: state.persona ? { personality_name: state.persona.personality?.name, mbti: state.persona.mbti } : null,
        trip: state.trip,
        weather: state.weather,
        chat_history: state.chatHistory.slice(-10),
      },
    });
    thinking.remove();
    const reply = data.reply || "抱歉，我暂时无法回答这个问题。";
    state.chatHistory.push({ role: "assistant", content: reply });
    addMessage("ai", reply, data.suggestions);
  } catch (e) {
    thinking.remove();
    addMessage("ai", `出错了：${e.message}`);
  } finally {
    waiting = false;
    sendBtn.disabled = input.disabled = false;
    input.focus();
  }
}

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 120) + "px";
}

export function setChatOpen(v) {
  open = v;
  drawer.classList.toggle("is-open", open);
  drawer.toggleAttribute("inert", !open);
  fab.setAttribute("aria-expanded", String(open));
  fab.classList.remove("is-nudging");
  if (open) setTimeout(() => input.focus(), 320);
  else fab.focus({ preventScroll: true });
}

/** 分析视频等长任务期间，主动把搭子叫出来陪聊（窄屏只轻提示，不遮挡） */
export function nudgeChat(message) {
  if (message) addMessage("ai", message);
  if (innerWidth >= 1100) setChatOpen(true);
  else fab.classList.add("is-nudging");
}

/** 长任务结束后，若用户没和搭子聊过，就把自动弹出的抽屉收起，别挡住主操作 */
export function closeChatIfIdle() {
  if (open && !state.chatHistory.some((m) => m.role === "user")) setChatOpen(false);
}

export function initChat() {
  const root = document.getElementById("chat-root");
  list = h("div", { class: "chat-list", role: "log", "aria-live": "polite" });
  input = h("textarea", {
    class: "textarea chat-input",
    rows: 1,
    placeholder: "问我任何旅行中的问题…",
    "aria-label": "给旅行搭子发消息",
    onkeydown: (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) (e.preventDefault(), ask());
    },
    oninput: autosize,
  });
  sendBtn = h("button", { class: "btn btn--primary btn--sm", type: "button", onclick: () => ask() }, icon("send"), "发送");

  drawer = h(
    "aside",
    { class: "drawer chat", "aria-label": "AI 旅行搭子", inert: true },
    h("header", { class: "drawer-head" }, h("div", { class: "drawer-title" }, icon("compass"), h("b", null, "旅行搭子 AI")), h("button", { class: "icon-btn", type: "button", "aria-label": "关闭", onclick: () => setChatOpen(false) }, icon("x"))),
    list,
    h("div", { class: "chat-compose" }, input, sendBtn)
  );
  fab = h("button", { class: "fab", type: "button", "aria-label": "打开 AI 旅行搭子", "aria-expanded": "false", hidden: true, onclick: () => setChatOpen(!open) }, icon("message"));
  root.append(fab, drawer);

  document.addEventListener("keydown", (e) => e.key === "Escape" && open && !document.querySelector(".modal-backdrop") && setChatOpen(false));

  bus.on("route:change", ({ chrome }) => {
    const show = !!state.user && chrome !== false;
    fab.hidden = !show;
    if (!show && open) setChatOpen(false);
    if (show && !welcomed) {
      welcomed = true;
      mountInto(list, welcome());
    }
  });
  bus.on("auth:change", (u) => {
    if (!u) {
      welcomed = false;
      mountInto(list);
      setChatOpen(false);
    }
  });
}
