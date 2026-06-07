/**
 * 一拍迹合 - 前端应用
 * 抖音精选内容重构黑客松参赛作品
 *
 * 流程：登录/注册 → 旅行人格 → 行程规划 → 搭子同步 → 精选视频 → 地图预览 → 路线生成 → 导出分享
 * AI搭子：浮动按钮，随时可打开侧边聊天面板
 */

// ============================================
// 全局状态
// ============================================
const state = {
  currentStep: 1,
  currentPage: "login",
  mbtiAnswers: {},
  mbtiResult: null,
  tripConfig: {
    city: "上海",
    days: 2,
    budget: 500, // 人均预算（¥，整趟）
  },
  selectedLocations: [],
  videos: [],
  itinerary: null,
  map: null,
  routeCatalog: [],
  routeLocationLookup: {},
  routeVideoLookup: {},
  routeEditor: {
    interestedStops: new Set(),
  },
  stopFeedbacks: {},  // { stopId: 'like' | 'must' | 'dislike' }
  activeFeedbackStopId: null,
  activeRouteStopId: null,
  routeTransportMode: "transfer",
  routePolylines: [],
  user: null,
  token: localStorage.getItem("luvdazi_token") || null,
  isLoggedIn: false,
  existingPlans: [],
  hasBuddy: false,
  buddyInfo: null,
  videoLinks: [],
  videoAnalysis: null,
  analyzedLocations: [],
  exportType: null,
  // AI搭子聊天
  chatHistory: [],      // 多轮对话历史
  chatPanelOpen: false,
};

// ============================================
// 页面ID → 步骤号映射（7步，chat不在流程中）
// ============================================
const PAGE_STEP_MAP = {
  mbti: 1,
  plan: 2,
  buddy: 3,
  videos: 4,
  "map-preview": 5,
  itinerary: 6,
  export: 7,
};

const STEP_LABELS = {
  1: "旅行人格",
  2: "行程规划",
  3: "旅行搭子",
  4: "精选视频",
  5: "地图预览",
  6: "路线生成",
  7: "导出分享",
};

const TOTAL_STEPS = 7;

// ============================================
// API 工具函数
// ============================================
const api = {
  _headers() {
    const h = { "Content-Type": "application/json" };
    if (state.token) h["Authorization"] = `Bearer ${state.token}`;
    return h;
  },

  async get(url) {
    const res = await fetch(url, { headers: this._headers() });
    return res.json();
  },

  async post(url, data) {
    const res = await fetch(url, {
      method: "POST",
      headers: this._headers(),
      body: JSON.stringify(data),
    });
    return res.json();
  },

  async put(url, data) {
    const res = await fetch(url, {
      method: "PUT",
      headers: this._headers(),
      body: JSON.stringify(data),
    });
    return res.json();
  },
};

// ============================================
// 页面切换
// ============================================
function showPage(pageId) {
  document
    .querySelectorAll(".page")
    .forEach((el) => el.classList.remove("active"));

  const pageMap = {
    login: "page-login",
    register: "page-register",
    mbti: "page-mbti",
    plan: "page-plan",
    buddy: "page-buddy",
    videos: "page-videos",
    "map-preview": "page-map",
    itinerary: "page-itinerary",
    export: "page-export",
  };

  const targetId = pageMap[pageId];
  if (targetId) {
    document.getElementById(targetId).classList.add("active");
    state.currentPage = pageId;

    if (PAGE_STEP_MAP[pageId] !== undefined) {
      updateStepNav(PAGE_STEP_MAP[pageId]);
    }

    // 登录/注册页面隐藏导航和聊天按钮
    const stepNav = document.getElementById("step-nav");
    const chatFab = document.getElementById("chat-fab");
    if (pageId === "login" || pageId === "register") {
      stepNav.style.display = "none";
      if (chatFab) chatFab.style.display = "none";
    } else {
      stepNav.style.display = "";
      // 登录后才显示聊天按钮
      if (chatFab && state.isLoggedIn) chatFab.style.display = "";
    }

    window.scrollTo({ top: 0, behavior: "smooth" });

    // 页面切换后执行初始化
    if (pageId === "map-preview") initMapPreview();
  }
}

/** 更新简化步骤导航：只显示当前步骤 + 进度条 */
function updateStepNav(step) {
  state.currentStep = step;

  const numberEl = document.getElementById("step-current-number");
  const labelEl = document.getElementById("step-current-label");
  const barEl = document.getElementById("step-progress-bar");

  if (numberEl) numberEl.textContent = step;
  if (labelEl) labelEl.textContent = STEP_LABELS[step] || "";
  if (barEl) barEl.style.width = ((step - 1) / (TOTAL_STEPS - 1)) * 100 + "%";
}

/** 向前跳到指定步骤 */
function goToPage(step) {
  const pageIdMap = {
    1: "mbti",
    2: "plan",
    3: "buddy",
    4: "videos",
    5: "map-preview",
    6: "itinerary",
    7: "export",
  };
  const pageId = pageIdMap[step];
  if (pageId) showPage(pageId);
}

/** 各步骤的「上一步」目标页 */
const PREV_PAGE = {
  plan: "mbti",
  buddy: "plan",
  videos: "buddy",
  "map-preview": "videos",
  itinerary: "map-preview",
  export: "itinerary",
};

/** 返回上一步 */
function goToPreviousStep() {
  const prev = PREV_PAGE[state.currentPage];
  if (!prev) return;
  if (prev === "mbti") ensureMbtiPageContent();
  showPage(prev);
}

/** 确保旅行人格页有内容可显示 */
function ensureMbtiPageContent() {
  const questions = document.getElementById("mbti-questions");
  const result = document.getElementById("mbti-result");
  const hasQuestions = questions && questions.innerHTML.trim() !== "";
  const hasResult = result && result.innerHTML.trim() !== "";
  if (hasQuestions || hasResult) return;

  if (state.mbtiResult && state.mbtiResult.personality && state.mbtiResult.dimensions) {
    renderMBTIResult(state.mbtiResult);
  } else {
    resetMBTIPage();
  }
}

// ============================================
// AI搭子：浮动按钮 + 侧边聊天面板
// ============================================

function toggleChatPanel() {
  const panel = document.getElementById("chat-panel");
  state.chatPanelOpen = !state.chatPanelOpen;

  if (state.chatPanelOpen) {
    panel.classList.add("open");
    // 聚焦输入框
    setTimeout(() => {
      document.getElementById("chat-input").focus();
    }, 350);
  } else {
    panel.classList.remove("open");
  }
}

function initChatPanel() {
  const textarea = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");

  // IME 中文输入法合成状态追踪
  let isComposing = false;
  textarea.addEventListener("compositionstart", () => { isComposing = true; });
  textarea.addEventListener("compositionend", () => { isComposing = false; });

  // 发送按钮
  sendBtn.addEventListener("click", () => sendChatMessage());

  // Enter 发送，Shift+Enter 换行，IME合成期间不拦截
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !isComposing) {
      e.preventDefault();
      sendChatMessage();
    }
  });

  // 自动调整高度
  textarea.addEventListener("input", () => {
    autoResizeTextarea(textarea);
  });

  // 快捷问题按钮
  document.querySelectorAll(".quick-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      sendChatMessage(btn.dataset.q);
    });
  });
}

function autoResizeTextarea(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 120) + "px";
}

let chatWaiting = false; // 防止重复发送

async function sendChatMessage(text) {
  if (chatWaiting) return;

  const textarea = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");
  const message = text || textarea.value.trim();

  if (!message) return;
  textarea.value = "";
  textarea.style.height = "auto";

  // 隐藏欢迎
  const welcome = document.querySelector("#chat-messages .chat-welcome");
  if (welcome) welcome.style.display = "none";

  addChatMessage("user", message);

  // 记录到多轮对话历史
  state.chatHistory.push({ role: "user", content: message });

  // 禁用输入 + 显示 thinking
  chatWaiting = true;
  textarea.disabled = true;
  sendBtn.disabled = true;
  textarea.placeholder = "AI 正在思考...";

  const thinkingId = addThinkingIndicator();

  const context = {
    itinerary: state.itinerary,
    profile: state.mbtiResult
      ? {
          personality_name: state.mbtiResult.personality?.name,
          mbti: state.mbtiResult.mbti,
        }
      : null,
    chat_history: state.chatHistory.slice(-10),
  };

  const data = await api.post("/api/chat/message", {
    message: message,
    context: context,
  });

  // 移除 thinking + 恢复输入
  removeThinkingIndicator(thinkingId);
  chatWaiting = false;
  textarea.disabled = false;
  sendBtn.disabled = false;
  textarea.placeholder = "问我任何旅行中的问题...";
  textarea.focus();

  const reply = data.reply || "抱歉，我暂时无法回答这个问题。";
  addChatMessage("ai", reply, data.suggestions);

  // 记录AI回复到历史
  state.chatHistory.push({ role: "assistant", content: reply });
}

function addChatMessage(type, text, suggestions) {
  const container = document.getElementById("chat-messages");
  const avatar = type === "ai" ? "🧳" : "👤";
  const bubbleContent = type === "ai" ? formatAIMessage(text) : escapeHtml(text);

  let html = `
    <div class="chat-message ${type}">
      <div class="message-avatar">${avatar}</div>
      <div class="message-bubble">${bubbleContent}</div>
    </div>
  `;

  if (suggestions && suggestions.length > 0) {
    html += `
      <div class="message-suggestions">
        ${suggestions
          .map((s) => {
            const escaped = s.replace(/'/g, "\\'").replace(/"/g, "&quot;");
            return `<button class="suggestion-btn" onclick="sendChatMessage('${escaped}')">${s}</button>`;
          })
          .join("")}
      </div>
    `;
  }

  container.insertAdjacentHTML("beforeend", html);
  scrollChatToBottom();
}

/** 格式化AI长回复：保留结构、列表、加粗 */
function formatAIMessage(text) {
  if (!text) return "";

  // 先转义HTML
  let safe = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // 按换行分割，逐行处理
  const lines = safe.split("\n");
  const formatted = lines.map((line) => {
    const trimmed = line.trim();

    // 空行
    if (!trimmed) return '<div class="msg-line" style="height:8px;"></div>';

    // 列表项：- xxx 或 * xxx 或 1. xxx
    if (/^[-*]\s+/.test(trimmed)) {
      const content = trimmed.replace(/^[-*]\s+/, "");
      return `<div class="msg-list-item">${inlineFormat(content)}</div>`;
    }
    if (/^\d+\.\s+/.test(trimmed)) {
      const content = trimmed.replace(/^\d+\.\s+/, "");
      return `<div class="msg-list-item">${inlineFormat(content)}</div>`;
    }

    // 普通行
    return `<div class="msg-line">${inlineFormat(trimmed)}</div>`;
  });

  return formatted.join("");
}

/** 行内格式：加粗、emoji行 */
function inlineFormat(text) {
  // **粗体** → <span class="msg-bold">
  let result = text.replace(/\*\*(.+?)\*\*/g, '<span class="msg-bold">$1</span>');
  return result;
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
}

/** Thinking 状态指示器 */
function addThinkingIndicator() {
  const container = document.getElementById("chat-messages");
  const id = "thinking-" + Date.now();

  container.insertAdjacentHTML(
    "beforeend",
    `
    <div class="chat-message ai" id="${id}">
      <div class="message-avatar">🧳</div>
      <div class="chat-thinking">
        <span>正在思考</span>
        <div class="chat-thinking-dots">
          <div class="chat-thinking-dot"></div>
          <div class="chat-thinking-dot"></div>
          <div class="chat-thinking-dot"></div>
        </div>
      </div>
    </div>
  `
  );

  scrollChatToBottom();
  return id;
}

function removeThinkingIndicator(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function scrollChatToBottom() {
  const container = document.getElementById("chat-messages");
  container.scrollTop = container.scrollHeight;
}

// ============================================
// 用户认证模块
// ============================================

function showLoginPage() {
  showPage("login");
  clearAuthForms();
  clearAllAuthErrors();
}

function showRegisterPage() {
  showPage("register");
  clearAuthForms();
  clearAllAuthErrors();
}

function showAuthError(msg, formType) {
  const el = document.getElementById(
    formType === "register" ? "register-error" : "login-error"
  );
  if (el) {
    el.textContent = msg;
    el.classList.add("show");
  }
}

function clearAllAuthErrors() {
  ["login-error", "register-error"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = "";
      el.classList.remove("show");
    }
  });
}

