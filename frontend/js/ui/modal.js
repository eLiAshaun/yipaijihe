import { h, $$ } from "../core/dom.js";
import { icon } from "../core/icons.js";

const FOCUSABLE = 'a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])';

/**
 * 通用弹窗：Esc 关闭、点遮罩关闭、焦点陷阱、关闭后焦点归还、锁滚动。
 * openModal({ title, body: Node, width, footer?: Node }) → { close, el }
 */
export function openModal({ title, body, footer, width = 560, onClose } = {}) {
  const opener = document.activeElement;
  const titleId = `m-${Math.random().toString(36).slice(2, 7)}`;

  const close = () => {
    document.removeEventListener("keydown", onKey, true);
    backdrop.remove();
    if (!document.querySelector(".modal-backdrop")) document.documentElement.style.overflow = "";
    opener?.focus?.();
    onClose?.();
  };

  const modal = h(
    "div",
    { class: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, style: { "--w": `${width}px` } },
    h("div", { class: "modal-head" }, h("h2", { id: titleId }, title), h("button", { class: "icon-btn", type: "button", "aria-label": "关闭", onclick: close }, icon("x"))),
    h("div", { class: "modal-body" }, body),
    footer && h("div", { class: "modal-foot" }, footer)
  );
  const backdrop = h("div", { class: "modal-backdrop", onmousedown: (e) => e.target === backdrop && close() }, modal);

  function onKey(e) {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    } else if (e.key === "Tab") {
      const nodes = $$(FOCUSABLE, modal).filter((n) => n.offsetParent !== null);
      if (!nodes.length) return;
      const [first, last] = [nodes[0], nodes[nodes.length - 1]];
      if (e.shiftKey && document.activeElement === first) (e.preventDefault(), last.focus());
      else if (!e.shiftKey && document.activeElement === last) (e.preventDefault(), first.focus());
    }
  }

  document.addEventListener("keydown", onKey, true);
  document.getElementById("modal-root").append(backdrop);
  document.documentElement.style.overflow = "hidden";
  (modal.querySelector("[autofocus]") || modal.querySelector(".modal-body " + FOCUSABLE) || modal.querySelector(".icon-btn")).focus();
  return { close, el: modal };
}

/** 确认对话框 → Promise<boolean> */
export function confirmDialog({ title = "确认操作", message = "", confirmText = "确定", cancelText = "取消", danger = false } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => {
      if (done) return;
      done = true;
      m.close();
      resolve(v);
    };
    const m = openModal({
      title,
      width: 420,
      onClose: () => !done && ((done = true), resolve(false)),
      body: h("p", { class: "muted" }, message),
      footer: h(
        "div",
        { class: "modal-actions" },
        h("button", { class: "btn btn--quiet", type: "button", onclick: () => finish(false) }, cancelText),
        h("button", { class: ["btn", danger ? "btn--primary" : "btn--ink"], type: "button", autofocus: true, onclick: () => finish(true) }, confirmText)
      ),
    });
  });
}
