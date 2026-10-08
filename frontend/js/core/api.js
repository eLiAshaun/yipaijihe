import { state, bus } from "./state.js";

export class ApiError extends Error {
  constructor(message, status = 0, data = null) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function request(method, url, body, { signal } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (state.token) headers.Authorization = `Bearer ${state.token}`;

  let res;
  try {
    res = await fetch(url, { method, headers, signal, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError("网络似乎断开了，请检查连接后重试");
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    /* 非 JSON 响应 */
  }
  if (!res.ok) {
    if (res.status === 401 && state.token) bus.emit("auth:expired");
    throw new ApiError(data?.error || `请求失败（${res.status}）`, res.status, data);
  }
  return data ?? {};
}

export const api = {
  get: (url, opts) => request("GET", url, undefined, opts),
  post: (url, body, opts) => request("POST", url, body ?? {}, opts),
  put: (url, body, opts) => request("PUT", url, body ?? {}, opts),
  del: (url, opts) => request("DELETE", url, undefined, opts),
};

export const isAbort = (e) => e?.name === "AbortError";
