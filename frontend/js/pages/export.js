import { h, mountInto, copyText } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { state, resetTrip } from "../core/state.js";
import { isoDate } from "../services/planner.js";
import { buildPoster, downloadPoster, printPdf, downloadIcs, downloadMarkdown, shareText } from "../services/exporters.js";
import { shareTrip, unshareTrip, saveTrip } from "../services/trips.js";
import { toast, toastError } from "../ui/toast.js";
import { confirmDialog } from "../ui/modal.js";

export default {
  title: () => "导出分享",

  mount(root, ctx) {
    const page = h("section", { class: "page page--wide" });
    root.append(page);

    // ------ 海报预览（缩放展示，导出时另建一份原尺寸）------
    const previewHost = h("div", { class: "poster-preview" });
    const stage = h("div", { class: "poster-stage" });
    previewHost.append(stage);
    const fit = () => {
      const poster = stage.firstElementChild;
      if (!poster) return;
      const k = Math.min(1, previewHost.clientWidth / 750);
      stage.style.transform = `scale(${k})`;
      stage.style.height = `${poster.offsetHeight * k}px`;
      stage.firstElementChild.style.transformOrigin = "top left";
    };
    stage.append(buildPoster());
    const ro = new ResizeObserver(fit);
    ro.observe(previewHost);
    ctx.disposer.add(() => ro.disconnect());
    requestAnimationFrame(() => document.fonts?.ready?.then(fit));

    // ------ 操作 ------
    const busy = (btn, fn) => async () => {
      btn.classList.add("is-loading");
      btn.disabled = true;
      try {
        await fn();
      } catch (e) {
        toastError(e);
      } finally {
        btn.classList.remove("is-loading");
        btn.disabled = false;
      }
    };

    const dateInput = h("input", { class: "input", type: "date", value: state.trip.startDate || "", "aria-label": "出发日期", onchange: (e) => (state.trip.startDate = e.target.value) });

    const action = (ic, title, desc, label, fn, extra) => {
      const btn = h("button", { class: "btn btn--ink btn--sm", type: "button" }, label);
      btn.addEventListener("click", busy(btn, fn));
      return h("article", { class: "export-card" }, h("div", { class: "export-ico" }, icon(ic)), h("div", { class: "export-body" }, h("h3", null, title), h("p", null, desc), extra), btn);
    };

    const shareBox = h("div", { class: "share-box" });
    async function doShare() {
      const url = await shareTrip();
      const input = h("input", { class: "input", readonly: true, value: url, "aria-label": "分享链接", onfocus: (e) => e.target.select() });
      mountInto(shareBox,
        h("div", { class: "share-row" }, input, h("button", { class: "btn btn--sm btn--quiet", type: "button", onclick: async () => toast((await copyText(url)) ? "链接已复制" : "请手动复制链接", { error: false }) }, icon("copy"), "复制")),
        h("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: async () => {
          await unshareTrip(state.tripId);
          shareBox.replaceChildren();
          toast("已停止分享，旧链接失效");
        } }, "停止分享"));
      toast("分享链接已生成：拿到链接的人可以只读查看这份行程");
    }

    const cards = [
      action("image", "分享海报", "手账风长图，适合发朋友圈、小红书", "生成并下载 PNG", downloadPoster),
      action("printer", "PDF 行程单", "排版清爽，离线查看或打印带走", "打印 / 存为 PDF", async () => printPdf()),
      action("calendar", "加入手机日历", "每个景点一个日程，提前 30 分钟提醒", "下载 .ics", async () => {
        if (!state.trip.startDate) {
          dateInput.focus();
          throw new Error("先选一下出发日期，日历才知道该排在哪几天");
        }
        downloadIcs(state.trip.startDate);
        toast("已下载，双击文件即可导入日历");
      }, h("label", { class: "export-date" }, "出发日期", dateInput)),
      action("message", "复制文字行程", "纯文本，直接粘贴到微信 / 备忘录", "复制文字", async () => toast((await copyText(shareText())) ? "行程文字已复制" : "复制失败", { error: false })),
      action("share", "分享链接", "生成只读链接，搭子打开就能看，也能一键复制成 TA 自己的行程", "生成分享链接", doShare, shareBox),
      action("file", "Markdown 攻略", "含地址、建议时段，可导入 Notion / Obsidian", "下载 .md", async () => downloadMarkdown()),
    ];

    mountInto(
      page,
      h("a", { class: "back-link", href: "#/itinerary" }, icon("arrow-left"), "返回路线"),
      h("div", { class: "page-head" }, h("p", { class: "eyebrow" }, "STEP 07 · 导出分享"), h("h1", null, "把行程", h("span", { class: "mark" }, "带在身上")), h("p", null, "海报、日历、链接，选你顺手的方式。")),
      h("div", { class: "export-split" },
        h("div", { class: "export-list" }, cards),
        h("div", { class: "export-side" }, h("p", { class: "eyebrow" }, "海报预览"), previewHost)),
      h("div", { class: "page-foot" },
        h("button", { class: "btn btn--quiet", type: "button", onclick: async () => { try { await saveTrip(); toast("已保存到「我的行程」"); } catch (e) { toastError(e); } } }, icon("download"), "保存到我的行程"),
        h("button", { class: "btn btn--primary", type: "button", onclick: async () => {
          if (!(await confirmDialog({ title: "开始新的旅行？", message: "当前行程若已保存，可在「我的行程」里找回；未保存的修改将清空。", confirmText: "开始新旅行" }))) return;
          resetTrip();
          ctx.navigate("plan");
        } }, icon("sparkles"), "开始新的旅行"))
    );
  },
};
