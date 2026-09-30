/** 旅行人格 ↔ 地点匹配（从旧版 isPersonalityMatch 迁移，逻辑不变） */
import { state } from "../core/state.js";

export function styleProfile() {
  const r = state.persona;
  if (!r?.mbti) return {};
  const v = (i) => r.dimensions?.[i]?.value;
  return {
    mbti: r.mbti,
    personality_name: r.personality?.name || "",
    description: r.personality?.description || "",
    di_label: v(0) === "D" ? "记录表达型" : "沉浸感受型",
    rl_label: v(1) === "R" ? "精致风格型" : "本地烟火型",
    ps_label: v(2) === "P" ? "计划依赖型" : "灵感优先型",
    cd_label: v(3) === "C" ? "覆盖打卡型" : "深度停留型",
    deep_profile: r.deep_profile || null,
  };
}

export function isPersonalityMatch(loc) {
  const mbti = state.persona?.mbti;
  if (!mbti || mbti.length < 4) return true;
  // AI 联网发现的地点：直接采用后端基于主画像描述判定的 selected
  if (loc.source === "ai_discover" && typeof loc.selected === "boolean") return loc.selected;

  const fit = loc.travel_style_fit || loc.personality_fit || {};
  const structured = ["pace", "pref", "exp", "social"].some((k) => typeof fit[k] === "string" && fit[k].trim());
  if (!structured) return true;

  let score = 0;
  const [d0, d1, d2, d3] = mbti;
  if ((d0 === "D" && ["any", "rush"].includes(fit.pace)) || (d0 === "I" && ["any", "slow"].includes(fit.pace))) score++;
  if ((d1 === "R" && ["any", "classic"].includes(fit.pref)) || (d1 === "L" && ["any", "hidden"].includes(fit.pref))) score++;
  if ((d2 === "P" && ["any", "scene"].includes(fit.exp)) || (d2 === "S" && ["any", "food"].includes(fit.exp))) score++;
  if ((d3 === "C" && ["any", "social"].includes(fit.social)) || (d3 === "T" && ["any", "solo"].includes(fit.social))) score++;
  return score >= 3;
}
