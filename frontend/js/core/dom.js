/**
 * 极简 DOM 工具。所有动态文本都走 textContent，天然免疫 XSS
 * （旧版靠模板字符串 + innerHTML，LLM / 用户输入没有转义）。
 */

const SVG_NS = "http://www.w3.org/2000/svg";
const SVG_TAGS = new Set(["svg", "path", "circle", "rect", "g", "line", "polyline", "polygon", "text", "defs", "filter", "use", "ellipse"]);

/** 以属性形式设置的布尔/值属性之外，这些必须走 property */
const PROPS = new Set(["value", "checked", "disabled", "selected", "indeterminate", "readOnly", "hidden", "open"]);

export function h(tag, props, ...children) {
  const el = SVG_TAGS.has(tag) ? document.createElementNS(SVG_NS, tag) : document.createElement(tag);
  if (props) {
    for (const [key, val] of Object.entries(props)) {
      if (val == null || val === false) continue;
      if (key === "class" || key === "className") el.setAttribute("class", Array.isArray(val) ? val.filter(Boolean).join(" ") : val);
      else if (key === "style" && typeof val === "object") {
        for (const [k, v] of Object.entries(val)) k.startsWith("--") ? el.style.setProperty(k, v) : (el.style[k] = v);
      } else if (key === "dataset") Object.assign(el.dataset, val);
      else if (key.startsWith("on") && typeof val === "function") el.addEventListener(key.slice(2).toLowerCase(), val);
      else if (PROPS.has(key)) el[key] = val;
      else el.setAttribute(key, val === true ? "" : String(val));
    }
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false || c === true) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function clear(el) {
  el.replaceChildren();
  return el;
}

export function mountInto(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c != null && c !== false));
  return el;
}

export function debounce(fn, ms = 250) {
  let t;
  const d = (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
  d.cancel = () => clearTimeout(t);
  d.flush = (...a) => {
    clearTimeout(t);
    fn(...a);
  };
  return d;
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const uid = (p = "id") => `${p}-${Math.random().toString(36).slice(2, 9)}`;
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** 事件委托：root 内匹配 selector 的元素触发 */
export function delegate(root, type, selector, handler) {
  const fn = (e) => {
    const t = e.target.closest?.(selector);
    if (t && root.contains(t)) handler(e, t);
  };
  root.addEventListener(type, fn);
  return () => root.removeEventListener(type, fn);
}

/** 收集清理函数，页面卸载时统一调用 */
export function createDisposer() {
  const fns = [];
  return {
    add(fn) {
      fns.push(fn);
      return fn;
    },
    listen(target, type, handler, opts) {
      target.addEventListener(type, handler, opts);
      fns.push(() => target.removeEventListener(type, handler, opts));
    },
    dispose() {
      while (fns.length) {
        try {
          fns.pop()();
        } catch (e) {
          console.warn("dispose failed", e);
        }
      }
    },
  };
}

/** 在可安全信任的静态 SVG 字符串上创建元素（仅用于内置图标） */
export function fromSvg(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup.trim();
  return t.content.firstElementChild;
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = h("textarea", { style: { position: "fixed", opacity: 0 } });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {}
    ta.remove();
    return ok;
  }
}
