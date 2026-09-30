import { state, bus, loadDraft, applyDraft } from "./core/state.js";
import { startRouter, navigate, ROUTES, parseHash, replaceHash } from "./core/router.js";
import { restoreSession, logout } from "./services/auth.js";
import { initHeader } from "./ui/header.js";
import { initChat } from "./ui/chat.js";
import { toast } from "./ui/toast.js";

async function boot() {
  initHeader();
  initChat();

  // 会话过期（任意接口 401）→ 回登录页
  bus.on("auth:expired", async () => {
    await logout({ remote: false });
    navigate("login");
    toast("登录已过期，请重新登录", { error: true });
  });

  await restoreSession();

  // 刷新页面后恢复上次的行程草稿（登录用户）
  const draft = loadDraft();
  if (draft) applyDraft(draft);

  // 未指定 hash 时按状态选择落点
  if (!parseHash() || location.hash === "#/" || !location.hash) {
    const target = !state.user ? "login" : !state.persona ? "persona" : draft?.itinerary?.days?.length ? "itinerary" : "plan";
    replaceHash("#" + ROUTES[target].path);
  }

  await startRouter();

  const splash = document.getElementById("splash");
  splash.classList.add("is-done");
  setTimeout(() => splash.remove(), 600);
}

boot().catch((e) => {
  console.error(e);
  document.getElementById("splash")?.remove();
  document.getElementById("view").textContent = "应用启动失败，请刷新页面重试。";
});
