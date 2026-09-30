export const STORAGE = {
  token: "ypjh_token",
  legacyToken: "luvdazi_token",
  draft: "ypjh_draft",
  theme: "ypjh_theme",
  checklist: "ypjh_checklist",
};

export const DECO = {
  ship: "轮船", suitcase: "行李箱", map: "地图", camera: "相机", castle: "城堡",
  sunglasses: "墨镜", compass: "指南针", passport: "护照", signpost: "指示牌",
  mountain: "山", beach: "沙滩",
};

/** 后端返回 "2生活家.png"，前端使用压缩后的 webp */
const webp = (name) => encodeURIComponent(String(name || "2生活家.png").replace(/\.png$/i, ".webp"));
export const personaImg = (name) => `assets/person/${webp(name)}`;
export const personaThumb = (name) => `assets/person/${webp(name).replace(/\.webp$/, "-sm.webp")}`;
export const decoImg = (key) => `assets/deco/${encodeURIComponent(DECO[key] || key)}.webp`;
/** mbti_data 里 deco_image 是 "行李箱.png" */
export const decoFromFile = (file) => `assets/deco/${webp(file)}`;

export const STEPS = [
  { n: 1, route: "persona", label: "旅行人格" },
  { n: 2, route: "plan", label: "行程规划" },
  { n: 3, route: "buddy", label: "旅行搭子" },
  { n: 4, route: "videos", label: "精选视频" },
  { n: 5, route: "places", label: "地点筛选" },
  { n: 6, route: "itinerary", label: "路线编辑" },
  { n: 7, route: "export", label: "导出分享" },
];

export const DAY_COLORS = ["--day-1", "--day-2", "--day-3", "--day-4", "--day-5", "--day-6", "--day-7", "--day-8"];
/** 地图 marker 需要具体色值（AMap 不吃 CSS 变量） */
export const DAY_HEX = ["#d6402a", "#1f6b73", "#e2a63b", "#6a4c93", "#5d7b4c", "#c2557f", "#3a6ea5", "#8a5a2b"];
export const dayColorVar = (i) => `var(${DAY_COLORS[i % DAY_COLORS.length]})`;
export const dayHex = (i) => DAY_HEX[i % DAY_HEX.length];
export const TYPE_HEX = { food: "#d9782d", nature: "#5d7b4c", culture: "#6a4c93", landmark: "#d6402a", street: "#1f6b73" };
