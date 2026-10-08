/**
 * 外部跳转链接（无需任何 Key，手机上会唤起对应 App）
 *  · 高德导航：https://uri.amap.com/navigation
 *  · 高德周边搜索：https://uri.amap.com/search
 *  · 抖音搜索
 */
import { hasCoords, stopLocation } from "./planner.js";

const enc = encodeURIComponent;

/** 导航到某个地点（公共交通优先）；没有坐标时按名称搜索 */
export function navUrl(loc, { mode = "bus" } = {}) {
  if (!loc) return "";
  if (hasCoords(loc)) return `https://uri.amap.com/navigation?to=${loc.lng},${loc.lat},${enc(loc.name || "目的地")}&mode=${mode}&policy=1&src=yipaijihe&coordinate=gaode&callnative=1`;
  return `https://uri.amap.com/search?keyword=${enc(loc.name || "")}&src=yipaijihe&callnative=1`;
}

/** 某地点周边搜索（找餐厅 / 咖啡 / 便利店…） */
export function nearbyUrl(loc, keyword = "美食", city = "") {
  if (hasCoords(loc)) return `https://uri.amap.com/search?keyword=${enc(keyword)}&center=${loc.lng},${loc.lat}&radius=1000&view=map&src=yipaijihe&coordinate=gaode&callnative=1`;
  return `https://uri.amap.com/search?keyword=${enc(`${city}${keyword}`)}&src=yipaijihe&callnative=1`;
}

export const douyinUrl = (name) => `https://www.douyin.com/search/${enc(`${name} 攻略`)}`;

/** 一天里某个位置之前最近的有坐标的地点（用餐时段用它来找附近餐厅） */
export function anchorBefore(items, index) {
  for (let i = index - 1; i >= 0; i--) if (hasCoords(stopLocation(items[i]))) return stopLocation(items[i]);
  for (let i = index + 1; i < items.length; i++) if (hasCoords(stopLocation(items[i]))) return stopLocation(items[i]);
  return null;
}

