import { api } from "../core/api.js";

/** /api/config 只请求一次：地图 Key、可用的 AI 能力、有内置景点库的城市 */
let pending = null;
export function getConfig() {
  pending ||= api.get("/api/config").catch((e) => {
    pending = null;
    throw e;
  });
  return pending;
}
