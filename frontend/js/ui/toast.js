import { h } from "../core/dom.js";
import { icon } from "../core/icons.js";

let root;

/** toast("已保存") / toast("出错了", { error: true }) */
export function toast(message, { error = false, ms = 3200 } = {}) {
  root ||= document.getElementById("toasts");
  const el = h("div", { class: ["toast", error && "is-error"], role: error ? "alert" : "status" }, icon(error ? "alert" : "check"), h("span", null, message));
  root.append(el);
  // 最多同时 3 条
  while (root.children.length > 3) root.firstElementChild.remove();
  setTimeout(() => {
    el.classList.add("is-leaving");
    setTimeout(() => el.remove(), 260);
  }, ms);
}

export const toastError = (e, fallback = "出了点小问题，请重试") => toast(e?.message || fallback, { error: true });