function clearAuthForms() {
  ["login-username", "login-password", "reg-username", "reg-password", "reg-password2"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
}

async function handleLogin(e) {
  e.preventDefault();
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;

  if (!username || !password) {
    showAuthError("请填写用户名和密码", "login");
    return;
  }

  const btn = document.getElementById("btn-login");
  btn.disabled = true;
  btn.textContent = "登录中...";

  const data = await api.post("/api/auth/login", { username, password });

  btn.disabled = false;
  btn.textContent = "登录";

  if (data.error) {
    showAuthError(data.error, "login");
    return;
  }

  onLoginSuccess(data.token, data.user);
}

async function handleRegister(e) {
  e.preventDefault();
  const username = document.getElementById("reg-username").value.trim();
  const password = document.getElementById("reg-password").value;
  const password2 = document.getElementById("reg-password2").value;

  if (!username || !password) {
    showAuthError("请填写所有字段", "register");
    return;
  }
  if (password.length < 6) {
    showAuthError("密码长度至少 6 个字符", "register");
    return;
  }
  if (password !== password2) {
    showAuthError("两次输入的密码不一致", "register");
    return;
  }

  const btn = document.getElementById("btn-register");
  btn.disabled = true;
  btn.textContent = "注册中...";

  const data = await api.post("/api/auth/register", { username, password });

  btn.disabled = false;
  btn.textContent = "注册";

  if (data.error) {
    showAuthError(data.error, "register");
    return;
  }

  onRegisterSuccess(data.token, data.user);
}

async function onLoginSuccess(token, user) {
  state.token = token;
  state.user = user;
  state.isLoggedIn = true;
  localStorage.setItem("luvdazi_token", token);

  clearAuthForms();
  updateAuthUI();

  await loadUserProfile();

  if (state.mbtiResult && state.mbtiResult.mbti) {
    showToast(`欢迎回来，${user.username}！`);
    await checkExistingPlans();
  } else {
    showToast(`欢迎，${user.username}！请完成旅行人格测试`);
    resetMBTIPage();
    showPage("mbti");
  }
}

async function onRegisterSuccess(token, user) {
  state.token = token;
  state.user = user;
  state.isLoggedIn = true;
  localStorage.setItem("luvdazi_token", token);

  clearAuthForms();
  updateAuthUI();

  showToast(`注册成功，欢迎 ${user.username}！请先完成旅行人格测试`);
  resetMBTIPage();
  showPage("mbti");
}

async function logoutUser() {
  await api.post("/api/auth/logout");
  state.token = null;
  state.user = null;
  state.isLoggedIn = false;
  state.mbtiResult = null;
  state.itinerary = null;
  state.existingPlans = [];
  state.buddyInfo = null;
  state.videoAnalysis = null;
  state.analyzedLocations = [];
  state.chatHistory = [];
  localStorage.removeItem("luvdazi_token");
  closeUserDropdown();
  updateAuthUI();

  // 关闭聊天面板
  const panel = document.getElementById("chat-panel");
  if (panel) panel.classList.remove("open");
  state.chatPanelOpen = false;

  showLoginPage();
  showToast("已退出登录");
}

function updateAuthUI() {
  const loginBtn = document.getElementById("btn-show-login");
  const userMenu = document.getElementById("user-menu");
  const chatFab = document.getElementById("chat-fab");

  if (state.isLoggedIn && state.user) {
    loginBtn.style.display = "none";
    userMenu.style.display = "block";
    document.getElementById("user-avatar-letter").textContent =
      state.user.username[0].toUpperCase();
    document.getElementById("user-display-name").textContent =
      state.user.username;
    if (chatFab) chatFab.style.display = "";
  } else {
    loginBtn.style.display = "";
    userMenu.style.display = "none";
    if (chatFab) chatFab.style.display = "none";
  }

  const saveBtn = document.getElementById("btn-save-history");
  if (saveBtn) {
    saveBtn.style.display = state.user && state.itinerary ? "" : "none";
  }
}

function toggleUserDropdown() {
  const dd = document.getElementById("user-dropdown");
  dd.classList.toggle("show");

  if (dd.classList.contains("show")) {
    setTimeout(() => {
      document.addEventListener("click", closeUserDropdownOnOutside);
    }, 0);
  }
}

function closeUserDropdown() {
  document.getElementById("user-dropdown").classList.remove("show");
  document.removeEventListener("click", closeUserDropdownOnOutside);
}

function closeUserDropdownOnOutside(e) {
  const menu = document.getElementById("user-menu");
  if (!menu.contains(e.target)) {
    closeUserDropdown();
  }
}

async function loadUserProfile() {
  const data = await api.get("/api/auth/profile");
  if (data.profile) {
    state.user = { ...state.user, ...data.profile };

    const p = data.profile;
    if (p.mbti_type) {
      document.getElementById("dropdown-mbti-type").textContent = p.mbti_type;
      document.getElementById("dropdown-mbti-name").textContent =
        p.mbti_result?.personality?.name || "";
    }

    if (p.mbti_result && p.mbti_result.mbti) {
      state.mbtiResult = p.mbti_result;
    }
  }
}

function retakeMBTI() {
  closeUserDropdown();
  state.mbtiResult = null;
  state.mbtiAnswers = {};
  // 清空下拉菜单中的MBTI显示
  document.getElementById("dropdown-mbti-type").textContent = "未测试";
  document.getElementById("dropdown-mbti-name").textContent = "完成旅行人格测试后显示";
  resetMBTIPage();
  showPage("mbti");
  showToast("重新开始旅行人格测试");
}

function showPersonaModal() {
  closeUserDropdown();

  if (!state.mbtiResult || !state.mbtiResult.mbti) {
    showToast("请先完成旅行人格测试", true);
    return;
  }

  const modal = document.getElementById("persona-modal");
  const content = document.getElementById("persona-modal-content");
  const p = state.mbtiResult.personality;
  const imageFile = p.image || "2生活家.png";

  // 描述按换行分段
  const descLines = (p.description || "").split("\n").filter((l) => l.trim());
  const descHtml = descLines.map((l) => `<p style="margin-bottom:8px;">${l.trim()}</p>`).join("");

  // 风格标签
  const styleTags = (p.style_tags || []).map((t) => `<span class="style-tag">${t}</span>`).join("");

  content.innerHTML = `
    <div style="margin: -24px; overflow: hidden; border-radius: 16px 16px 0 0;">
      <div class="result-hero">
        <img class="result-hero-img" src="assets/person/${imageFile}" alt="${p.name}"
             onerror="this.style.display='none'"
             style="max-height: 280px;">
        <div class="result-persona-overlay">
          <div class="result-emoji">${p.emoji}</div>
          <div class="result-persona-name">${p.full_name || p.name}</div>
          <div class="result-name" style="font-size: 24px;">${p.name}</div>
          <div class="result-subtitle">${p.subtitle}</div>
        </div>
      </div>
    </div>
    <div style="padding-top: 20px;">
      <div class="result-description">${descHtml}</div>
      ${styleTags ? `<div class="result-style-tags">${styleTags}</div>` : ""}
      <div class="result-strengths">
        ${p.strengths.map((s) => `<span class="strength-tag">${s}</span>`).join("")}
      </div>
    </div>
  `;

  modal.classList.remove("hidden");
}

function showTravelHistory() {
  closeUserDropdown();
  const modal = document.getElementById("history-modal");
  const content = document.getElementById("history-content");

  const history = state.user?.travel_history || [];
  if (history.length === 0) {
    content.innerHTML =
      '<p style="color: var(--text-muted); text-align: center; padding: 40px;">' +
      "暂无旅行记录<br><small>完成路线规划后可保存</small></p>";
  } else {
    content.innerHTML = history
      .map(
        (trip) => `
      <div style="padding: 16px; background: var(--bg); border-radius: var(--radius-md); margin-bottom: 12px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <strong style="font-size: 16px;">${trip.city} ${trip.days}天</strong>
          <span style="font-size: 12px; color: var(--text-muted);">${trip.date || ""}</span>
        </div>
        <div style="font-size: 13px; color: var(--text-secondary);">
          ${trip.companions ? `👥 ${trip.companions}` : ""}
          ${trip.budget ? ` · 💰 ${trip.budget}` : ""}
          ${trip.mbti_type ? ` · 🧬 ${trip.mbti_type}` : ""}
        </div>
      </div>
    `
      )
      .join("");
  }

  modal.classList.remove("hidden");
}

async function saveMBTIResult() {
  if (!state.user || !state.mbtiResult) return;
  await api.put("/api/auth/mbti", {
    mbti_type: state.mbtiResult.mbti,
    mbti_result: state.mbtiResult,
  });
}

async function saveTravelHistory() {
  if (!state.user || !state.itinerary) return;

  const data = await api.post("/api/itinerary/save", {
    city: state.tripConfig.city,
    days: state.tripConfig.days,
    companions: state.hasBuddy ? "和搭子一起" : "独自旅行",
    budget: state.tripConfig.budget ? `人均 ¥${state.tripConfig.budget}` : "",
    itinerary: state.itinerary,
  });

  if (data.error) {
    showToast(data.error, true);
    return;
  }

  if (!state.user.travel_history) state.user.travel_history = [];
  state.user.travel_history.push(data.trip);

  const btn = document.getElementById("btn-save-history");
  btn.textContent = "✅ 已保存";
  btn.classList.add("saved");

  showToast("旅行已保存到历史记录！");
}

function showToast(message, isError) {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast${isError ? " error" : ""}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.transition = "opacity 0.3s";
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ============================================
// Step 1: 旅行 MBTI 测试
// ============================================

function resetMBTIPage() {
  document.getElementById("mbti-questions").style.display = "";
  document.getElementById("mbti-result").classList.add("hidden");
  document.getElementById("mbti-result").innerHTML = "";
  state.mbtiAnswers = {};
  setMbtiHero(false);
  initMBTI();
}

/** 切换旅行人格页顶部标题：答题态 vs 结果态 */
function setMbtiHero(isResult) {
  const title = document.querySelector("#page-mbti .hero-title");
  const subtitle = document.querySelector("#page-mbti .hero-subtitle");
  if (title) title.textContent = isResult ? "你的旅行人格是……" : "先聊聊你的旅行风格";
  if (subtitle) subtitle.style.display = isResult ? "none" : "";
}

/** 从结果页返回到答题页（保留已选答案；若题目不存在则重新出题） */
function backToMbtiQuestions() {
  const questions = document.getElementById("mbti-questions");
  if (!questions || questions.innerHTML.trim() === "") {
    resetMBTIPage();
  } else {
    document.getElementById("mbti-result").classList.add("hidden");
    questions.style.display = "";
    setMbtiHero(false);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function initMBTI() {
  const data = await api.get("/api/mbti/questions");
  renderQuestions(data.questions);
}

function renderQuestions(questions) {
  const container = document.getElementById("mbti-questions");
  state.mbtiQuestions = questions;
  container.innerHTML = questions
    .map((q, idx) => {
      let optionsHtml = "";

      if (q.type === "single") {
        const letters = ["A", "B", "C", "D", "E"];
        optionsHtml = `
          <div class="question-options question-options-single">
            ${q.options
              .map(
                (opt, i) => `
              <button class="option-btn" data-qid="${q.id}" data-answer="${opt.id}"
                onclick="selectSingleAnswer(${q.id}, '${opt.id}', this)">
                <span class="option-letter">${letters[i]}</span>
                <span>${opt.text}</span>
              </button>
            `
              )
              .join("")}
          </div>
        `;
      } else if (q.type === "ranking") {
        optionsHtml = `
          <div class="question-options question-options-ranking">
            <p class="ranking-hint">拖动卡片调整顺序（从上到下：最想 → 最不想）</p>
            <div class="ranking-list" id="ranking-${q.id}">
              ${q.options
                .map(
                  (opt, i) => `
                <div class="ranking-item ranked" draggable="true" data-qid="${q.id}" data-optid="${opt.id}">
                  <span class="ranking-rank">${i + 1}</span>
                  <span class="ranking-text">${opt.text}</span>
                  <span class="ranking-drag-handle" aria-hidden="true">⠿</span>
                </div>
              `
                )
                .join("")}
            </div>
          </div>
        `;
      } else if (q.type === "slider") {
        optionsHtml = `
          <div class="question-options question-options-slider">
            <div class="slider-labels">
              <span class="slider-label-a">${q.label_a}</span>
              <span class="slider-label-b">${q.label_b}</span>
            </div>
            <div class="slider-track-wrap">
              <input type="range" class="slider-input" id="slider-${q.id}"
                min="0" max="100" value="50"
                oninput="onSliderChange(${q.id}, this.value)" />
              <div class="slider-ticks">
                <div class="slider-tick" style="left:0%">
                  <span class="slider-tick-dot"></span>
                </div>
                <div class="slider-tick" style="left:25%">
                  <span class="slider-tick-dot"></span>
                  <span class="slider-tick-label">更倾向于这边</span>
                </div>
                <div class="slider-tick" style="left:50%">
                  <span class="slider-tick-dot"></span>
                  <span class="slider-tick-label">我都要</span>
                </div>
                <div class="slider-tick" style="left:75%">
                  <span class="slider-tick-dot"></span>
                  <span class="slider-tick-label">更倾向于这边</span>
                </div>
                <div class="slider-tick" style="left:100%">
                  <span class="slider-tick-dot"></span>
                </div>
              </div>
            </div>
            <div class="slider-value slider-value-empty" id="slider-value-${q.id}">拖动圆点作答</div>
          </div>
        `;
      }

      // 题目文字：若含括号说明，把括号部分换行单独呈现
      const parenIdx = q.question.indexOf("（");
      const questionTextHtml =
        parenIdx >= 0
          ? `<div class="question-text">${q.question.slice(0, parenIdx)}<span class="question-text-hint">${q.question.slice(parenIdx)}</span></div>`
          : `<div class="question-text">${q.question}</div>`;

      return `
        <div class="question-card" id="q-${q.id}" data-question="${q.id}" data-type="${q.type}">
          <div class="question-number">Question ${idx + 1} / ${questions.length}</div>
          ${questionTextHtml}
          ${optionsHtml}
        </div>
      `;
    })
    .join("") +
    `
      <div class="mbti-submit-wrap">
        <div class="mbti-submit-hint" id="mbti-submit-hint"></div>
        <button class="btn-primary" id="btn-mbti-submit" onclick="trySubmitMBTI()">
          <span>下一步：查看结果</span>
          <span class="btn-arrow">→</span>
        </button>
      </div>
    `;

  // 排序题：默认顺序即为初始答案，用户可拖动调整
  state.rankingState = state.rankingState || {};
  questions.forEach((q) => {
    if (q.type === "ranking") {
      const order = q.options.map((o) => o.id);
      state.rankingState[q.id] = [...order];
      state.mbtiAnswers[q.id] = [...order];
      const card = document.getElementById(`q-${q.id}`);
      if (card) card.classList.add("answered");
      initRankingDrag(q.id);
    }
  });
}

function selectSingleAnswer(qid, answer, btn) {
  state.mbtiAnswers[qid] = answer;
  const card = document.getElementById(`q-${qid}`);
  card.querySelectorAll(".option-btn").forEach((b) => b.classList.remove("selected"));
  btn.classList.add("selected");
  card.classList.add("answered");
  clearUnansweredHighlight(qid);
}

/** 为某道排序题的列表绑定拖拽排序交互 */
function initRankingDrag(qid) {
  const list = document.getElementById(`ranking-${qid}`);
  if (!list) return;

  list.querySelectorAll(".ranking-item").forEach((item) => {
    item.addEventListener("dragstart", () => {
      item.classList.add("dragging");
    });
    item.addEventListener("dragend", () => {
      item.classList.remove("dragging");
      commitRanking(qid);
    });
  });

  list.addEventListener("dragover", (e) => {
    e.preventDefault();
    const dragging = list.querySelector(".ranking-item.dragging");
    if (!dragging) return;
    const after = getRankingDragAfter(list, e.clientY);
    if (after == null) {
      list.appendChild(dragging);
    } else {
      list.insertBefore(dragging, after);
    }
  });
}

/** 根据鼠标 Y 坐标，找出拖拽元素应插入到哪个元素之前 */
function getRankingDragAfter(list, y) {
  const items = [...list.querySelectorAll(".ranking-item:not(.dragging)")];
  let closest = { offset: -Infinity, element: null };
  for (const child of items) {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > closest.offset) {
      closest = { offset, element: child };
    }
  }
  return closest.element;
}

/** 拖拽结束后，按当前 DOM 顺序更新排名与答案 */
function commitRanking(qid) {
  const list = document.getElementById(`ranking-${qid}`);
  if (!list) return;

  const order = [];
  list.querySelectorAll(".ranking-item").forEach((item, idx) => {
    order.push(item.dataset.optid);
    const rankSpan = item.querySelector(".ranking-rank");
    if (rankSpan) rankSpan.textContent = idx + 1;
    item.classList.add("ranked");
  });

  state.rankingState[qid] = [...order];
  state.mbtiAnswers[qid] = [...order];
  document.getElementById(`q-${qid}`).classList.add("answered");
  clearUnansweredHighlight(qid);
}

function onSliderChange(qid, value) {
  const v = parseInt(value);
  state.mbtiAnswers[qid] = v;

  const display = document.getElementById(`slider-value-${qid}`);
  display.classList.remove("slider-value-empty"); // 用户已拖动，显示橙色结果文字
  // 五个节点：0=完全偏左 · 25=更偏左一些 · 50=我都要 · 75=更偏右一些 · 100=完全偏右
  if (v < 12.5) display.textContent = "完全偏左";
  else if (v < 37.5) display.textContent = "更偏左一些";
  else if (v <= 62.5) display.textContent = "我都要";
  else if (v < 87.5) display.textContent = "更偏右一些";
  else display.textContent = "完全偏右";

  document.getElementById(`q-${qid}`).classList.add("answered");
  clearUnansweredHighlight(qid);
}

/** 去掉某题的「未作答」高亮，并清空提示文案 */
function clearUnansweredHighlight(qid) {
  const card = document.getElementById(`q-${qid}`);
  if (card) card.classList.remove("unanswered");
  const hint = document.getElementById("mbti-submit-hint");
  if (hint) hint.textContent = "";
}

/** 判断某题是否已作答 */
function isQuestionAnswered(q) {
  const ans = state.mbtiAnswers[q.id];
  if (ans === undefined || ans === null) return false;
  if (Array.isArray(ans)) return ans.length > 0;
  return true;
}

/** 点击「查看结果」：校验全部题目，未答则跳到第一道漏答的题 */
function trySubmitMBTI() {
  const questions = state.mbtiQuestions || [];

  for (let i = 0; i < questions.length; i++) {
    const q = questions[i];
    if (!isQuestionAnswered(q)) {
      const card = document.getElementById(`q-${q.id}`);
      document.querySelectorAll(".question-card.unanswered").forEach((c) => c.classList.remove("unanswered"));
      if (card) {
        card.classList.add("unanswered");
        card.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      const hint = document.getElementById("mbti-submit-hint");
      if (hint) hint.textContent = `还有题目没有完成，请先作答第 ${i + 1} 题`;
      return;
    }
  }

  submitMBTI();
}

async function submitMBTI() {
  const data = await api.post("/api/mbti/calculate", { answers: state.mbtiAnswers });
  state.mbtiResult = data;
  renderMBTIResult(data);
  await saveMBTIResult();

  if (data.personality) {
    document.getElementById("dropdown-mbti-type").textContent = data.mbti;
    document.getElementById("dropdown-mbti-name").textContent = data.personality.name;
  }
}

function renderMBTIResult(data) {
  const container = document.getElementById("mbti-result");
  const p = data.personality;
  const imageFile = p.image || "2生活家.png";

  document.getElementById("mbti-questions").style.display = "none";
  container.classList.remove("hidden");
  setMbtiHero(true);

  // 描述按换行分段
  const descLines = (p.description || "").split("\n").filter((l) => l.trim());
  const descHtml = descLines.map((l) => `<p style="margin-bottom:8px;">${l.trim()}</p>`).join("");

  // 风格标签
  const styleTags = (p.style_tags || []).map((t) => `<span class="style-tag">${t}</span>`).join("");

  container.innerHTML = `
    <button class="btn-back" onclick="backToMbtiQuestions()">← 返回上一步</button>
    <div class="result-card">
      <div class="result-hero">
        <img class="result-hero-img" src="assets/person/${imageFile}" alt="${p.name}"
             onerror="this.style.display='none'">
        <div class="result-persona-overlay">
          <div class="result-emoji">${p.emoji}</div>
          <div class="result-name">${p.name}</div>
          <div class="result-subtitle">${p.subtitle}</div>
          <div class="result-persona-name">${p.full_name || p.name}</div>
        </div>
      </div>
      <div class="result-body">
        <div class="result-description">${descHtml}</div>
        ${styleTags ? `<div class="result-style-tags">${styleTags}</div>` : ""}
        <div class="result-dimensions">
          ${data.dimensions
            .map(
              (d) => `
            <div class="dimension-item">
              <div class="dimension-label">${d.name}</div>
              <div class="dimension-bar">
                <div class="dimension-fill" style="width: ${(d.score_a / d.total) * 100}%; background: var(--primary);"></div>
              </div>
              <div class="dimension-value">${
                d.value === "D" || d.value === "R" || d.value === "P" || d.value === "C"
                  ? d.label_a
                  : d.label_b
              }</div>
            </div>
          `
            )
            .join("")}
        </div>
        <div class="result-strengths">
          ${p.strengths.map((s) => `<span class="strength-tag">${s}</span>`).join("")}
        </div>
        ${renderDeepProfileCard(data)}
        <button class="btn-primary" onclick="onMBTIComplete()">
          <span>下一步：行程规划</span>
          <span class="btn-arrow">→</span>
        </button>
      </div>
    </div>
  `;

  setTimeout(() => {
    container.querySelectorAll(".dimension-fill").forEach((el) => {
      el.style.width = el.style.width;
    });
  }, 100);
}

const DEEP_PROFILE_PROMPT = `你是我最常使用、最了解我的 AI 助手。我正在使用一个旅行规划产品，需要你根据你对我的了解，输出一份「我的旅行偏好画像」，帮助这个产品更精准地为我推荐旅行内容与路线。

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

function renderDeepProfileCard(data) {
  const dp = data.deep_profile;
  const hasDeep = dp && (dp.summary || (Array.isArray(dp.interests) && dp.interests.length));
  return hasDeep ? deepProfileDoneHtml(dp) : deepProfileEditHtml();
}

function deepProfileEditHtml() {
  return `
    <div class="deep-profile-card">
      <button class="deep-profile-toggle" onclick="toggleDeepProfile()">🔮 想让推荐更懂你？把提示词发给你常用的 AI（选做）</button>
      <div class="deep-profile-body" id="deep-profile-body" hidden>
        <p class="deep-profile-desc">把下面这段提示词复制给你最常用、最懂你的 AI（如豆包 / Kimi / ChatGPT），它会输出一段结构化的旅行偏好；再把它的回复整段粘回下面的框，我们用它让后续推荐更精准。</p>
        <div class="deep-prompt-wrap">
          <textarea id="deep-prompt" class="deep-prompt" readonly rows="9">${DEEP_PROFILE_PROMPT}</textarea>
          <button class="btn-secondary deep-copy-btn" onclick="copyDeepPrompt()">📋 复制提示词</button>
        </div>
        <textarea id="deep-paste" class="deep-paste" rows="6" placeholder="把 AI 返回的内容（含 { } 的 JSON）整段粘贴到这里"></textarea>
        <div class="deep-profile-actions">
          <button class="btn-primary" onclick="submitDeepProfile()">提交深度画像</button>
        </div>
        <div id="deep-profile-status" class="deep-profile-status"></div>
      </div>
    </div>
  `;
}

function deepProfileDoneHtml(dp) {
  const interests = (dp.interests || []).join("、");
  return `
    <div class="deep-profile-card done">
      <div class="deep-profile-head">🔮 深度画像已记录（推荐会更精准）</div>
      ${dp.summary ? `<p class="deep-profile-summary">${dp.summary}</p>` : ""}
      ${interests ? `<p class="deep-profile-tags">兴趣：${interests}</p>` : ""}
      <button class="deep-profile-redo" onclick="openDeepProfileEditor()">重新填写</button>
    </div>
  `;
}

function toggleDeepProfile() {
  const body = document.getElementById("deep-profile-body");
  if (body) body.hidden = !body.hidden;
}

function copyDeepPrompt() {
  const ta = document.getElementById("deep-prompt");
  if (!ta) return;
  const done = () => showToast("提示词已复制，去粘给你的 AI 吧～");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(ta.value).then(done, () => {
      ta.select();
      document.execCommand("copy");
      done();
    });
  } else {
    ta.select();
    document.execCommand("copy");
    done();
  }
}

function openDeepProfileEditor() {
  const card = document.querySelector(".deep-profile-card");
  if (card) card.outerHTML = deepProfileEditHtml();
  const body = document.getElementById("deep-profile-body");
  if (body) body.hidden = false;
}

function parseDeepProfile(raw) {
  let text = raw;
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) {
    text = fence[1];
  } else {
    const brace = raw.match(/\{[\s\S]*\}/);
    if (brace) text = brace[0];
  }
  try {
    const obj = JSON.parse(text);
    if (obj && typeof obj === "object" && !Array.isArray(obj)) return obj;
  } catch (e) {
    /* ignore */
  }
  return null;
}

function submitDeepProfile() {
  const status = document.getElementById("deep-profile-status");
  const pasteEl = document.getElementById("deep-paste");
  const raw = (pasteEl && pasteEl.value.trim()) || "";
  const setErr = (msg) => {
    if (status) {
      status.textContent = msg;
      status.className = "deep-profile-status error";
    }
  };

  if (!raw) return setErr("请先粘贴 AI 返回的内容");
  const parsed = parseDeepProfile(raw);
  if (!parsed) return setErr("没能识别出 JSON，请确认把 AI 返回的内容（含大括号那段）整段粘贴进来");
  if (!state.mbtiResult) return setErr("请先完成旅行人格测试");

  state.mbtiResult.deep_profile = parsed;
  if (state.user) saveMBTIResult();
  showToast("已记录你的深度画像，推荐会更懂你～");

  const card = document.querySelector(".deep-profile-card");
  if (card) card.outerHTML = deepProfileDoneHtml(parsed);
}

async function onMBTIComplete() {
  await checkExistingPlans();
}

// ============================================
// Step 2: 行程规划
// ============================================

async function checkExistingPlans() {
  if (!state.user) {
    showNewPlanSection();
    showPage("plan");
    return;
  }

  const history = state.user.travel_history || [];
  state.existingPlans = history;

  if (history.length > 0) {
    showPlanCheckSection(history);
  } else {
    showNewPlanSection();
  }

  showPage("plan");
}

function showPlanCheckSection(history) {
  document.getElementById("plan-check-section").style.display = "";
  document.getElementById("new-plan-section").style.display = "none";

  const list = document.getElementById("existing-plans-list");
  list.innerHTML = history
    .map(
      (trip, idx) => `
    <div class="plan-card">
      <div class="plan-card-info">
        <div class="plan-card-city">${trip.city} ${trip.days}天</div>
        <div class="plan-card-meta">
          ${trip.date || ""}
          ${trip.companions ? ` · 👥 ${trip.companions}` : ""}
          ${trip.mbti_type ? ` · 🧬 ${trip.mbti_type}` : ""}
        </div>
      </div>
      <div class="plan-card-actions">
        <button class="btn-primary" style="padding: 8px 20px; font-size: 13px;" onclick="handlePlanChoice('continue', ${idx})">
          继续这个计划
        </button>
      </div>
    </div>
  `
    )
    .join("");
}

function showNewPlanSection() {
  document.getElementById("plan-check-section").style.display = "none";
  document.getElementById("new-plan-section").style.display = "";
  renderPlanPersona();
}

/** 行程规划页上方展示用户已固定的旅行者画像（一次性测试的结果） */
function renderPlanPersona() {
  const el = document.getElementById("plan-persona");
  if (!el) return;
  const r = state.mbtiResult;
  if (!r || !r.personality) {
    el.style.display = "none";
    el.innerHTML = "";
    return;
  }
  const p = r.personality;
  const img = p.image || "2生活家.png";
  el.style.display = "";
  el.innerHTML = `
    <img class="plan-persona-img" src="assets/person/${img}" alt="${p.name}" onerror="this.style.display='none'">
    <div class="plan-persona-text">
      <div class="plan-persona-label">你的旅行人格</div>
      <div class="plan-persona-name">${p.emoji || ""} ${p.name}</div>
      <div class="plan-persona-sub">${p.subtitle || ""}</div>
      <button class="plan-persona-retake" onclick="retakeMBTI()">重新测试旅行人格</button>
    </div>
  `;
}

async function handlePlanChoice(choice, planIdx) {
  if (choice === "continue" && planIdx !== undefined) {
    const plan = state.existingPlans[planIdx];
    if (plan && plan.itinerary) {
      state.tripConfig.city = plan.city;
      state.tripConfig.days = plan.days;
      showPage("itinerary");
      await renderItinerary({ itinerary: plan.itinerary, locations_used: [] });
      showToast("已加载之前的旅行计划");
    }
  } else if (choice === "new") {
    showNewPlanSection();
  }
}

// ============================================
// Step 3: 旅行搭子
// ============================================

function handleBuddyChoice(hasBuddy) {
  state.hasBuddy = hasBuddy;
  if (hasBuddy) {
    document.getElementById("buddy-input-section").style.display = "";
  } else {
    state.buddyInfo = null;
    showPage("videos");
  }
}

async function submitBuddySync() {
  const identifier = document.getElementById("buddy-identifier").value.trim();
  if (!identifier) {
    showToast("请输入搭子的用户名或UID", true);
    return;
  }

  const statusEl = document.getElementById("buddy-sync-status");
  statusEl.textContent = "正在同步...";
  statusEl.style.color = "var(--text-secondary)";

  const data = await api.post("/api/buddy/sync", { buddy_identifier: identifier });

  if (data.error) {
    statusEl.textContent = data.error;
    statusEl.style.color = "#E74C3C";
    return;
  }

  state.buddyInfo = data.buddy;
  statusEl.textContent = `已同步搭子：${data.buddy.username}`;
  statusEl.style.color = "var(--accent)";

  // 如果搭子有旅行计划，显示选择
  const sharedPlans = data.shared_plans || [];
  if (sharedPlans.length > 0) {
    const plansHtml = sharedPlans
      .map(
        (trip, idx) => `
      <div style="padding: 12px; background: var(--bg); border-radius: var(--radius-md); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
        <div>
          <strong>${trip.city || "上海"} ${trip.days || 2}天</strong>
          <span style="font-size: 12px; color: var(--text-muted); margin-left: 8px;">${trip.date || ""}</span>
        </div>
        <button class="btn-primary" style="padding: 6px 16px; font-size: 12px;"
          onclick="loadBuddyPlan(${idx})">同步此计划</button>
      </div>
    `
      )
      .join("");

    statusEl.innerHTML = `
      <div style="margin-top: 12px;">
        <div style="font-weight: 600; margin-bottom: 8px;">📋 ${data.buddy.username} 的旅行计划：</div>
        ${plansHtml}
      </div>
    `;
  } else {
    showToast(`已与 ${data.buddy.username} 同步！搭子暂无旅行计划`);
    setTimeout(() => showPage("videos"), 1000);
  }
}

/** 加载搭子的旅行计划 */
function loadBuddyPlan(planIdx) {
  if (!state.buddyInfo) return;
  // 搭子计划通过 buddy sync 接口已获取，这里直接使用
  // 实际数据存储在后端，需要额外接口获取完整计划
  showToast("正在加载搭子的计划...");
  showPage("videos");
}

// ============================================
// Step 4: 精选视频
// ============================================

/** 从文本中提取所有 URL（清洗粘贴的分享文案） */
function extractUrls(text) {
  const urlPattern = /https?:\/\/[^\s，。！？、；："'\)\]}>]+/gi;
  const matches = text.match(urlPattern) || [];
  // 去重并去除末尾标点
  const seen = new Set();
  return matches
    .map((u) => u.replace(/[，。！？、；：""''）\]}>]+$/, "").trim())
    .filter((u) => {
      if (seen.has(u)) return false;
      seen.add(u);
      return u.length > 10;
    });
}

async function analyzeVideoLinks() {
  const textarea = document.getElementById("video-links-input");
  const rawText = textarea.value.trim();

  if (!rawText) {
    showToast("请粘贴视频链接或分享文案", true);
    return;
  }

  // 清洗：从粘贴的文本中提取纯 URL
  const links = extractUrls(rawText);

  if (links.length === 0) {
    showToast("未找到有效链接，请检查粘贴内容", true);
    return;
  }

  // 回填清洗后的链接到文本框
  textarea.value = links.join("\n");
  state.videoLinks = links;
  showToast(`已识别 ${links.length} 个视频链接，开始并行分析`);

  document.getElementById("analysis-progress").style.display = "";
  document.getElementById("analysis-results").style.display = "none";
  document.getElementById("btn-analyze-videos").disabled = true;

  // 自动打开 AI 助手聊天面板，让用户边等边聊
  if (!state.chatPanelOpen) {
    toggleChatPanel();
  }
  // 发一条欢迎消息
  addChatMessage(
    "ai",
    `正在并行分析 ${links.length} 个视频，预计需要 1-2 分钟 ⏳\n\n等待期间你可以问我任何旅行问题，比如：\n- 这个城市的美食推荐\n- 适合拍照的地方\n- 当地天气和穿搭建议`,
  );

  const progressBar = document.getElementById("analysis-progress-bar");
  const progressText = document.getElementById("analysis-progress-text");
  const totalLinks = links.length;
  let progress = 0;
  const startTime = Date.now();
  const progressInterval = setInterval(() => {
    progress = Math.min(progress + Math.random() * 6, 85);
    progressBar.style.width = progress + "%";
    const elapsed = Math.round((Date.now() - startTime) / 1000);
    if (progress < 30) {
      progressText.textContent = `正在并行处理 ${totalLinks} 个视频... (${elapsed}s)`;
    } else if (progress < 60) {
      progressText.textContent = `正在下载视频并转录语音... (${elapsed}s)`;
    } else {
      progressText.textContent = `AI 正在提取景点信息... (${elapsed}s)`;
    }
  }, 1000);

  const profile = state.mbtiResult
    ? { mbti: state.mbtiResult.mbti, personality_name: state.mbtiResult.personality?.name }
    : {};

  const data = await api.post("/api/video/analyze", { urls: links, personality: profile });

  clearInterval(progressInterval);
  const totalTime = Math.round((Date.now() - startTime) / 1000);
  progressBar.style.width = "100%";
  progressText.textContent = `分析完成！用时 ${totalTime} 秒`;
  document.getElementById("btn-analyze-videos").disabled = false;

  if (data.error) {
    showToast(data.error, true);
    return;
  }

  state.videoAnalysis = data;
  state.analyzedLocations = (data.locations || []).map(loc => ({
    ...loc,
    source: loc.source || "video",
  }));

  // 通知 AI 助手分析结果
  const successCount = data.success_count || 0;
  const locationCount = data.locations?.length || 0;
  if (locationCount > 0) {
    addChatMessage(
      "ai",
      `分析完成！✅\n\n成功处理 ${successCount}/${totalLinks} 个视频，提取了 ${locationCount} 个景点。\n\n你可以继续问我关于这些景点的问题，或者点击下方按钮查看地图预览 🗺️`,
    );
  }

  setTimeout(() => {
    document.getElementById("analysis-progress").style.display = "none";
    renderAnalysisResults(data);
  }, 800);
}

function renderAnalysisResults(data) {
  const container = document.getElementById("analysis-results");
  container.style.display = "";

  if (!data.locations || data.locations.length === 0) {
    container.innerHTML = '<p style="text-align: center; color: var(--text-muted);">未能从视频中提取到有效信息</p>';
    return;
  }

  // 降级提示
  let fallbackHtml = "";
  if (data.fallback) {
    fallbackHtml = `
      <div style="text-align: center; padding: 12px; background: #FFF3CD; border-radius: var(--radius-md); margin-bottom: 16px; font-size: 13px; color: #856404;">
        ⚠️ 语音转写暂不可用，以下为演示数据
      </div>
    `;
  }

  // 错误提示
  let errorsHtml = "";
  if (data.errors && data.errors.length > 0) {
    const errorItems = data.errors
      .map((e) => {
        const url = typeof e === "string" ? e : e.url || "";
        const msg = typeof e === "string" ? "处理失败" : e.error || "处理失败";
        const shortUrl = url.length > 40 ? url.substring(0, 40) + "..." : url;
        return `<div style="font-size:12px;color:#E74C3C;margin-bottom:4px;">❌ ${shortUrl}：${msg}</div>`;
      })
      .join("");
    errorsHtml = `
      <div style="padding: 12px; background: #FDEDEC; border-radius: var(--radius-md); margin-bottom: 16px;">
        <div style="font-weight: 600; margin-bottom: 8px; color: #C0392B;">⚠️ ${data.errors.length} 个视频处理失败</div>
        ${errorItems}
        <div style="font-size: 11px; color: #999; margin-top: 8px;">提示：请确保链接是有效的抖音视频链接，且视频未被删除或设为私密</div>
      </div>
    `;
  }

  container.innerHTML = `
    <h3 style="text-align: center; margin-bottom: 20px;">🔍 AI 分析结果</h3>
    ${fallbackHtml}
    ${errorsHtml}
    <h4 style="margin-bottom: 12px; color: var(--text-secondary);">📍 提取的景点</h4>
    ${data.locations
      .map(
        (loc) => `
      <div class="analysis-card">
        <div class="analysis-card-header">
          <span class="analysis-card-emoji">📍</span>
          <span class="analysis-card-title">${loc.name}</span>
        </div>
        <div class="analysis-card-keywords">
          ${(loc.keywords || []).map((k) => `<span class="keyword-tag">${k}</span>`).join("")}
        </div>
        <div class="analysis-card-reason">${loc.reason || ""}</div>
        <div class="analysis-card-labels">
          ${(loc.labels || []).map((l) => `<span class="label-tag">${l}</span>`).join("")}
        </div>
      </div>
    `
      )
      .join("")}
    <div style="text-align: center; margin-top: 24px;">
      <button class="btn-primary" onclick="showPage('map-preview')">
        <span>查看地图预览</span>
        <span class="btn-arrow">→</span>
      </button>
    </div>
  `;
}

function skipVideoStep() {
  state.videoAnalysis = null;
  state.analyzedLocations = [];
  showPage("map-preview");
}

// ============================================
// Step 5: 地图预览
// ============================================

/** 地点类型 → 图标 + 颜色 + 标签 */
const LOC_TYPE_CONFIG = {
  food:     { emoji: "🍜", color: "#E67E22", label: "美食" },
  nature:   { emoji: "🌿", color: "#27AE60", label: "自然" },
  culture:  { emoji: "🏛️", color: "#9B59B6", label: "人文" },
  landmark: { emoji: "📍", color: "#E74C3C", label: "地标" },
  street:   { emoji: "🛍️", color: "#3498DB", label: "街区" },
};
const LOC_TYPE_DEFAULT = { emoji: "📌", color: "#FF6B35", label: "其他" };

/** 获取地点类型配置 */
function getLocTypeConf(loc) {
  return LOC_TYPE_CONFIG[loc.type] || LOC_TYPE_DEFAULT;
}

/** 出行 day → 配色板（同一天的点位序号圆使用同一种颜色，不同天彼此区分） */
const DAY_COLOR_PALETTE = [
  "#FF6B35", // Day 1 橙
  "#4A90D9", // Day 2 蓝
  "#27AE60", // Day 3 绿
  "#9B59B6", // Day 4 紫
  "#E67E22", // Day 5 橙黄
  "#16A2B8", // Day 6 青
  "#E74C3C", // Day 7 红
  "#8E5BD9", // Day 8 靛紫
];

/** 根据 day 序号（0-based）取对应的主题色 */
function getDayColor(dayIdx) {
  const i = ((dayIdx % DAY_COLOR_PALETTE.length) + DAY_COLOR_PALETTE.length) % DAY_COLOR_PALETTE.length;
  return DAY_COLOR_PALETTE[i];
}

/**
 * 生成组合式地图标记 HTML：上方为纯圆形序号徽标（不带外框），下方为内嵌 emoji 的图钉，
 * 图钉描边加粗，且与序号圆同色 —— 颜色统一由调用方传入（地图预览按类型着色，
 * 路径规划按所在 day 着色，便于区分同一天 / 不同天的点位）。
 */
function buildPinMarkerContent(num, color, emoji, { dimmed = false } = {}) {
  const dimClass = dimmed ? " map-pin-marker-dim" : "";
  return `<div class="map-pin-marker${dimClass}">
    <div class="map-pin-badge" style="background:${color};">${num}</div>
    <div class="map-pin-body" style="border-color:${color};">
      <span class="map-pin-emoji">${emoji}</span>
    </div>
  </div>`;
}

/** 生成地图标记 HTML（地图预览：按地点类型着色，选中/未选中状态区分明暗） */
function getMarkerContent(loc, idx, selected) {
  const conf = getLocTypeConf(loc);
  const color = selected ? conf.color : "#A6A6A6";
  return buildPinMarkerContent(idx + 1, color, conf.emoji, { dimmed: !selected });
}

/** 构建旅行风格画像（供地图预览提示条等复用） */
function buildTravelStyleProfile() {
  const mr = state.mbtiResult;
  if (!mr || !mr.mbti) return {};
  return {
    mbti: mr.mbti,
    personality_name: mr.personality?.name || "",
    // 旅行人格主画像的完整描述原文，发给豆包用于挑选/筛选推荐地点
    description: mr.personality?.description || "",
    di_label: mr.dimensions?.[0]?.value === "D" ? "记录表达型" : "沉浸感受型",
    rl_label: mr.dimensions?.[1]?.value === "R" ? "精致风格型" : "本地烟火型",
    ps_label: mr.dimensions?.[2]?.value === "P" ? "计划依赖型" : "灵感优先型",
    cd_label: mr.dimensions?.[3]?.value === "C" ? "覆盖打卡型" : "深度停留型",
  };
}

/**
 * 判断景点是否符合用户的旅行人格
 * @param {Object} loc - 景点对象，含 travel_style_fit / personality_fit
 * @returns {boolean}
 */
function isPersonalityMatch(loc) {
  const mbti = state.mbtiResult?.mbti;
  if (!mbti || mbti.length < 4) return true; // 无 MBTI 时默认匹配

  // AI 联网发现/筛选的地点：直接采用后端豆包基于「旅行风格主画像描述文本」
  // 判定出的 selected 结果，而不是用本地数据库才有的 travel_style_fit 维度去硬匹配
  // （否则所有 AI 发现的地点都会因缺少该字段被误判为"风格不匹配"）
  if (loc.source === "ai_discover" && typeof loc.selected === "boolean") {
    return loc.selected;
  }

  const fit = loc.travel_style_fit || loc.personality_fit || {};
  const hasStructuredFit =
    !!fit &&
    ["pace", "pref", "exp", "social"].some(
      (key) => typeof fit[key] === "string" && fit[key].trim() !== ""
    );

  // 视频/预览态景点可能暂时没有结构化风格字段，不做硬匹配拦截
  if (!hasStructuredFit) return true;

  let score = 0;

  // D=记录表达型 → pace: any/rush, I=沉浸感受型 → pace: any/slow
  const d0 = mbti[0];
  if (d0 === "D" && (fit.pace === "any" || fit.pace === "rush")) score++;
  if (d0 === "I" && (fit.pace === "any" || fit.pace === "slow")) score++;

  // R=精致风格型 → pref: any/classic, L=本地烟火型 → pref: any/hidden
  const d1 = mbti[1];
  if (d1 === "R" && (fit.pref === "any" || fit.pref === "classic")) score++;
  if (d1 === "L" && (fit.pref === "any" || fit.pref === "hidden")) score++;

  // P=计划依赖型 → exp: any/scene, S=灵感优先型 → exp: any/food
  const d2 = mbti[2];
  if (d2 === "P" && (fit.exp === "any" || fit.exp === "scene")) score++;
  if (d2 === "S" && (fit.exp === "any" || fit.exp === "food")) score++;

  // C=覆盖打卡型 → social: any/social, T=深度停留型 → social: any/solo
  const d3 = mbti[3];
  if (d3 === "C" && (fit.social === "any" || fit.social === "social")) score++;
  if (d3 === "T" && (fit.social === "any" || fit.social === "solo")) score++;

  // 匹配 3/4 维度即视为符合
  return score >= 3;
}

/** 人格筛选开关切换 */
function onPersonalityFilterToggle(checked) {
  const items = document.querySelectorAll(".map-loc-item");
  items.forEach((item) => {
    const idx = parseInt(item.dataset.idx);
    const loc = state._mapValidLocations?.[idx];
    if (!loc) return;
    const matched = isPersonalityMatch(loc);
    if (checked) {
      // 只看符合人格的：隐藏不匹配的
      item.style.display = matched ? "" : "none";
      // 不匹配的取消勾选
      const cb = item.querySelector(".loc-checkbox");
      if (!matched && cb) cb.checked = false;
    } else {
      // 显示全部
      item.style.display = "";
    }
  });
  refreshMapPreviewMarkers();
  renderMapPreviewStyleEcho();
}

/** 渲染地图预览页顶部的"旅行风格呼应"提示条 */
function renderMapPreviewStyleEcho() {
  const echoEl = document.getElementById("map-preview-style-echo");
  if (!echoEl) return;

  const mbtiResult = state.mbtiResult;
  if (!mbtiResult || !mbtiResult.mbti) {
    echoEl.classList.add("hidden");
    echoEl.innerHTML = "";
    return;
  }

  const profile = buildTravelStyleProfile();
  const personality = mbtiResult.personality || {};
  const personalityLabel = personality.full_name || personality.name || profile.mbti;
  const emoji = personality.emoji || "🧭";
  const styleTags = [profile.di_label, profile.rl_label, profile.ps_label, profile.cd_label]
    .filter(Boolean)
    .join(" · ");

  // 计算当前选中的数量（基于实际显示的 checkbox）
  const checkedBoxes = document.querySelectorAll(".loc-checkbox:checked");
  const selectedCount = checkedBoxes.length;

  // 判断数据来源
  const hasVideo = (state.analyzedLocations || []).some(l => l.source === "video");
  const totalValid = (state.analyzedLocations || []).filter(
    (loc) => loc.lat && loc.lng && !isNaN(loc.lat) && !isNaN(loc.lng)
  ).length;

  const sourceText = hasVideo
    ? `已从视频中提取 <strong>${totalValid}</strong> 个景点`
    : `已加载 <strong>${totalValid}</strong> 个精选景点`;

  echoEl.innerHTML = `
    <span class="echo-icon">${emoji}</span>
    <span>
      根据你的旅行人格——<strong>${personalityLabel}（${profile.mbti}）</strong>，
      ${sourceText}，当前选中 <strong>${selectedCount}</strong> 个「${styleTags}」风格的地点。
    </span>
  `;
  echoEl.classList.remove("hidden");
}

async function initMapPreview() {
  const listEl = document.getElementById("map-location-list");

  // 如果没有视频分析数据：优先调用「默认推荐」接口——
  // 后端会用豆包联网搜索归纳"{城市}{天数}日游攻略"中常被提及的景点/餐厅/街区，
  // 为每个地点生成真实可跳转的抖音搜索结果链接，并结合用户的旅行风格主画像
  // （把主画像描述文本发给豆包）筛选出符合偏好的地点、标记 selected + 生成推荐理由
  if (!state.analyzedLocations || state.analyzedLocations.length === 0) {
    try {
      const data = await api.post("/api/locations/default-recommend", {
        profile: buildTravelStyleProfile(),
        city: state.tripConfig.city || "上海",
        days: state.tripConfig.days || 3,
      });
      const attractions = Array.isArray(data?.attractions) ? data.attractions : [];
      if (attractions.length > 0) {
        state.analyzedLocations = attractions.map((loc, idx) => ({
          ...loc,
          id: loc.id || `ai_loc_${idx + 1}`,
          keywords: loc.keywords || loc.tags || [],
          reason: loc.reason || loc.video_hint || "",
          labels: [loc.type, loc.category].filter(Boolean),
          source: data.source === "web_search" ? "ai_discover" : "builtin",
        }));
      }
      // 后端用显式的 fallback 标志告知"豆包调用失败/不可用，已切换为本地静态库"——
      // 弹个提示让你知道当前看到的不是豆包联网搜索的实时结果，而是本地兜底数据
      if (data?.fallback) {
        showToast(data.fallback_message || "豆包 AI 联网搜索调用失败，已切换为本地静态推荐景点库", true);
      }
    } catch (e) {
      console.warn("Failed to load default-recommend locations:", e);
      showToast("豆包 AI 联网搜索调用失败，已切换为本地静态推荐景点库", true);
    }
  }

  // 兜底：默认推荐接口不可用 / 无结果时，从本地数据库加载景点
  if (!state.analyzedLocations || state.analyzedLocations.length === 0) {
    try {
      const data = await api.get(`/api/locations/list?city=${encodeURIComponent(state.tripConfig.city)}`);
      state.analyzedLocations = (data.locations || []).map(loc => ({
        ...loc,
        keywords: loc.tags || [],
        reason: loc.description || loc.tips || "",
        labels: [loc.type, loc.category].filter(Boolean),
        source: "builtin",
      }));
    } catch (e) {
      console.warn("Failed to load locations:", e);
    }
  }

  const locations = state.analyzedLocations || [];

  // 筛选有效的地点（有坐标）
  const validLocations = locations.filter(
    (loc) => loc.lat && loc.lng && !isNaN(loc.lat) && !isNaN(loc.lng)
  );

  // 保存到 state 供开关函数引用
  state._mapValidLocations = validLocations;

  // 统计人格匹配情况
  const hasMbti = !!(state.mbtiResult && state.mbtiResult.mbti);
  const matchCount = hasMbti ? validLocations.filter(l => isPersonalityMatch(l)).length : validLocations.length;
  const mismatchCount = validLocations.length - matchCount;

  if (validLocations.length > 0) {
    // 人格筛选开关（仅有 MBTI 时显示）
    const filterBarHtml = hasMbti && mismatchCount > 0 ? `
      <div class="personality-filter-bar" id="personality-filter-bar">
        <label class="filter-toggle">
          <input type="checkbox" id="personality-filter-toggle" onchange="onPersonalityFilterToggle(this.checked)">
          <span class="filter-toggle-slider"></span>
          <span class="filter-toggle-label">只看符合我风格的景点</span>
        </label>
        <span class="filter-match-info">符合 ${matchCount} · 其他 ${mismatchCount}</span>
      </div>
    ` : "";

    listEl.innerHTML = `
      ${filterBarHtml}
      <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; color: var(--text-secondary);">
          <input type="checkbox" id="select-all-locs" checked onchange="toggleAllLocations(this)"> 全选
        </label>
        <span style="font-size: 12px; color: var(--text-muted);">${validLocations.length} 个景点</span>
      </div>
      ${validLocations
        .map(
          (loc, idx) => {
            const matched = !hasMbti || isPersonalityMatch(loc);
            const checkedAttr = matched ? "checked" : "";
            const dimStyle = matched ? "" : "opacity: 0.5;";
            const badge = hasMbti && !matched
              ? `<span class="mismatch-badge">风格不匹配</span>`
              : "";
            const tConf = getLocTypeConf(loc);
            // AI（豆包）基于旅行风格主画像挑选出的地点会带有 reason（推荐理由）；
            // 同时若有真实可跳转的抖音搜索结果链接，附上跳转按钮
            const aiReasonHtml = loc.source === "ai_discover" && matched && loc.reason
              ? `<div class="map-loc-reason" style="margin-top: 4px; font-size: 12px; color: var(--text-secondary, #666);">💡 ${loc.reason}</div>`
              : "";
            const douyinLinkHtml = loc.douyin_search_url
              ? `<a href="${loc.douyin_search_url}" target="_blank" rel="noopener noreferrer"
                   style="display:inline-block; margin-top:4px; font-size:12px; color:#FE2C55; text-decoration:none;"
                   onclick="event.stopPropagation();">🔗 ${loc.link_label || `在抖音搜索「${loc.name}」相关内容`}</a>`
              : "";
            return `
        <div class="map-loc-item" data-idx="${idx}" data-loc-id="${loc.id}" style="${dimStyle}">
          <label style="display: flex; align-items: flex-start; gap: 8px; cursor: pointer;">
            <input type="checkbox" class="loc-checkbox" data-idx="${idx}" ${checkedAttr}
              onchange="onLocationToggle(${idx}, this.checked)" style="margin-top: 3px;">
            <div>
              <div class="map-loc-name"><span class="loc-type-emoji" style="color:${tConf.color};">${tConf.emoji}</span> ${loc.name} ${badge}</div>
              <div class="map-loc-keywords">${(loc.keywords || loc.tags || []).join(" · ")}</div>
              ${aiReasonHtml}
              ${douyinLinkHtml}
            </div>
          </label>
        </div>
      `;
          }
        )
        .join("")}
    `;
  } else {
    listEl.innerHTML =
      '<p style="color: var(--text-muted); text-align: center; padding: 20px;">暂无景点数据</p>';
  }

  // 渲染地图
  const container = document.getElementById("map-preview-container");
  try {
    if (typeof AMap !== "undefined") {
      // 计算中心点：使用有效坐标的平均值
      let centerLng = 121.4737,
        centerLat = 31.2304;
      if (validLocations.length > 0) {
        centerLng =
          validLocations.reduce((s, l) => s + l.lng, 0) / validLocations.length;
        centerLat =
          validLocations.reduce((s, l) => s + l.lat, 0) / validLocations.length;
      }

      state.map = new AMap.Map("map-preview-container", {
        zoom: validLocations.length > 0 ? 13 : 11,
        center: [centerLng, centerLat],
        mapStyle: "amap://styles/whitesmoke",
      });

      // 添加标记
      state.mapPreviewMarkers = [];
      validLocations.forEach((loc, idx) => {
        const marker = new AMap.Marker({
          position: [loc.lng, loc.lat],
          title: loc.name,
          anchor: "bottom-center",
          content: getMarkerContent(loc, idx, true),
        });
        marker.on("click", () => {
          const info = new AMap.InfoWindow({
            content: `<div style="padding:8px;max-width:200px;">
              <b>${loc.name}</b>
              <p style="font-size:12px;color:#666;margin:4px 0 0;">${(loc.keywords || []).join(" · ")}</p>
              ${loc.reason ? `<p style="font-size:12px;color:#444;margin:4px 0 0;">${loc.reason}</p>` : ""}
            </div>`,
            offset: new AMap.Pixel(0, -6),
          });
          info.open(state.map, [loc.lng, loc.lat]);
        });
        state.map.add(marker);
        state.mapPreviewMarkers.push(marker);
      });

      if (validLocations.length > 0) {
        state.map.setFitView(null, false, [60, 60, 60, 60]);
      }
    } else {
      container.innerHTML = `
        <div class="map-placeholder">
          <span>🗺️</span>
          <p>地图 API 未配置</p>
          <p style="font-size: 12px; color: var(--text-muted);">请在 index.html 中配置高德地图 Key</p>
        </div>
      `;
    }
  } catch (e) {
    container.innerHTML = `
      <div class="map-placeholder">
        <span>🗺️</span>
        <p>地图加载失败</p>
        <p style="font-size: 12px; color: var(--text-muted);">${e.message}</p>
      </div>
    `;
  }

  renderMapPreviewStyleEcho();
}

/** 全选/取消全选景点（仅操作可见的） */
function toggleAllLocations(checkbox) {
  document.querySelectorAll(".map-loc-item").forEach((item) => {
    if (item.style.display === "none") return; // 跳过被筛选隐藏的
    const cb = item.querySelector(".loc-checkbox");
    if (cb) cb.checked = checkbox.checked;
  });
  refreshMapPreviewMarkers();
  renderMapPreviewStyleEcho();
}

/** 单个景点筛选切换 */
function onLocationToggle(idx, checked) {
  refreshMapPreviewMarkers();
  renderMapPreviewStyleEcho();
}

/**
 * 获取用户在「地图预览」页当前勾选保留的地点（基于实际显示的 checkbox 状态），
 * 用于后续「路径规划/行程生成」环节，确保严格基于上一步用户实际选中的地点来生成，
 * 而不是无视用户的勾选直接使用全部 AI 推荐/视频提取地点。
 */
function getSelectedPreviewLocations() {
  const validLocations = state._mapValidLocations || [];
  const checkedBoxes = document.querySelectorAll(".loc-checkbox:checked");
  const selected = [];
  checkedBoxes.forEach((cb) => {
    const idx = parseInt(cb.dataset.idx, 10);
    const loc = validLocations[idx];
    if (loc) selected.push(loc);
  });
  // 同步写入 state，方便其他地方引用当前选中的地点
  state.selectedLocations = selected.map((l) => l.id).filter(Boolean);
  return selected;
}

/** 根据筛选状态刷新地图标记（切换选中/未选中样式） */
function refreshMapPreviewMarkers() {
  if (!state.map || !state.mapPreviewMarkers) return;
  const validLocations = state._mapValidLocations || [];
  state.mapPreviewMarkers.forEach((marker, idx) => {
    const loc = validLocations[idx];
    if (!loc) return;
    const cb = document.querySelector(`.loc-checkbox[data-idx="${idx}"]`);
    const selected = cb && cb.checked;
    if (selected) {
      marker.show();
      marker.setContent(getMarkerContent(loc, idx, true));
    } else {
      marker.setContent(getMarkerContent(loc, idx, false));
    }
  });
}

// ============================================
// Step 6: 路线生成
// ============================================

async function generateItinerary() {
  showPage("itinerary");

  document.getElementById("itinerary-timeline").innerHTML = `
    <div style="text-align: center; padding: 60px;">
      <div class="loader"><div class="loader-dot"></div><div class="loader-dot"></div><div class="loader-dot"></div></div>
      <p style="margin-top: 20px; color: var(--text-secondary);">AI 正在为你规划路线...</p>
    </div>
  `;

  const profile = state.mbtiResult
    ? {
        mbti: state.mbtiResult.mbti,
        personality_name: state.mbtiResult.personality.name,
        di_label: state.mbtiResult.dimensions[0]?.value === "D" ? "记录表达型" : "沉浸感受型",
        rl_label: state.mbtiResult.dimensions[1]?.value === "R" ? "精致风格型" : "本地烟火型",
        ps_label: state.mbtiResult.dimensions[2]?.value === "P" ? "计划依赖型" : "灵感优先型",
        cd_label: state.mbtiResult.dimensions[3]?.value === "C" ? "覆盖打卡型" : "深度停留型",
        deep_profile: state.mbtiResult.deep_profile || null,
      }
    : {};

  // 同行人由「是否有搭子」推导：有搭子→结伴(friends)，独自出发→solo
  const companionType = state.hasBuddy ? "friends" : "solo";
  const companionLabel = state.hasBuddy ? "和搭子一起" : "独自旅行";
  const budgetAmount = state.tripConfig.budget || 0;

  const requestData = {
    destination: state.tripConfig.city,
    days: state.tripConfig.days,
    companions: companionLabel,
    companion_type: companionType,
    budget: budgetAmount ? `人均 ¥${budgetAmount}` : "",
    budget_amount: budgetAmount,
    profile: profile,
  };

  // 优先使用用户在「地图预览」页实际勾选保留的地点——
  // 一旦存在，行程的路径规划/时间安排将严格基于这些地点生成，
  // 不再退回到 MBTI 推荐 / 数据库 ID 筛选 / 视频合并等兼容逻辑
  const previewLocations = getSelectedPreviewLocations();
  if (previewLocations.length > 0) {
    requestData.preview_locations = previewLocations;
    state._lastPreviewLocations = previewLocations; // 供"恢复初始路线"等后续操作复用
  } else {
    state._lastPreviewLocations = null;
    requestData.selected_locations = state.selectedLocations.length > 0 ? state.selectedLocations : undefined;
    if (state.videoAnalysis && state.analyzedLocations.length > 0) {
      requestData.video_locations = state.analyzedLocations;
    }
  }

  const data = await api.post("/api/itinerary/generate", requestData);

  await renderItinerary(data);

  const saveBtn = document.getElementById("btn-save-history");
  if (saveBtn) {
    saveBtn.style.display = state.user ? "" : "none";
    saveBtn.textContent = "💾 保存到旅行历史";
    saveBtn.classList.remove("saved");
  }
}

/** 渲染整趟人均花费估算与预算对比 */
function renderCostEstimate(est) {
  const el = document.getElementById("itin-cost");
  if (!el) return;
  if (!est || est.per_person == null) {
    el.style.display = "none";
    return;
  }
  const cur = est.currency || "¥";
  let html =
    `<span class="cost-main">预计人均花费 <strong>${cur}${est.per_person}</strong></span>` +
    `<span class="cost-detail">景点/餐饮 ${cur}${est.spots} · 市内交通 ${cur}${est.transport}</span>`;
  if (est.budget) {
    html +=
      est.within_budget
        ? `<span class="cost-badge cost-ok">✅ 在预算内，余 ${cur}${est.diff}</span>`
        : `<span class="cost-badge cost-over">⚠️ 超预算 ${cur}${Math.abs(est.diff)}</span>`;
  }
  el.innerHTML = html;
  el.style.display = "";
}

async function renderItinerary(data) {
  const { itinerary, locations_used } = data;

  renderCostEstimate(data.cost_estimate);

  state.routeCatalog = await loadRouteCatalog();
  state.itinerary = ensureDemoStops(cloneValue(itinerary), locations_used || [], state.routeCatalog);
  annotateItineraryStops(state.itinerary);
  state.routeLocationLookup = buildLocationLookup([...(locations_used || []), ...state.routeCatalog]);
  state.routeEditor = { interestedStops: new Set() };
  state.stopFeedbacks = {};
  state.routeVideoLookup = await loadRouteVideoLookup();

  renderItineraryTimeline();
  await renderMapShell();
}

// ============================================
// Step 7: 导出分享
// ============================================

function exportPlan(type) {
  state.exportType = type;
  if (!state.itinerary) {
    showToast("暂无旅行计划可导出", true);
    return;
  }

  if (type === "pdf") {
    exportAsPDF();
  } else if (type === "image") {
    exportAsImage();
  } else if (type === "document") {
    exportAsDocument();
  }
}

/** PDF 导出：调用浏览器打印 */
function exportAsPDF() {
  showToast("正在准备 PDF，请在打印对话框中选择'保存为 PDF'...");
  // 临时隐藏非内容元素
  const printContent = buildExportHTML();
  const win = window.open("", "_blank");
  win.document.write(`
    <!DOCTYPE html>
    <html><head>
      <meta charset="UTF-8">
      <title>一拍迹合 - 旅行计划</title>
      <style>
        body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; padding: 40px; color: #333; max-width: 800px; margin: 0 auto; }
        h1 { color: #FF6B35; border-bottom: 2px solid #FF6B35; padding-bottom: 8px; }
        h2 { color: #2c3e50; margin-top: 24px; }
        .day-section { margin-bottom: 24px; }
        .day-title { font-size: 18px; font-weight: 700; color: #FF6B35; margin-bottom: 12px; }
        .stop { padding: 12px 0; border-bottom: 1px solid #eee; }
        .stop-time { color: #888; font-size: 13px; }
        .stop-name { font-weight: 600; font-size: 16px; }
        .stop-note { color: #666; font-size: 14px; margin-top: 4px; }
        .tips { background: #f8f9fa; padding: 16px; border-radius: 8px; margin-top: 24px; }
        .footer { text-align: center; color: #aaa; font-size: 12px; margin-top: 40px; }
      </style>
    </head><body>${printContent}</body></html>
  `);
  win.document.close();
  setTimeout(() => {
    win.print();
    showToast("请在打印对话框中选择'保存为 PDF'");
  }, 500);
}

/** 图文海报导出：使用 html2canvas 截图 */
async function exportAsImage() {
  const itin = state.itinerary;
  if (!itin) {
    showToast("暂无旅行计划可导出", true);
    return;
  }

  // 找到图片导出卡片，加 loading 状态
  const cards = document.querySelectorAll(".export-card");
  const imageCard = cards[1]; // 第二个是图文海报
  if (imageCard) imageCard.classList.add("loading");

  showToast("正在生成海报，请稍候...");

  // 创建海报容器（移出视口，不影响用户）
  const wrapper = document.createElement("div");
  wrapper.style.cssText =
    "position:fixed;left:-9999px;top:0;z-index:-1;pointer-events:none;";
  wrapper.innerHTML = buildPosterHTML();
  document.body.appendChild(wrapper);

  try {
    if (typeof html2canvas === "undefined") {
      throw new Error("html2canvas 未加载");
    }

    const posterEl = wrapper.firstElementChild;
    const canvas = await html2canvas(posterEl, {
      scale: 2,
      useCORS: true,
      allowTaint: true,
      backgroundColor: null,
      logging: false,
    });

    const link = document.createElement("a");
    link.download = `一拍迹合-${(itin.summary || "旅行计划").slice(0, 10)}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
    showToast("海报已下载！");
  } catch (err) {
    console.error("海报生成失败:", err);
    // 降级：下载 HTML 文件
    const htmlContent = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>一拍迹合-旅行计划</title><style>body{margin:0;display:flex;justify-content:center;padding:20px;background:#f5f5f5;}</style></head><body>${wrapper.innerHTML}</body></html>`;
    const blob = new Blob([htmlContent], { type: "text/html;charset=utf-8" });
    const link = document.createElement("a");
    link.download = "一拍迹合-旅行计划.html";
    link.href = URL.createObjectURL(blob);
    link.click();
    showToast("海报图片生成失败，已下载 HTML 文件（可在浏览器中截图分享）", true);
  } finally {
    document.body.removeChild(wrapper);
    if (imageCard) imageCard.classList.remove("loading");
  }
}

/** 详细文档导出：下载 Markdown 文件 */
function exportAsDocument() {
  const md = buildMarkdownDocument();
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const link = document.createElement("a");
  link.download = "一拍迹合-旅行攻略.md";
  link.href = URL.createObjectURL(blob);
  link.click();
  showToast("攻略文档已下载！");
}

/** 构建导出 HTML 内容 */
function buildExportHTML() {
  const itin = state.itinerary;
  if (!itin) return "<p>暂无旅行计划</p>";

  let html = `<h1>✈️ 一拍迹合 - 旅行计划</h1>`;
  html += `<p>${itin.summary || ""}</p>`;

  (itin.days || []).forEach((day) => {
    html += `<div class="day-section"><div class="day-title">${day.title}</div>`;
    (day.items || []).forEach((item) => {
      const loc = item.location || {};
      html += `
        <div class="stop">
          <div class="stop-time">${item.time || ""}</div>
          <div class="stop-name">${loc.name || item.activity || ""}</div>
          ${item.notes ? `<div class="stop-note">💡 ${item.notes}</div>` : ""}
        </div>`;
    });
    html += `</div>`;
  });

  if (itin.tips && itin.tips.length > 0) {
    html += `<div class="tips"><h2>💡 旅行小贴士</h2><ul>`;
    itin.tips.forEach((t) => (html += `<li>${t}</li>`));
    html += `</ul></div>`;
  }

  html += `<div class="footer">由 一拍迹合 AI 生成 · ${new Date().toLocaleDateString()}</div>`;
  return html;
}

/** 构建海报 HTML（卡片式布局，750px 宽，适合手机分享） */
function buildPosterHTML() {
  const itin = state.itinerary;
  if (!itin) return "";

  const city = state.tripConfig.city || "上海";
  const days = state.tripConfig.days || 2;
  const budget = state.tripConfig.budget || 500;
  const personaName = state.mbtiResult?.personality?.name || "";
  const personaEmoji = state.mbtiResult?.personality?.emoji || "";
  const mbtiType = state.mbtiResult?.mbti || "";
  const today = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" });

  // 统计景点数量
  const totalStops = (itin.days || []).reduce((sum, d) => sum + (d.items || []).length, 0);

  // 收集所有有经纬度的点用于地图
  const allCoords = [];
  (itin.days || []).forEach((day) => {
    (day.items || []).forEach((item) => {
      const loc = item.location || {};
      if (loc.lat && loc.lng) allCoords.push({ lat: loc.lat, lng: loc.lng, name: loc.name || "" });
    });
  });

  // 构建静态地图 URL（高德）
  let mapImgSrc = "";
  if (allCoords.length > 0) {
    const centerLng = allCoords.reduce((s, c) => s + c.lng, 0) / allCoords.length;
    const centerLat = allCoords.reduce((s, c) => s + c.lat, 0) / allCoords.length;
    const markers = allCoords
      .slice(0, 20)
      .map((c, i) => `large,0xFF6B35,${i + 1}:${c.lng},${c.lat}`)
      .join("|");
    mapImgSrc = `https://restapi.amap.com/v3/staticmap?location=${centerLng.toFixed(6)},${centerLat.toFixed(6)}&zoom=12&size=710*280&markers=${markers}&key=f82fd3115909f6cda7b1378ff7b2e3cb&scale=2`;
  }

  // --- 渲染每一天的时间线 ---
  let daysHTML = "";
  const dayColors = ["#FF6B35", "#E85D75", "#7B68EE", "#20B2AA", "#FF8C42", "#6C5CE7", "#00B894"];

  (itin.days || []).forEach((day, dayIdx) => {
    const color = dayColors[dayIdx % dayColors.length];
    let stopsHTML = "";
    (day.items || []).forEach((item) => {
      const loc = item.location || {};
      const name = loc.name || item.activity || "";
      const time = item.time || "";
      const note = item.notes || "";
      const categoryEmoji = loc.category ? getCategoryEmoji(loc.category) : "📍";

      stopsHTML += `
        <div style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #f0f0f0;">
          <div style="min-width:36px;height:36px;border-radius:50%;background:${color}15;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;">${categoryEmoji}</div>
          <div style="flex:1;min-width:0;">
            <div style="font-size:13px;font-weight:600;color:#1a1a1a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${name}</div>
            <div style="display:flex;gap:8px;font-size:11px;color:#999;margin-top:2px;">
              ${time ? `<span>🕐 ${time}</span>` : ""}
              ${note ? `<span style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">💡 ${note}</span>` : ""}
            </div>
          </div>
        </div>`;
    });

    daysHTML += `
      <div style="margin-bottom:16px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
          <div style="width:28px;height:28px;border-radius:50%;background:${color};color:white;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;">${dayIdx + 1}</div>
          <div style="font-size:15px;font-weight:700;color:#1a1a1a;">${day.title || `Day ${dayIdx + 1}`}</div>
        </div>
        <div style="margin-left:36px;">${stopsHTML}</div>
      </div>`;
  });

  // --- 旅行小贴士 ---
  let tipsHTML = "";
  if (itin.tips && itin.tips.length > 0) {
    const tipItems = itin.tips.map((t) => `<li style="margin-bottom:4px;">${t}</li>`).join("");
    tipsHTML = `
      <div style="background:#FFF8F0;border-radius:12px;padding:14px 16px;margin-top:8px;">
        <div style="font-size:13px;font-weight:700;color:#FF6B35;margin-bottom:6px;">💡 旅行小贴士</div>
        <ul style="font-size:12px;color:#666;margin:0;padding-left:18px;line-height:1.6;">${tipItems}</ul>
      </div>`;
  }

  // --- 人格徽章 ---
  const personaBadge = personaName
    ? `<div style="display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,0.2);border-radius:20px;padding:4px 12px;font-size:12px;margin-top:8px;">${personaEmoji} ${personaName}${mbtiType ? ` · ${mbtiType}` : ""}</div>`
    : "";

  // --- 地图 ---
  const mapHTML = mapImgSrc
    ? `<div style="margin:16px 0;border-radius:12px;overflow:hidden;">
        <img src="${mapImgSrc}" style="width:100%;display:block;" crossorigin="anonymous" onerror="this.style.display='none'">
       </div>`
    : "";

  // --- 组装完整海报 ---
  return `
  <div style="width:750px;font-family:-apple-system,'PingFang SC','Helvetica Neue','Microsoft YaHei',sans-serif;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.15);">

    <!-- 顶部渐变区域 -->
    <div style="background:linear-gradient(135deg,#FF6B35 0%,#FF8F65 50%,#E85D75 100%);padding:32px 28px 24px;color:white;text-align:center;">
      <div style="font-size:36px;margin-bottom:4px;">✈️</div>
      <div style="font-size:26px;font-weight:800;letter-spacing:1px;">一拍迹合</div>
      <div style="font-size:14px;opacity:0.9;margin-top:6px;">${itin.summary || "你的专属旅行计划"}</div>
      ${personaBadge}
    </div>

    <!-- 行程信息条 -->
    <div style="display:flex;justify-content:center;gap:24px;padding:14px 20px;background:#FFF8F0;border-bottom:1px solid #f0e8e0;">
      <div style="text-align:center;">
        <div style="font-size:11px;color:#999;">目的地</div>
        <div style="font-size:15px;font-weight:700;color:#FF6B35;">📍 ${city}</div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:11px;color:#999;">天数</div>
        <div style="font-size:15px;font-weight:700;color:#FF6B35;">📅 ${days}天</div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:11px;color:#999;">预算</div>
        <div style="font-size:15px;font-weight:700;color:#FF6B35;">💰 ¥${budget}/人</div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:11px;color:#999;">景点</div>
        <div style="font-size:15px;font-weight:700;color:#FF6B35;">📍 ${totalStops}个</div>
      </div>
    </div>

    <!-- 地图 -->
    ${mapHTML}

    <!-- 行程时间线 -->
    <div style="padding:20px 24px;">
      <div style="font-size:16px;font-weight:700;color:#1a1a1a;margin-bottom:14px;">🗓️ 行程安排</div>
      ${daysHTML}
    </div>

    <!-- 小贴士 -->
    <div style="padding:0 24px 20px;">
      ${tipsHTML}
    </div>

    <!-- 底部 -->
    <div style="background:#f8f8f8;padding:14px 24px;text-align:center;border-top:1px solid #f0f0f0;">
      <div style="font-size:12px;color:#999;">由 一拍迹合 AI 生成 · ${today}</div>
      <div style="font-size:11px;color:#ccc;margin-top:4px;">yipaijihe.com</div>
    </div>
  </div>`;
}

/** 获取地点分类对应的 emoji */
function getCategoryEmoji(category) {
  const map = {
    景点: "🏛️", 美食: "🍜", 餐厅: "🍽️", 咖啡: "☕", 购物: "🛍️",
    酒店: "🏨", 交通: "🚇", 公园: "🌳", 寺庙: "🛕", 海滩: "🏖️",
    夜景: "🌃", 博物馆: "🏛️", 商圈: "🏬", 文创: "🎨", 拍照: "📸",
    甜品: "🍰", 酒吧: "🍸", 书店: "📚", 市场: "🛒", 地标: "🗼",
  };
  if (!category) return "📍";
  for (const [key, emoji] of Object.entries(map)) {
    if (category.includes(key)) return emoji;
  }
  return "📍";
}

/** 构建 Markdown 文档 */
function buildMarkdownDocument() {
  const itin = state.itinerary;
  if (!itin) return "# 暂无旅行计划\n";

  let md = `# ✈️ 一拍迹合 - 旅行攻略\n\n`;
  md += `${itin.summary || ""}\n\n`;
  md += `---\n\n`;

  (itin.days || []).forEach((day) => {
    md += `## ${day.title}\n\n`;
    (day.items || []).forEach((item) => {
      const loc = item.location || {};
      md += `### ${item.time || ""} ${loc.name || item.activity || ""}\n`;
      if (item.notes) md += `> 💡 ${item.notes}\n`;
      if (loc.description) md += `${loc.description}\n`;
      md += `\n`;
    });
  });

  if (itin.tips && itin.tips.length > 0) {
    md += `---\n\n## 💡 旅行小贴士\n\n`;
    itin.tips.forEach((t) => (md += `- ${t}\n`));
    md += `\n`;
  }

  md += `---\n\n*由 一拍迹合 AI 生成 · ${new Date().toLocaleDateString()}*\n`;
  return md;
}

function startNewTrip() {
  state.itinerary = null;
  state.videoAnalysis = null;
  state.analyzedLocations = [];
  state.selectedLocations = [];
  state.videoLinks = [];
  state.buddyInfo = null;
  state.chatHistory = [];
  showPage("plan");
}

// ============================================
// 工具函数
// ============================================
function formatNumber(num) {
  if (num >= 10000) return (num / 10000).toFixed(1) + "万";
  if (num >= 1000) return (num / 1000).toFixed(1) + "k";
  return num.toString();
}

// ============================================
// 路线辅助函数
// ============================================
function cloneValue(value) {
  return JSON.parse(JSON.stringify(value));
}

function annotateItineraryStops(itinerary) {
  if (!itinerary || !Array.isArray(itinerary.days)) return;
  itinerary.days.forEach((day, dayIdx) => {
    day.items = (day.items || []).map((item, itemIdx) => ({
      ...item,
      __stopId: item.__stopId || `stop-${dayIdx}-${itemIdx}-${item.location_id || item.location?.name || item.activity || "item"}`,
    }));
  });
}

function buildLocationLookup(locations) {
  return (locations || []).reduce((acc, loc) => {
    if (loc && loc.id) acc[loc.id] = loc;
    return acc;
  }, {});
}

async function loadRouteCatalog() {
  try {
    const data = await api.get(`/api/locations/list?city=${encodeURIComponent(state.tripConfig.city)}`);
    return data.locations || [];
  } catch (e) {
    console.warn("Load route catalog failed:", e);
    return [];
  }
}

function ensureDemoStops(itinerary, usedLocations, catalog) {
  if (!itinerary || !Array.isArray(itinerary.days) || itinerary.days.length === 0) return itinerary;
  const existingIds = new Set([
    ...(usedLocations || []).map((loc) => loc.id),
    ...itinerary.days.flatMap((day) => (day.items || []).map((item) => item.location_id).filter(Boolean)),
  ]);
  const stops = itinerary.days.flatMap((day) => day.items || []).filter(Boolean);
  if (stops.length >= 4) return itinerary;

  const timeSlots = ["09:30", "12:00", "15:00", "18:00", "20:00"];
  const supplements = (catalog || []).filter((loc) => loc && !existingIds.has(loc.id));
  let dayIndex = 0;
  let timeIndex = stops.length;
  while (stops.length < 4 && supplements.length > 0) {
    const loc = supplements.shift();
    const day = itinerary.days[dayIndex % itinerary.days.length];
    day.items = day.items || [];
    day.items.push({
      time: timeSlots[Math.min(timeIndex, timeSlots.length - 1)],
      activity: `探索 ${loc.name}`,
      notes: loc.tips || loc.description || "补充路线点位，便于演示地图联动和信息窗。",
      location_id: loc.id,
      location: {
        name: loc.name, lat: loc.lat, lng: loc.lng, type: loc.type,
        category: loc.category, address: loc.address, description: loc.description,
        best_time: loc.best_time, duration_min: loc.duration_min, cost_level: loc.cost_level, tips: loc.tips,
      },
    });
    existingIds.add(loc.id);
    stops.push(day.items[day.items.length - 1]);
    dayIndex += 1;
    timeIndex += 1;
  }
  return itinerary;
}

async function loadRouteVideoLookup() {
  if (Object.keys(state.routeVideoLookup || {}).length > 0) return state.routeVideoLookup;
  try {
    const data = await api.get("/api/locations/videos");
    const lookup = {};
    (data.videos || []).forEach((video) => {
      if (!video.location_id) return;
      if (!lookup[video.location_id]) lookup[video.location_id] = [];
      lookup[video.location_id].push({
        ...video,
        search_url: `https://www.douyin.com/search/${encodeURIComponent(`${video.location_name || video.title} 攻略`)}`,
      });
    });
    return lookup;
  } catch (e) {
    console.warn("Load route videos failed:", e);
    return {};
  }
}

function buildDouyinSearchUrl(name) {
  return `https://www.douyin.com/search/${encodeURIComponent(`${name} 攻略`)}`;
}

function formatNumberCompact(value) {
  if (!value && value !== 0) return "0";
  if (value >= 100000000) return `${(value / 100000000).toFixed(1)}亿`;
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`;
  return String(value);
}

function getTravelHint(location) {
  if (!location) return "地铁/步行可达，结合高德地图导航调整";
  const hints = {
    landmark: "建议地铁到达后步行前往，拍照停留时间较短",
    street: "建议地铁+步行串联周边街区，适合慢逛",
    food: "建议优先选择地铁到店，午晚高峰注意排队",
    culture: "建议公共交通前往，部分园区适合步行串联",
  };
  return hints[location.type] || "建议地铁+步行组合出行";
}

function getLocationSummary(location, item) {
  return location?.description || item?.notes || item?.activity || "根据当前路线生成的打卡点";
}

function getRouteStops() {
  if (!state.itinerary || !Array.isArray(state.itinerary.days)) return [];
  const stops = [];
  state.itinerary.days.forEach((day, dayIdx) => {
    (day.items || []).forEach((item) => {
      const location = item.location || state.routeLocationLookup[item.location_id] || {};
      const videos = state.routeVideoLookup[item.location_id] || [];
      const firstVideo = videos[0] || null;
      stops.push({
        dayIdx, dayTitle: day.title, item, location, videos,
        video: firstVideo || {
          title: `${location.name || item.activity || "打卡点"} 攻略视频`,
          author: "@抖音精选", likes: 0,
          search_url: buildDouyinSearchUrl(location.name || item.activity || "旅行打卡"),
        },
        stopId: item.__stopId, sequence: stops.length + 1,
      });
    });
  });
  return stops;
}

function isStopInterested(stopId) {
  return state.routeEditor?.interestedStops?.has(stopId);
}

function refreshItineraryView() {
  renderItineraryTimeline();
  updateMapContent();
}

/** 地图内容更新（不重建 shell，只刷新标记和路线） */
async function updateMapContent() {
  if (!state.map) {
    // 地图尚未初始化，走完整流程
    await renderMapShell();
    return;
  }

  // 清除旧的路线折线
  clearRoutePolylines();

  // 移除旧标记（通过遍历 overlays）
  const overlays = state.map.getAllOverlays("marker") || [];
  state.map.remove(overlays);

  // 重新添加标记
  const stops = getRouteStops();
  if (stops.length > 0) {
    const markers = [];
    stops.forEach((stop) => {
      const loc = stop.location || {};
      if (!loc.lng || !loc.lat) return;
      const dayColor = getDayColor(stop.dayIdx || 0);
      const conf = getLocTypeConf(loc);
      const marker = new AMap.Marker({
        position: [loc.lng, loc.lat],
        title: loc.name,
        anchor: "bottom-center",
        content: buildPinMarkerContent(stop.sequence, dayColor, conf.emoji),
      });
      marker.on("click", () => {
        focusRouteStop(stop.stopId);
        openRouteInfoWindow(stop.stopId);
      });
      markers.push(marker);
      state.map.add(marker);
    });
    if (markers.length > 0) {
      state.map.setFitView(markers, false, [60, 60, 60, 60]);
    }
  }

  // 重新绘制路线
  await drawRouteSegments(state.routeTransportMode);
}

function toggleRouteStopInterest(stopId) {
  if (!stopId) return;
  const interestedStops = state.routeEditor.interestedStops;
  if (interestedStops.has(stopId)) {
    interestedStops.delete(stopId);
    showToast("已取消感兴趣标记");
  } else {
    interestedStops.add(stopId);
    showToast("已标记为感兴趣");
  }
  renderItineraryTimeline();
  updateRouteInfoWindow();
}

// ============================================
// 景点反馈浮层
// ============================================
function openStopFeedback(stopId) {
  if (!stopId) return;
  const stops = getRouteStops();
  const stop = stops.find((s) => s.stopId === stopId);
  if (!stop) return;

  const location = stop.location || {};
  const popup = document.getElementById("stop-feedback-popup");
  const nameEl = document.getElementById("feedback-stop-name");
  const descEl = document.getElementById("feedback-stop-desc");
  const statusEl = document.getElementById("feedback-status");

  nameEl.textContent = location.name || stop.item.activity || "打卡点";
  descEl.textContent = location.description || stop.item.notes || stop.item.activity || "";
  statusEl.textContent = "";

  // 高亮已选的反馈
  const currentFeedback = state.stopFeedbacks[stopId];
  document.querySelectorAll(".feedback-btn").forEach((btn) => btn.classList.remove("selected"));
  if (currentFeedback) {
    const btn = document.querySelector(`.feedback-${currentFeedback}`);
    if (btn) btn.classList.add("selected");
  }

  state.activeFeedbackStopId = stopId;
  popup.classList.remove("hidden");
}

function closeStopFeedback() {
  const popup = document.getElementById("stop-feedback-popup");
  popup.classList.add("hidden");
  state.activeFeedbackStopId = null;
}

function submitStopFeedback(type) {
  const stopId = state.activeFeedbackStopId;
  if (!stopId) return;

  state.stopFeedbacks[stopId] = type;

  // 按钮动画
  const btn = document.querySelector(`.feedback-${type}`);
  if (btn) {
    document.querySelectorAll(".feedback-btn").forEach((b) => b.classList.remove("selected"));
    btn.classList.add("selected");
    btn.classList.add("pop");
    setTimeout(() => btn.classList.remove("pop"), 300);
  }

  // 状态提示
  const statusEl = document.getElementById("feedback-status");
  const messages = {
    like: "👍 已标记感兴趣，后续会推荐类似景点",
    must: "⭐ 已标记为必去，会优先安排",
    dislike: "👎 已记录，后续会减少此类推荐",
  };
  statusEl.textContent = messages[type] || "";

  // 更新 interestedStops（保持兼容）
  if (type === "like" || type === "must") {
    state.routeEditor.interestedStops.add(stopId);
  } else {
    state.routeEditor.interestedStops.delete(stopId);
  }

  // 1.2秒后自动关闭
  setTimeout(() => {
    closeStopFeedback();
    renderItineraryTimeline();
  }, 1200);
}

function removeRouteStop(stopId) {
  if (!stopId || !state.itinerary || !Array.isArray(state.itinerary.days)) return;
  let removed = false;
  state.itinerary.days = state.itinerary.days
    .map((day) => {
      const items = (day.items || []).filter((item) => item.__stopId !== stopId);
      if (items.length !== (day.items || []).length) removed = true;
      return { ...day, items };
    })
    .filter((day) => (day.items || []).length > 0);
  if (!removed) return;
  state.routeEditor.interestedStops.delete(stopId);
  delete state.stopFeedbacks[stopId];
  if (state.activeRouteStopId === stopId) closeRouteInfoWindow();
  if (state.activeFeedbackStopId === stopId) closeStopFeedback();
  showToast("已从路线中删除该打卡点");
  refreshItineraryView();
}

function focusRouteStop(stopId) {
  if (!stopId) return;
  const timelineItem = document.querySelector(`.timeline-item[data-stop-id="${CSS.escape(stopId)}"]`);
  if (timelineItem) {
    timelineItem.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function buildStopInfoWindow(stop) {
  const location = stop.location || {};
  const video = stop.video || {};
  return `
    <div class="map-info-window">
      <button class="map-info-close" type="button" data-close-route-window aria-label="关闭信息窗">×</button>
      <div class="map-info-title">${location.name || stop.item.activity || "打卡点"}</div>
      <div class="map-info-subtitle">${stop.dayTitle} · ${stop.item.time || "时间待定"}</div>
      <div class="map-info-summary">${getLocationSummary(location, stop.item)}</div>
      <div class="map-info-grid">
        <div><span>开放时间</span><strong>${location.best_time || stop.item.best_time || "全天"}</strong></div>
        <div><span>交通建议</span><strong>${getTravelHint(location)}</strong></div>
      </div>
      <div class="map-info-video">
        <div class="map-info-video-title">${video.title || `${location.name || stop.item.activity || "打卡点"} 攻略视频`}</div>
        <div class="map-info-video-meta">${video.author || "@抖音精选"} · ${formatNumberCompact(video.likes || 0)} 赞</div>
      </div>
      <div class="map-info-actions">
        <button type="button" data-route-action="open-feedback" data-stop-id="${stop.stopId}">💬 评价</button>
        <button type="button" class="danger" data-route-action="remove-stop" data-stop-id="${stop.stopId}">删除此点</button>
        <a href="${video.search_url || buildDouyinSearchUrl(location.name || stop.item.activity || "旅行打卡")}" target="_blank" rel="noreferrer">打开抖音搜索</a>
      </div>
    </div>
  `;
}

function getRouteInfoWindowEl() {
  return document.getElementById("route-info-window");
}

function bindTimelineInteractions() {
  const timeline = document.getElementById("itinerary-timeline");
  if (!timeline) return;
  timeline.onclick = (event) => {
    if (event.target.closest(".timeline-drag-handle")) return;
    if (event.target.closest(".time-input")) return;
    if (event.target.closest(".add-stop-btn")) return;
    const item = event.target.closest(".timeline-item[data-stop-id]");
    if (item) openStopFeedback(item.dataset.stopId);
  };
}

// ============================================
// 统一拖拽系统（交换 + 插入）
// ============================================
let _dragData = null;
let _swapTarget = null; // 当前悬停的交换目标

function bindAllDragDrop() {
  // --- 推荐池磁贴 ---
  document.querySelectorAll(".rec-tile[draggable]").forEach((tile) => {
    tile.addEventListener("dragstart", (e) => {
      tile.classList.add("dragging");
      _dragData = { type: "rec", recIdx: parseInt(tile.dataset.recIdx) };
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", "drag");
    });
    tile.addEventListener("dragend", () => {
      tile.classList.remove("dragging");
      _dragData = null;
      clearDropState();
    });
  });

  // --- 时间线景点（仅手柄触发） ---
  document.querySelectorAll(".timeline-item").forEach((item) => {
    const handle = item.querySelector("[data-drag-handle]");
    if (!handle) return;

    handle.addEventListener("mousedown", () => item.setAttribute("draggable", "true"));
    item.addEventListener("mouseup", () => item.removeAttribute("draggable"));
    item.addEventListener("mouseleave", () => {
      if (!item.classList.contains("dragging-item")) item.removeAttribute("draggable");
    });

    item.addEventListener("dragstart", (e) => {
      item.classList.add("dragging-item");
      const dayIdx = parseInt(item.dataset.dayIdx);
      const itemIdx = parseInt(item.dataset.itemIdx);
      _dragData = { type: "timeline-item", fromDayIdx: dayIdx, itemIdx, stopId: item.dataset.stopId };
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", "drag");
    });
    item.addEventListener("dragend", () => {
      item.classList.remove("dragging-item");
      item.removeAttribute("draggable");
      _dragData = null;
      clearDropState();
    });
  });

  // --- drop zone ---
  document.querySelectorAll(".day-items[data-day-idx]").forEach((container) => {
    container.addEventListener("dragover", (e) => {
      if (!_dragData) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";

      clearDropIndicators(container);

      // 判断鼠标是在某个 item 上方（交换）还是之间（插入）
      const hoverItem = getHoveredItem(container, e.clientY);
      const daySection = container.closest(".day-section");

      if (hoverItem && _dragData.type === "timeline-item") {
        // 悬停在 item 上 → 交换模式
        hoverItem.classList.add("swap-target");
        _swapTarget = hoverItem;
        if (daySection) daySection.classList.add("drag-over");
      } else {
        // 悬停在 item 之间 → 插入模式
        document.querySelectorAll(".swap-target").forEach(el => el.classList.remove("swap-target"));
        _swapTarget = null;
        const afterEl = getDropAfterElement(container, e.clientY);
        const indicator = document.createElement("div");
        indicator.className = "drop-indicator";
        if (afterEl) container.insertBefore(indicator, afterEl);
        else container.appendChild(indicator);
        if (daySection) daySection.classList.add("drag-over");
      }
    });

    container.addEventListener("dragleave", (e) => {
      if (!container.contains(e.relatedTarget)) {
        clearDropIndicators(container);
        document.querySelectorAll(".swap-target").forEach(el => el.classList.remove("swap-target"));
        _swapTarget = null;
        const daySection = container.closest(".day-section");
        if (daySection) daySection.classList.remove("drag-over");
      }
    });

    container.addEventListener("drop", (e) => {
      e.preventDefault();
      const daySection = container.closest(".day-section");
      if (daySection) daySection.classList.remove("drag-over");

      const dayIdx = parseInt(container.dataset.dayIdx);

      if (!_dragData) { clearDropState(); return; }

      // 优先判断：是否是交换
      if (_swapTarget && _dragData.type === "timeline-item") {
        const toIdx = parseInt(_swapTarget.dataset.itemIdx);
        const toDay = parseInt(_swapTarget.dataset.dayIdx);
        clearDropState();
        swapTimelineItems(_dragData.fromDayIdx, _dragData.itemIdx, toDay, toIdx);
        _dragData = null;
        return;
      }

      // 插入模式
      const afterEl = getDropAfterElement(container, e.clientY);
      const insertIdx = afterEl
        ? getItemIndexInDay(afterEl)
        : (state.itinerary?.days[dayIdx]?.items?.length || 0);
      clearDropState();

      if (_dragData.type === "rec") {
        addRecToDay(_dragData.recIdx, dayIdx, insertIdx);
      } else if (_dragData.type === "timeline-item") {
        moveTimelineItem(_dragData.fromDayIdx, _dragData.itemIdx, dayIdx, insertIdx);
      }
      _dragData = null;
    });
  });
}

/** 判断鼠标是否悬停在某个 item 上（上半/下半区域之外的中间区域） */
function getHoveredItem(container, y) {
  const items = [...container.querySelectorAll(".timeline-item:not(.dragging-item)")];
  for (const item of items) {
    const box = item.getBoundingClientRect();
    if (y >= box.top && y <= box.bottom) {
      return item;
    }
  }
  return null;
}

/** 计算插入点：返回应插在其之前的元素 */
function getDropAfterElement(container, y) {
  const items = [...container.querySelectorAll(".timeline-item:not(.dragging-item):not(.swap-target)")];
  let closest = { offset: Infinity, element: null };
  for (const child of items) {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && Math.abs(offset) < Math.abs(closest.offset)) {
      closest = { offset, element: child };
    }
  }
  return closest.element;
}

function getItemIndexInDay(el) {
  const siblings = [...el.parentElement.querySelectorAll(".timeline-item")];
  return siblings.indexOf(el);
}

function clearDropIndicators(container) {
  if (container) container.querySelectorAll(".drop-indicator").forEach(el => el.remove());
}

function clearDropState() {
  document.querySelectorAll(".drop-indicator").forEach(el => el.remove());
  document.querySelectorAll(".swap-target").forEach(el => el.classList.remove("swap-target"));
  document.querySelectorAll(".day-section.drag-over").forEach(el => el.classList.remove("drag-over"));
  _swapTarget = null;
}

// ============================================
// 交换两个景点（位置 + 时间互换）
// ============================================
function swapTimelineItems(dayA, idxA, dayB, idxB) {
  if (!state.itinerary) return;
  const itemsA = state.itinerary.days[dayA]?.items;
  const itemsB = state.itinerary.days[dayB]?.items;
  if (!itemsA || !itemsB) return;
  if (idxA < 0 || idxA >= itemsA.length || idxB < 0 || idxB >= itemsB.length) return;

  const itemA = itemsA[idxA];
  const itemB = itemsB[idxB];

  // 交换时间
  const tmpTime = itemA.time;
  itemA.time = itemB.time;
  itemB.time = tmpTime;

  // 同天：直接在数组中交换位置
  if (dayA === dayB) {
    itemsA[idxA] = itemB;
    itemsA[idxB] = itemA;
  } else {
    // 跨天：互相放到对方位置
    itemsA.splice(idxA, 1, itemB);
    itemsB.splice(idxB, 1, itemA);
  }

  renderItineraryTimeline();
  updateMapContent();
  showToast("已交换两个景点");
}

// ============================================
// 时间编辑（15分钟 select + 自动排序）
// ============================================

/** 生成 15 分钟间隔的 <option> 列表 */
function buildTimeOptions(selected) {
  const sel = selected || "09:00";
  let html = "";
  for (let h = 6; h <= 23; h++) {
    for (let m = 0; m < 60; m += 15) {
      const val = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
      html += `<option value="${val}"${val === sel ? " selected" : ""}>${val}</option>`;
    }
  }
  return html;
}

function onTimeChange(select) {
  const dayIdx = parseInt(select.dataset.dayIdx);
  const itemIdx = parseInt(select.dataset.itemIdx);
  if (!state.itinerary?.days?.[dayIdx]?.items?.[itemIdx]) return;
  state.itinerary.days[dayIdx].items[itemIdx].time = select.value;
  sortDayByTime(dayIdx);
}

/** 将时间对齐到最近的15分钟 */
function snapToQuarter(timeStr) {
  if (!timeStr) return "09:00";
  const [h, m] = timeStr.split(":").map(Number);
  const rounded = Math.round(m / 15) * 15;
  let nh = h, nm = rounded;
  if (nm >= 60) { nh += 1; nm = 0; }
  return `${String(nh).padStart(2, "0")}:${String(nm).padStart(2, "0")}`;
}

/** 对某天的景点按时间排序，乱序时自动纠正并弹 toast */
function sortDayByTime(dayIdx) {
  const day = state.itinerary?.days?.[dayIdx];
  if (!day?.items?.length) return;

  const items = day.items;
  let isSorted = true;
  for (let i = 1; i < items.length; i++) {
    if ((items[i].time || "") < (items[i - 1].time || "")) {
      isSorted = false;
      break;
    }
  }

  if (!isSorted) {
    day.items.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
    renderItineraryTimeline();
    updateMapContent();
    showToast("已按时间重新排序");
  }
}

// ============================================
// 推荐池 → 某天
// ============================================
function addRecToDay(recIdx, dayIdx, insertIdx) {
  if (!state.itinerary?.recommendations) return;
  const recs = state.itinerary.recommendations;
  if (recIdx < 0 || recIdx >= recs.length) return;

  const rec = recs[recIdx];
  const day = state.itinerary.days[dayIdx];
  if (!day) return;

  if (!day.items) day.items = [];
  const idx = Math.min(insertIdx ?? day.items.length, day.items.length);

  const existingTimes = day.items.map(i => i.time).filter(Boolean);
  const defaultTime = idx > 0 && existingTimes[idx - 1]
    ? snapToQuarter(addMinutes(existingTimes[idx - 1], 120))
    : (existingTimes[0] || "09:00");

  const newItem = {
    time: defaultTime,
    location_id: rec.location_id,
    activity: rec.activity,
    notes: rec.reason || "",
    __stopId: `stop-${dayIdx}-${Date.now()}-${rec.location_id || "rec"}`,
    location: rec.location || {},
  };

  day.items.splice(idx, 0, newItem);
  recs.splice(recIdx, 1);

  renderItineraryTimeline();
  updateMapContent();
  showToast(`已添加到 ${day.title}`);
}

// ============================================
// 已安排景点移动
// ============================================
function moveTimelineItem(fromDayIdx, fromItemIdx, toDayIdx, insertIdx) {
  if (!state.itinerary) return;
  const fromDay = state.itinerary.days[fromDayIdx];
  const toDay = state.itinerary.days[toDayIdx];
  if (!fromDay || !toDay) return;

  const items = fromDay.items || [];
  if (fromItemIdx < 0 || fromItemIdx >= items.length) return;

  if (fromDayIdx === toDayIdx) {
    // 同天：重新排列
    const [moved] = items.splice(fromItemIdx, 1);
    const adjustedIdx = Math.min(insertIdx > fromItemIdx ? insertIdx - 1 : insertIdx, items.length);
    items.splice(adjustedIdx, 0, moved);
  } else {
    const [moved] = items.splice(fromItemIdx, 1);
    const toItems = toDay.items || [];
    const idx = Math.min(insertIdx ?? toItems.length, toItems.length);
    const existingTimes = toItems.map(i => i.time).filter(Boolean);
    moved.time = idx > 0 && existingTimes[idx - 1]
      ? snapToQuarter(addMinutes(existingTimes[idx - 1], 120))
      : (existingTimes[0] || "09:00");
    toItems.splice(idx, 0, moved);
    toDay.items = toItems;
    showToast(`已移动到 ${toDay.title}`);
  }

  renderItineraryTimeline();
  updateMapContent();
}

/** 时间加分钟 */
function addMinutes(timeStr, mins) {
  if (!timeStr) return "10:00";
  const [h, m] = timeStr.split(":").map(Number);
  const total = h * 60 + m + mins;
  const nh = Math.min(Math.floor(total / 60), 23);
  const nm = total % 60;
  return `${String(nh).padStart(2, "0")}:${String(nm).padStart(2, "0")}`;
}

// ============================================
// 添加自定义景点（带数据库搜索匹配）
// ============================================
function openAddStop(dayIdx) {
  const day = state.itinerary?.days?.[dayIdx];
  if (!day) return;

  const section = document.querySelector(`.day-section[data-day-idx="${dayIdx}"]`);
  if (!section || section.querySelector(".add-stop-form")) return;

  const existingTimes = (day.items || []).map(i => i.time).filter(Boolean);
  const defaultTime = existingTimes.length > 0
    ? snapToQuarter(addMinutes(existingTimes[existingTimes.length - 1], 120))
    : "10:00";

  const formHtml = `
    <div class="add-stop-form" data-day-idx="${dayIdx}">
      <select class="add-stop-time-select">${buildTimeOptions(defaultTime)}</select>
      <div class="add-stop-input-wrap">
        <input type="text" class="add-stop-name" placeholder="输入景点名称…" autocomplete="off"
          oninput="onAddStopInput(this)" onkeydown="onAddStopKeydown(event, ${dayIdx})">
        <div class="add-stop-suggest"></div>
      </div>
      <div class="add-stop-actions">
        <button class="add-stop-confirm" onclick="confirmAddStop(${dayIdx})">添加</button>
        <button class="add-stop-cancel" onclick="closeAddStop(${dayIdx})">取消</button>
      </div>
    </div>
  `;
  section.querySelector(".add-stop-btn").insertAdjacentHTML("beforebegin", formHtml);

  // 缓存数据库景点
  if (!state._allLocationsCache) {
    state._allLocationsCache = state.routeCatalog?.length ? state.routeCatalog : [];
    if (!state._allLocationsCache.length) {
      api.get(`/api/locations/list?city=${encodeURIComponent(state.tripConfig.city)}`)
        .then(data => { state._allLocationsCache = data.locations || []; })
        .catch(() => { state._allLocationsCache = []; });
    }
  }

  section.querySelector(".add-stop-name").focus();
}

/** 输入时搜索匹配数据库景点 */
function onAddStopInput(input) {
  const form = input.closest(".add-stop-form");
  const suggestEl = form.querySelector(".add-stop-suggest");
  const query = input.value.trim().toLowerCase();

  if (!query || query.length < 1) {
    suggestEl.style.display = "none";
    suggestEl.innerHTML = "";
    return;
  }

  const allLocs = state._allLocationsCache || [];
  const matches = allLocs.filter(loc =>
    loc.name.toLowerCase().includes(query) ||
    (loc.tags || []).some(t => t.toLowerCase().includes(query)) ||
    (loc.category || "").toLowerCase().includes(query)
  ).slice(0, 6);

  if (matches.length === 0) {
    suggestEl.innerHTML = '<div class="suggest-item suggest-custom">➕ 自定义添加「' + escapeHtml(input.value.trim()) + '」</div>';
    suggestEl.style.display = "block";
    return;
  }

  suggestEl.innerHTML = matches.map((loc, i) =>
    `<div class="suggest-item" data-loc-idx="${i}" data-loc-id="${loc.id}" onclick="selectSuggestItem(this, ${dayIdxFromForm(form)})">
      <span class="suggest-name">${loc.name}</span>
      <span class="suggest-meta">${loc.category || ''} · ${(loc.tags || []).slice(0, 3).join(' ')}</span>
    </div>`
  ).join("");

  // 缓存匹配结果供选中用
  form._suggestMatches = matches;
  suggestEl.style.display = "block";
}

function dayIdxFromForm(form) {
  return parseInt(form.dataset.dayIdx);
}

/** 选中建议项 */
function selectSuggestItem(el, dayIdx) {
  const form = el.closest(".add-stop-form");
  const locId = el.dataset.locId;

  if (!locId) {
    // 自定义项，不做特殊处理
    closeSuggest(form);
    return;
  }

  const loc = (form._suggestMatches || []).find(l => l.id === locId);
  if (!loc) return;

  // 填入名称，关闭建议
  form.querySelector(".add-stop-name").value = loc.name;
  form._selectedLocation = loc;
  closeSuggest(form);
}

function closeSuggest(form) {
  const el = form.querySelector(".add-stop-suggest");
  if (el) { el.style.display = "none"; el.innerHTML = ""; }
}

/** 键盘导航 */
function onAddStopKeydown(e, dayIdx) {
  if (e.key === "Enter") { e.preventDefault(); confirmAddStop(dayIdx); }
  if (e.key === "Escape") { closeAddStop(dayIdx); }
}

function closeAddStop(dayIdx) {
  const section = document.querySelector(`.day-section[data-day-idx="${dayIdx}"]`);
  if (!section) return;
  const form = section.querySelector(".add-stop-form");
  if (form) form.remove();
}

function confirmAddStop(dayIdx) {
  const section = document.querySelector(`.day-section[data-day-idx="${dayIdx}"]`);
  if (!section) return;
  const form = section.querySelector(".add-stop-form");
  if (!form) return;

  const timeSelect = form.querySelector(".add-stop-time-select");
  const nameInput = form.querySelector(".add-stop-name");
  const name = nameInput.value.trim();
  if (!name) { nameInput.focus(); return; }

  const time = timeSelect.value;
  const day = state.itinerary.days[dayIdx];
  if (!day.items) day.items = [];

  // 如果选中了数据库景点，用完整数据
  const matchedLoc = form._selectedLocation;
  const newItem = {
    time,
    location_id: matchedLoc ? matchedLoc.id : null,
    activity: matchedLoc ? `探索${matchedLoc.name}` : name,
    notes: matchedLoc?.tips || matchedLoc?.description || "",
    __stopId: `stop-${dayIdx}-${Date.now()}-${matchedLoc?.id || "custom"}`,
    location: matchedLoc ? {
      name: matchedLoc.name, lat: matchedLoc.lat, lng: matchedLoc.lng,
      type: matchedLoc.type, category: matchedLoc.category,
      description: matchedLoc.description, tags: matchedLoc.tags,
    } : { name },
  };

  // 按时间插入
  let insertIdx = day.items.length;
  for (let i = 0; i < day.items.length; i++) {
    if ((day.items[i].time || "") > time) { insertIdx = i; break; }
  }
  day.items.splice(insertIdx, 0, newItem);

  form.remove();
  renderItineraryTimeline();
  updateMapContent();
  const tag = matchedLoc ? "（已匹配数据库）" : "";
  showToast(`已添加「${name}」${tag}`);
}

function openRouteInfoWindow(stopId) {
  const stop = getRouteStops().find((entry) => entry.stopId === stopId);
  const windowEl = getRouteInfoWindowEl();
  if (!windowEl || !stop) return;
  state.activeRouteStopId = stopId;
  windowEl.innerHTML = buildStopInfoWindow(stop);
  windowEl.classList.remove("hidden");
  windowEl.onclick = (event) => {
    const closeBtn = event.target.closest("[data-close-route-window]");
    const actionBtn = event.target.closest("[data-route-action]");
    if (closeBtn) { closeRouteInfoWindow(); return; }
    if (!actionBtn) return;
    const action = actionBtn.dataset.routeAction;
    const activeStopId = actionBtn.dataset.stopId || state.activeRouteStopId;
    if (action === "open-feedback") { closeRouteInfoWindow(); openStopFeedback(activeStopId); }
    if (action === "toggle-interest") toggleRouteStopInterest(activeStopId);
    if (action === "remove-stop") removeRouteStop(activeStopId);
  };
}

function closeRouteInfoWindow() {
  const windowEl = getRouteInfoWindowEl();
  if (windowEl) {
    windowEl.classList.add("hidden");
    windowEl.innerHTML = "";
    windowEl.onclick = null;
  }
  state.activeRouteStopId = null;
}

function updateRouteInfoWindow() {
  if (!state.activeRouteStopId) return;
  openRouteInfoWindow(state.activeRouteStopId);
}

// ============================================
// 路线规划（真实路网）
// ============================================
const TRANSPORT_MODES = [
  { key: "transfer", label: "🚇 公交", plugin: "AMap.Transfer" },
  { key: "walking",  label: "🚶 步行", plugin: "AMap.Walking"  },
  { key: "driving",  label: "🚗 驾车", plugin: "AMap.Driving"  },
  { key: "riding",   label: "🚲 骑行", plugin: "AMap.Riding"   },
];

function buildTransportSwitcher() {
  return `<div class="transport-switcher" id="transport-switcher">
    ${TRANSPORT_MODES.map((m) => `<button type="button"
      class="transport-btn${state.routeTransportMode === m.key ? " active" : ""}"
      data-mode="${m.key}">${m.label}</button>`).join("")}
  </div>`;
}

function clearRoutePolylines() {
  if (state.map && state.routePolylines.length > 0) {
    state.map.remove(state.routePolylines);
  }
  state.routePolylines = [];
}

function extractRoutePath(mode, result) {
  try {
    if (mode === "transfer") {
      const plan = (result.plans || [])[0];
      if (!plan) return null;
      if (plan.path && plan.path.length >= 2) return plan.path;
      const path = [];
      (plan.segments || []).forEach((seg) => {
        if (seg.walking) {
          let fromSteps = false;
          (seg.walking.steps || []).forEach((step) => {
            if (step.path?.length) { fromSteps = true; step.path.forEach((pt) => path.push(pt)); }
          });
          if (!fromSteps && seg.walking.path?.length) seg.walking.path.forEach((pt) => path.push(pt));
        }
        if (seg.bus?.busLines?.[0]?.path?.length) seg.bus.busLines[0].path.forEach((pt) => path.push(pt));
      });
      return path.length >= 2 ? path : null;
    } else {
      const route = (result.routes || [])[0] || result.route;
      if (!route) return null;
      const path = [];
      (route.steps || route.rides || []).forEach((step) => {
        (step.path || []).forEach((pt) => path.push(pt));
      });
      return path.length >= 2 ? path : null;
    }
  } catch (e) {
    console.error("[extractRoutePath] 解析失败:", e, result);
    return null;
  }
}

function extractRouteInfo(mode, result) {
  try {
    if (mode === "transfer") {
      const plan = (result.plans || [])[0];
      return { time: plan?.time || 0, distance: plan?.distance || 0 };
    } else {
      const route = (result.routes || [])[0] || result.route;
      return { time: route?.time || 0, distance: route?.distance || 0 };
    }
  } catch (_) {
    return { time: 0, distance: 0 };
  }
}

function calcStraightDist(from, to) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dlat = toRad(to.lat - from.lat);
  const dlng = toRad(to.lng - from.lng);
  const a = Math.sin(dlat / 2) ** 2 + Math.cos(toRad(from.lat)) * Math.cos(toRad(to.lat)) * Math.sin(dlng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

let _routeInfoWindow = null;
function showRouteSegmentInfo(lnglat, info) {
  if (!_routeInfoWindow) _routeInfoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -6) });
  const modeEmoji = { transfer: "🚇", walking: "🚶", driving: "🚗", riding: "🚲" };
  let content;
  if (info.isFallback) {
    const suggestion = info.distMeters < 1500 ? "距离较近，推荐 🚶 步行或 🚲 骑行" : `暂无${info.modeLabel}路线，可切换其他交通方式`;
    content = `<div class="route-seg-popup route-seg-fallback">
      <div class="route-seg-tip">💡 ${suggestion}</div>
      <div class="route-seg-dist">直线距离约 ${(info.distMeters / 1000).toFixed(2)} 公里</div>
    </div>`;
  } else {
    const mins = Math.max(1, Math.round(info.time / 60));
    const km = (info.distance / 1000).toFixed(1);
    content = `<div class="route-seg-popup">
      <div class="route-seg-time">${modeEmoji[info.mode] || "🗺️"} 预计用时 <strong>${mins} 分钟</strong></div>
      <div class="route-seg-dist">距离约 ${km} 公里</div>
    </div>`;
  }
  _routeInfoWindow.setContent(content);
  _routeInfoWindow.open(state.map, lnglat);
}

function queryRouteSegment(from, to, mode) {
  return new Promise((resolve) => {
    const modeInfo = TRANSPORT_MODES.find((m) => m.key === mode) || TRANSPORT_MODES[0];
    AMap.plugin([modeInfo.plugin], () => {
      try {
        const city = state.tripConfig?.city || "上海";
        const origin = [from.lng, from.lat];
        const dest = [to.lng, to.lat];
        let planner;
        if (mode === "transfer") planner = new AMap.Transfer({ city });
        else if (mode === "walking") planner = new AMap.Walking();
        else if (mode === "driving") planner = new AMap.Driving();
        else planner = new AMap.Riding();
        planner.search(origin, dest, (status, result) => {
          if (status === "complete") {
            const path = extractRoutePath(mode, result);
            const info = extractRouteInfo(mode, result);
            resolve(path ? { path, ...info } : null);
          } else {
            console.error(`[route/${mode}] status="${status}"`, result);
            resolve(null);
          }
        });
      } catch (e) {
        console.error("[queryRouteSegment] 异常:", e);
        resolve(null);
      }
    });
  });
}

async function drawRouteSegments(mode) {
  if (!state.map || !state.itinerary?.days) return;
  const dayColors = ["#FF6B35", "#3498DB", "#2ECC71"];
  const modeLabel = { transfer: "公交", walking: "步行", driving: "驾车", riding: "骑行" };

  for (let dayIdx = 0; dayIdx < state.itinerary.days.length; dayIdx++) {
    const day = state.itinerary.days[dayIdx];
    const color = dayColors[dayIdx % dayColors.length];
    const items = (day.items || []).filter((item) => item.location?.lat && item.location?.lng);
    for (let i = 0; i < items.length - 1; i++) {
      const from = items[i].location;
      const to = items[i + 1].location;
      if (i > 0) await new Promise((r) => setTimeout(r, 350));
      const result = await queryRouteSegment(from, to, mode);
      if (result && result.path?.length >= 2) {
        const polyline = new AMap.Polyline({
          path: result.path, strokeColor: color, strokeWeight: 5, strokeOpacity: 0.85,
          lineJoin: "round", lineCap: "round",
        });
        polyline.on("click", (e) => showRouteSegmentInfo(e.lnglat, { mode, time: result.time, distance: result.distance }));
        state.map.add(polyline);
        state.routePolylines.push(polyline);
      } else {
        const distMeters = calcStraightDist(from, to);
        const polyline = new AMap.Polyline({
          path: [[from.lng, from.lat], [to.lng, to.lat]],
          strokeColor: color, strokeWeight: 3, strokeOpacity: 0.45,
          strokeStyle: "dashed", strokeDasharray: [12, 6], lineJoin: "round", lineCap: "round",
        });
        polyline.on("click", (e) => showRouteSegmentInfo(e.lnglat, { isFallback: true, mode, modeLabel: modeLabel[mode] || "", distMeters }));
        state.map.add(polyline);
        state.routePolylines.push(polyline);
      }
    }
  }
}

async function switchTransportMode(mode) {
  if (mode === state.routeTransportMode) return;
  state.routeTransportMode = mode;
  document.querySelectorAll(".transport-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });
  clearRoutePolylines();
  await drawRouteSegments(mode);
}

// ============================================
// 高德地图（增强版）
// ============================================
function renderItineraryTimeline() {
  const itinerary = state.itinerary;
  const summaryEl = document.getElementById("itin-summary");
  const timeline = document.getElementById("itinerary-timeline");
  const recPool = document.getElementById("rec-pool");
  const recTiles = document.getElementById("rec-pool-tiles");
  if (!summaryEl || !timeline) return;

  summaryEl.textContent = itinerary?.summary || "";

  if (!itinerary || !Array.isArray(itinerary.days) || itinerary.days.length === 0) {
    timeline.innerHTML = `
      <div class="map-placeholder map-empty-state">
        <span>🗺️</span>
        <p>暂无可展示的路线</p>
        <p style="font-size: 12px; color: var(--text-muted);">请重新生成路线</p>
      </div>
    `;
    if (recPool) recPool.style.display = "none";
    return;
  }

  // 渲染每天的行程
  timeline.innerHTML = itinerary.days
    .map((day, dayIdx) => {
      const visibleItems = (day.items || []).filter(Boolean);
      return `
    <div class="day-section" data-day-idx="${dayIdx}">
      <div class="day-title">${day.title}</div>
      <div class="day-items" data-day-idx="${dayIdx}">
      ${visibleItems.length === 0
        ? '<div class="day-empty-hint" style="text-align:center;padding:20px;color:var(--text-muted);font-size:13px;">拖拽推荐景点到这里</div>'
        : visibleItems
          .map((item, itemIdx) => {
            const location = item.location || state.routeLocationLookup[item.location_id] || {};
            const feedback = state.stopFeedbacks[item.__stopId];
            const feedbackHtml = feedback
              ? `<div class="timeline-feedback ${feedback}">${feedback === 'like' ? '👍 感兴趣' : feedback === 'must' ? '⭐ 必去' : '👎 已跳过'}</div>`
              : '';
            return `
          <div class="timeline-item ${feedback ? 'has-feedback' : ''}"
               data-stop-id="${item.__stopId}" data-day-idx="${dayIdx}" data-item-idx="${itemIdx}">
            <div class="timeline-drag-handle" data-drag-handle title="拖拽排序">⠿</div>
            <div class="timeline-time-edit">
              <select class="time-select"
                data-stop-id="${item.__stopId}" data-day-idx="${dayIdx}" data-item-idx="${itemIdx}"
                onchange="onTimeChange(this)" onclick="event.stopPropagation()">
                ${buildTimeOptions(item.time)}
              </select>
            </div>
            <div class="timeline-dot"></div>
            <div class="timeline-content">
              <div class="timeline-name">${location.name || item.activity}</div>
              <div class="timeline-activity">${item.activity || "打卡点"}</div>
              ${item.notes ? `<div class="timeline-note">💡 ${item.notes}</div>` : ""}
              ${feedbackHtml}
            </div>
          </div>
        `;
          })
          .join("")}
      </div>
      <button class="add-stop-btn" onclick="openAddStop(${dayIdx})" title="添加景点">
        <span class="add-stop-icon">＋</span>
        <span class="add-stop-label">添加景点</span>
      </button>
    </div>
  `;
    })
    .join("");

  // 渲染推荐池
  const recs = itinerary.recommendations || [];
  if (recs.length > 0 && recPool && recTiles) {
    recPool.style.display = "";
    recTiles.innerHTML = recs
      .map((rec, idx) => {
        const location = rec.location || state.routeLocationLookup[rec.location_id] || {};
        const name = location.name || rec.activity || "推荐景点";
        const reason = rec.reason || location.description || "";
        return `
        <div class="rec-tile" draggable="true" data-rec-idx="${idx}" title="${reason}">
          <span class="rec-tile-icon">📍</span>
          <div class="rec-tile-info">
            <div class="rec-tile-name">${name}</div>
            ${reason ? `<div class="rec-tile-reason">${reason}</div>` : ''}
          </div>
          <span class="rec-tile-handle">⠿</span>
        </div>
      `;
      })
      .join("");
  } else if (recPool) {
    recPool.style.display = "none";
  }

  bindTimelineInteractions();
  bindAllDragDrop();
}

async function renderMapShell() {
  const container = document.getElementById("map-container");
  if (!container) return;

  // 销毁旧地图实例，防止内存泄漏
  if (state.map) {
    try { state.map.destroy(); } catch (_) {}
    state.map = null;
  }
  state.routePolylines = [];
  _routeInfoWindow = null;

  container.innerHTML = `
    <div class="map-shell">
      <div class="map-panel-header">
        <div>
          ${buildTransportSwitcher()}
          <h2>可编辑旅行路线</h2>
          <p>点击地图点位打开浮层信息窗，右上角可关闭。</p>
        </div>
        <button class="route-reset-btn" id="btn-reset-route" type="button">恢复初始路线</button>
      </div>
      <div class="map-stage">
        <div id="amap" class="amap-canvas"></div>
        <div id="route-info-window" class="route-info-window hidden"></div>
      </div>
    </div>
  `;

  // 交通方式切换
  const switcher = document.getElementById("transport-switcher");
  if (switcher) {
    switcher.addEventListener("click", (e) => {
      const btn = e.target.closest(".transport-btn[data-mode]");
      if (btn) switchTransportMode(btn.dataset.mode);
    });
  }

  // 恢复初始路线
  const resetBtn = document.getElementById("btn-reset-route");
  if (resetBtn) {
    resetBtn.onclick = async () => {
      if (!state.itinerary) return;
      const budgetAmount = state.tripConfig.budget || 0;
      const resetRequest = {
        destination: state.tripConfig.city,
        days: state.tripConfig.days,
        companions: state.hasBuddy ? "和搭子一起" : "独自旅行",
        companion_type: state.hasBuddy ? "friends" : "solo",
        budget: budgetAmount ? `人均 ¥${budgetAmount}` : "",
        budget_amount: budgetAmount,
        profile: state.mbtiResult ? { mbti: state.mbtiResult.mbti, personality_name: state.mbtiResult.personality.name, deep_profile: state.mbtiResult.deep_profile || null } : {},
      };
      // 与生成行程时保持一致：优先沿用用户在地图预览页选中的地点
      if (state._lastPreviewLocations && state._lastPreviewLocations.length > 0) {
        resetRequest.preview_locations = state._lastPreviewLocations;
      } else {
        resetRequest.selected_locations = state.selectedLocations.length > 0 ? state.selectedLocations : undefined;
      }
      const data = await api.post("/api/itinerary/generate", resetRequest);
      if (!data.error) await renderItinerary(data);
    };
  }

  // 初始化地图
  try {
    if (typeof AMap === "undefined") {
      document.getElementById("amap").innerHTML = `
        <div class="map-placeholder">
          <span>🗺️</span>
          <p>地图 API 未配置</p>
          <p style="font-size: 12px; color: var(--text-muted);">请在 index.html 中配置高德地图 Key</p>
        </div>
      `;
      return;
    }

    state.map = new AMap.Map("amap", {
      zoom: 12,
      center: [121.4737, 31.2304],
      mapStyle: "amap://styles/whitesmoke",
    });

    state.routePolylines = [];

    const stops = getRouteStops();
    if (stops.length > 0) {
      const markers = [];
      stops.forEach((stop) => {
        const loc = stop.location || {};
        const dayColor = getDayColor(stop.dayIdx || 0);
        const conf = getLocTypeConf(loc);
        const marker = new AMap.Marker({
          position: [loc.lng, loc.lat],
          title: loc.name,
          anchor: "bottom-center",
          content: buildPinMarkerContent(stop.sequence, dayColor, conf.emoji),
        });
        marker.on("click", () => {
          focusRouteStop(stop.stopId);
          openRouteInfoWindow(stop.stopId);
        });
        markers.push(marker);
        state.map.add(marker);
      });
      state.map.setFitView(markers, false, [60, 60, 60, 60]);
    }

    await drawRouteSegments(state.routeTransportMode);
  } catch (e) {
    console.error("Map init error:", e);
    container.innerHTML = `
      <div class="map-placeholder">
        <span>🗺️</span>
        <p>地图加载失败</p>
        <p style="font-size: 12px; color: var(--text-muted);">${e.message}</p>
      </div>
    `;
  }
}

// ============================================
// 行程规划页面事件绑定
// ============================================
function initPlanPage() {
  const daysInput = document.getElementById("plan-days-input");
  if (daysInput) {
    const clampDays = (raw) => {
      let v = parseInt(raw, 10);
      if (isNaN(v)) return null;
      if (v < 1) v = 1;
      if (v > 30) v = 30;
      return v;
    };
    daysInput.addEventListener("input", () => {
      const v = clampDays(daysInput.value);
      if (v !== null) state.tripConfig.days = v;
    });
    daysInput.addEventListener("blur", () => {
      const v = clampDays(daysInput.value);
      const days = v === null ? 1 : v;
      daysInput.value = days;
      state.tripConfig.days = days;
    });
  }

  const budgetInput = document.getElementById("plan-budget-input");
  if (budgetInput) {
    const clampBudget = (raw) => {
      let v = parseInt(raw, 10);
      if (isNaN(v)) return null;
      if (v < 0) v = 0;
      if (v > 100000) v = 100000;
      return v;
    };
    budgetInput.addEventListener("input", () => {
      const v = clampBudget(budgetInput.value);
      if (v !== null) state.tripConfig.budget = v;
    });
    budgetInput.addEventListener("blur", () => {
      const v = clampBudget(budgetInput.value);
      const budget = v === null ? 0 : v;
      budgetInput.value = budget;
      state.tripConfig.budget = budget;
    });
  }

  document.getElementById("btn-to-buddy").addEventListener("click", () => showPage("buddy"));
}

// ============================================
// 按钮事件绑定
// ============================================
function initButtons() {
  document.getElementById("btn-generate-plan").addEventListener("click", () => generateItinerary());
  document.getElementById("btn-to-export").addEventListener("click", () => {
    showPage("export");
  });
}

// ============================================
// 应用初始化
// ============================================
document.addEventListener("DOMContentLoaded", async () => {
  initPlanPage();
  initButtons();
  initChatPanel();

  setTimeout(() => {
    document.getElementById("loading-overlay").classList.add("hidden");
  }, 600);

  if (state.token) {
    try {
      const data = await api.get("/api/auth/profile");
      if (data.profile) {
        state.user = data.profile;
        state.isLoggedIn = true;

        if (data.profile.mbti_result && data.profile.mbti_result.mbti) {
          state.mbtiResult = data.profile.mbti_result;
        }

        updateAuthUI();

        if (state.mbtiResult) {
          await checkExistingPlans();
        } else {
          resetMBTIPage();
          showPage("mbti");
        }
      } else {
        state.token = null;
        localStorage.removeItem("luvdazi_token");
        showLoginPage();
      }
    } catch (e) {
      state.token = null;
      localStorage.removeItem("luvdazi_token");
      showLoginPage();
    }
  } else {
    showLoginPage();
  }
});
