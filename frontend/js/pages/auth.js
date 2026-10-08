import { h } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { decoImg } from "../core/config.js";
import { login, register, guest } from "../services/auth.js";
import { state, storage } from "../core/state.js";
import { toast } from "../ui/toast.js";

export default {
  title: (ctx) => (ctx.name === "register" ? "创建账号" : "登录"),

  mount(root, ctx) {
    const isRegister = ctx.name === "register";
    const err = h("div", { class: "form-error", role: "alert" });
    const showErr = (m) => ((err.textContent = m), err.classList.add("is-visible"));

    const user = h("input", { class: "input", id: "f-user", name: "username", type: "text", autocomplete: "username", required: true, placeholder: isRegister ? "3–20 个字符" : "输入用户名", autofocus: true });
    const pass = h("input", { class: "input", id: "f-pass", name: "password", type: "password", autocomplete: isRegister ? "new-password" : "current-password", required: true, placeholder: isRegister ? "6–20 个字符" : "输入密码" });
    const pass2 = h("input", { class: "input", id: "f-pass2", type: "password", autocomplete: "new-password", required: true, placeholder: "再输入一次" });

    const eye = h("button", { class: "icon-btn icon-btn--sm", type: "button", "aria-label": "显示密码", onclick: () => {
      const show = pass.type === "password";
      pass.type = show ? "text" : "password";
      eye.replaceChildren(icon(show ? "eye-off" : "eye"));
      eye.setAttribute("aria-label", show ? "隐藏密码" : "显示密码");
    } }, icon("eye"));

    const submit = h("button", { class: "btn btn--primary btn--lg btn--block", type: "submit" }, isRegister ? "创建账号" : "登录", icon("arrow-right", "i-arrow"));

    const form = h(
      "form",
      { class: "auth-form", novalidate: true, onsubmit: async (e) => {
        e.preventDefault();
        err.classList.remove("is-visible");
        const u = user.value.trim();
        if (!u || !pass.value) return showErr("请填写用户名和密码");
        if (isRegister) {
          if (u.length < 3 || u.length > 20) return showErr("用户名长度需为 3–20 个字符");
          if (pass.value.length < 6) return showErr("密码长度至少 6 个字符");
          if (pass.value !== pass2.value) return showErr("两次输入的密码不一致");
        }
        submit.classList.add("is-loading");
        submit.disabled = true;
        try {
          await (isRegister ? register(u, pass.value) : login(u, pass.value));
          toast(isRegister ? `注册成功，欢迎 ${u}！先来测测你的旅行人格` : `欢迎回来，${u}`);
          const pending = storage.get("ypjh_pending_share");
          if (pending) {
            storage.del("ypjh_pending_share");
            return ctx.navigate("shared", { token: pending });
          }
          ctx.navigate(state.persona ? "plan" : "persona");
        } catch (ex) {
          showErr(ex.message);
        } finally {
          submit.classList.remove("is-loading");
          submit.disabled = false;
        }
      } },
      err,
      h("div", { class: "field" }, h("label", { for: "f-user" }, "用户名"), user, isRegister && h("span", { class: "hint" }, "字母、数字、下划线或中文")),
      h("div", { class: "field" }, h("label", { for: "f-pass" }, "密码"), h("div", { class: "input-group" }, pass, eye)),
      isRegister && h("div", { class: "field" }, h("label", { for: "f-pass2" }, "确认密码"), pass2),
      submit
    );

    const sticker = (name, style) => h("img", { class: "sticker sticker--float", src: decoImg(name), alt: "", width: 200, height: 200, style, decoding: "async" });

    root.append(
      h(
        "section",
        { class: "auth" },
        h(
          "div",
          { class: "auth-hero" },
          h("p", { class: "eyebrow rise", style: { "--i": 0 } }, "AI TRIP JOURNAL · 抖音精选内容重构"),
          h("h1", { class: "rise", style: { "--i": 1 } }, "把收藏夹里的", h("br"), "远方，", h("span", { class: "mark" }, "走成路线"), "。"),
          h("p", { class: "auth-lede rise", style: { "--i": 2 } }, "粘贴收藏的旅行视频，AI 提取景点；结合你的旅行人格，排出能真正走得通的逐日路线——含通勤、预算、天气和行前清单。"),
          h(
            "ol",
            { class: "auth-steps rise", style: { "--i": 3 } },
            [["01", "测旅行人格", "10 种画像，决定你的节奏与偏好"], ["02", "喂给它视频", "抖音链接 → 景点 → 地图"], ["03", "一键成行程", "可拖拽、可优化、可分享"]].map(([n, t, d]) => h("li", null, h("span", { class: "mono" }, n), h("div", null, h("b", null, t), h("small", null, d))))
          ),
          sticker("camera", { "--w": "108px", "--rot": "-10deg", right: "6%", top: "-6%" }),
          sticker("suitcase", { "--w": "120px", "--rot": "8deg", right: "34%", bottom: "-4%", "--d": "-2s" }),
          sticker("compass", { "--w": "92px", "--rot": "-6deg", right: "2%", top: "48%", "--d": "-4s" })
        ),
        h(
          "div",
          { class: "auth-side rise", style: { "--i": 2 } },
          h(
            "div",
            { class: "boarding ticket", style: { "--stub": "86px" } },
            h("div", { class: "boarding-head" }, h("span", { class: "mono" }, "BOARDING PASS"), h("span", { class: "mono" }, isRegister ? "NEW · 新旅客" : "旅客登机")),
            h("h2", null, isRegister ? "创建账号" : "欢迎登机"),
            form,
            h("hr", { class: "perf" }),
            h("p", { class: "auth-switch" }, isRegister ? "已有账号？" : "还没有账号？", h("a", { href: isRegister ? "#/login" : "#/register" }, isRegister ? "去登录" : "立即注册")),
            h("button", { class: "btn btn--ghost btn--block guest-btn", type: "button", onclick: async (e) => {
              const btn = e.currentTarget;
              btn.classList.add("is-loading");
              btn.disabled = true;
              try {
                await guest();
                toast("已用游客身份进入，之后可以在右上角「设置账号」保存进度");
                ctx.navigate(state.persona ? "plan" : "persona");
              } catch (ex) {
                showErr(ex.message);
              } finally {
                btn.classList.remove("is-loading");
                btn.disabled = false;
              }
            } }, icon("compass"), "先逛逛，不注册")
          )
        )
      )
    );
    setTimeout(() => user.focus(), 50);
  },
};
