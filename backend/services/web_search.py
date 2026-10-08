"""
联网搜索：这里负责「搜」，再交给大模型「读」。

DeepSeek 等模型的 API 不带联网搜索工具（web_search 类型的工具会被忽略），所以：
  1. 多个搜索源并行查询（头条搜索 / Bing / DuckDuckGo），丢掉和查询无关的结果
     —— Bing 对疑似程序的请求有时会返回随机热门结果，必须做相关性过滤
  2. 把「标题 + 摘要（+ 少量能直接读取的正文）」编号后交给大模型，只允许它根据这些资料回答，并注明引用编号
  3. 地点坐标用地理编码校正（Photon → GCJ-02），不直接相信模型给的经纬度

discover_attractions 的后备链：
  豆包内置联网搜索（配置了 DOUBAO_API_KEY 时）→ 搜索引擎 + 大模型 → 大模型自身知识（明确标注「未联网核实」）
  → 都不行时返回空，由路由层改用内置景点库。
"""

from __future__ import annotations

import html
import ipaddress
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse

import requests

from backend.config import Config

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
}
_TIMEOUT = 8
# 三个线程池分层使用（查询 → 搜索源；请求线程 → 读正文 / 地理编码），互不嵌套等待，避免并发时线程池死锁
_QUERY_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="search-q")
_ENGINE_POOL = ThreadPoolExecutor(max_workers=12, thread_name_prefix="search-e")
_IO_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="search-io")

# 这些站点的正文要执行 JS 或登录才能看到，直接抓取只会拿到空壳，只用搜索摘要
_JS_ONLY_HOSTS = ("douyin.com", "xiaohongshu.com", "toutiao.com", "zhihu.com", "weibo.com", "bilibili.com", "baidu.com", "sohu.com", "qq.com", "163.com", "weixin.qq.com")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


# ------------------------------------------------------------------ 搜索源 ----
def _toutiao(query: str) -> list[dict]:
    resp = requests.get("https://so.toutiao.com/search", params={"keyword": query, "pd": "information"}, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    out = []
    for part in resp.text.split('class="result-content"')[1:]:
        m = re.search(r'cr-params="([^"]+)"', part)
        if not m:
            continue
        try:
            card = json.loads(html.unescape(m.group(1)))
        except ValueError:
            continue
        title = _clean(card.get("title") or "")
        snippet = " ".join(_clean(x) for x in re.findall(r"l-paragraph[^>]*>(.*?)</div>", part, re.S))
        gid = card.get("gid")
        url = card.get("url") or (f"https://www.toutiao.com/article/{gid}/" if gid else "")
        if title and snippet:
            out.append({"title": title, "url": url, "snippet": snippet[:320], "engine": "头条搜索"})
    return out


def _bing(query: str) -> list[dict]:
    resp = requests.get("https://www.bing.com/search", params={"q": query}, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    out = []
    for block in re.findall(r'<li class="b_algo"(.*?)</li>', resp.text, re.S):
        a = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        p = re.search(r"<p[^>]*>(.*?)</p>", block, re.S) or re.search(r'class="b_caption"[^>]*>(.*?)</div>', block, re.S)
        if not a:
            continue
        url, title = html.unescape(a.group(1)), _clean(a.group(2))
        snippet = _clean(p.group(1)) if p else ""
        if url.startswith("http") and title:
            out.append({"title": title, "url": url, "snippet": snippet[:320], "engine": "Bing"})
    return out


def _duckduckgo(query: str) -> list[dict]:
    resp = requests.post("https://html.duckduckgo.com/html/", data={"q": query, "kl": "cn-zh"}, headers=_HEADERS, timeout=_TIMEOUT)
    if resp.status_code != 200:
        return []
    out = []
    for m in re.finditer(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.S):
        url = html.unescape(m.group(1))
        if "uddg=" in url:
            from urllib.parse import parse_qs

            url = parse_qs(urlparse(url).query).get("uddg", [url])[0]
        out.append({"title": _clean(m.group(2)), "url": url, "snippet": _clean(m.group(3))[:320], "engine": "DuckDuckGo"})
    return out


_ENGINES = (_toutiao, _bing, _duckduckgo)


def _bigrams(text: str) -> set[str]:
    han = re.findall(r"[一-龥]+|[A-Za-z0-9]+", text.lower())
    out = set()
    for seg in han:
        if seg.isascii():
            out.add(seg)
        else:
            out.update(seg[i:i + 2] for i in range(max(1, len(seg) - 1)))
    return out


def _relevant(item: dict, query: str, must: tuple[str, ...]) -> bool:
    text = f"{item['title']} {item['snippet']}"
    if any(m and m not in text for m in must):
        return False
    q = _bigrams(query)
    return not q or len(q & _bigrams(text)) / len(q) >= 0.25


def search(query: str, limit: int = 10, must: tuple[str, ...] = ()) -> list[dict]:
    """多个搜索源并行查询，合并去重并过滤无关结果。单个搜索源失败不影响其他。"""
    futures = [_ENGINE_POOL.submit(engine, query) for engine in _ENGINES]
    merged, seen = [], set()
    for fut in futures:
        try:
            items = fut.result(timeout=_TIMEOUT + 4)
        except Exception as e:  # noqa: BLE001 — 搜索源被墙 / 反爬 / 超时
            logger.info("搜索源失败: %s", str(e)[:120])
            continue
        for item in items:
            key = re.sub(r"\W", "", item["title"])[:24]
            if key in seen or not _relevant(item, query, must):
                continue
            seen.add(key)
            merged.append(item)
    # 交替取各搜索源的结果，避免某一个源独占
    by_engine: dict[str, list] = {}
    for item in merged:
        by_engine.setdefault(item["engine"], []).append(item)
    out = []
    while len(out) < limit and any(by_engine.values()):
        for items in by_engine.values():
            if items and len(out) < limit:
                out.append(items.pop(0))
    return out


def _public_http(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not host or host == "localhost":
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host


def fetch_text(url: str, limit: int = 2500, focus: str = "") -> str:
    """读取网页正文（只读服务端渲染的页面）；失败返回空串"""
    host = (urlparse(url).hostname or "").lower()
    if not _public_http(url) or any(host == h or host.endswith("." + h) for h in _JS_ONLY_HOSTS):
        return ""
    try:
        with requests.get(url, headers=_HEADERS, timeout=6, stream=True, allow_redirects=True) as resp:
            if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", "html"):
                return ""
            raw = resp.raw.read(1_500_000, decode_content=True)
            encoding = resp.encoding if resp.encoding and resp.encoding.lower() != "iso-8859-1" else resp.apparent_encoding
    except Exception:  # noqa: BLE001
        return ""
    page = raw.decode(encoding or "utf-8", "replace")
    page = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", page)
    text = _clean(re.sub(r"(?i)<(br|p|div|li|h\d)[^>]*>", "\n", page))
    if len(re.findall(r"[一-龥]", text)) < 200:
        return ""
    if focus and focus in text:
        start = max(0, text.find(focus) - 200)
        text = text[start:]
    return text[:limit]


def format_sources(items: list[dict], start: int = 1) -> str:
    lines = []
    for i, it in enumerate(items, start):
        body = it.get("content") or it["snippet"]
        lines.append(f"[{i}] {it['title']}（{it['engine']}）\n{body}")
    return "\n\n".join(lines)


# ------------------------------------------------------------ 发现景点 ----
_CACHE: dict[tuple, tuple[float, list, dict]] = {}
_CACHE_TTL = 6 * 3600
_CACHE_LOCK = threading.Lock()

_TYPES = ("landmark", "street", "food", "culture", "nature")
_COSTS = ("免费", "低", "中等", "较高", "高")
_FIT_VALUES = {"pace": ("rush", "slow", "any"), "pref": ("classic", "hidden", "any"), "exp": ("scene", "food", "any"), "social": ("social", "solo", "any")}


def _persona_text(profile: dict) -> str:
    profile = profile or {}
    labels = " / ".join(profile.get(k) for k in ("di_label", "rl_label", "ps_label", "cd_label") if profile.get(k))
    if not (profile.get("personality_name") or labels):
        return "（用户没有做旅行人格测试，按大众口味挑选）"
    text = f"旅行人格：{profile.get('personality_name') or ''}（{labels}）"
    if profile.get("description"):
        text += f"\n画像：{str(profile['description'])[:300]}"
    return text


def _queries(city: str, days: int, profile: dict) -> list[str]:
    code = (profile or {}).get("mbti") or ""
    qs = [f"{city}{days}日游攻略 必去景点", f"{city} 本地人推荐 小众景点", f"{city} 必吃美食 推荐"]
    if len(code) >= 2 and code[1] == "R":
        qs.append(f"{city} 美术馆 展览 咖啡 推荐")
    elif len(code) >= 3 and code[2] == "S":
        qs.append(f"{city} 老字号 小吃 街 推荐")
    else:
        qs.append(f"{city} 夜景 拍照 打卡")
    return qs


def _gather_sources(city: str, days: int, profile: dict) -> list[dict]:
    queries = _queries(city, days, profile)
    futures = [_QUERY_POOL.submit(search, q, 8, (city,)) for q in queries]
    items, seen = [], set()
    for fut in futures:
        try:
            for it in fut.result(timeout=_TIMEOUT * 2 + 4):
                if it["title"] not in seen:
                    seen.add(it["title"])
                    items.append(it)
        except Exception:  # noqa: BLE001
            continue
    # 再读几篇能直接打开的攻略正文，摘要往往只有一两个地点
    readable = [it for it in items if it["engine"] != "头条搜索"][:4]
    for it, text in zip(readable, _IO_POOL.map(lambda x: fetch_text(x["url"], 2500, city), readable)):
        if text:
            it["content"] = text
    return items[:24]


def _discover_prompt(city: str, days: int, profile: dict, sources: list[dict] | None) -> str:
    want = max(12, min(24, days * 6))
    basis = (
        f"## 资料（来自联网搜索，编号可引用）\n{format_sources(sources)}\n\n"
        "只能挑选资料里出现过的地点，sources 写出处编号；资料里没有提到的信息不要编。"
        if sources
        else "## 说明\n当前无法联网，请根据你掌握的知识挑选真实存在、至今仍在营业的地点；拿不准的不要写。sources 留空数组。"
    )
    return f"""你是熟悉{city}的旅行编辑。为一位要在{city}玩 {days} 天的用户整理候选地点。

## 用户
{_persona_text(profile)}

{basis}

## 要求
- 挑 {want} 个左右、互不重复、位于{city}的具体地点（景点、街区、展馆、公园、餐厅、小吃店、咖啡馆都可以，美食约占三分之一）
- 名称要简洁、能直接在地图里搜到（如「宽窄巷子」而不是「成都宽窄巷子历史文化保护区游览」）
- 不要城市/行政区/泛称（如「市中心」「春熙路附近」「火锅」）
- 按用户画像，把最契合的 {days * 3}-{days * 4} 个标 pick=true，并用 fit_reason 说明为什么适合 TA（20 字以内，具体）
- tips 只写资料里提到的实用信息，用这些说法：「周一闭馆」「需提前预约」「末班 21:30」「排队约 1 小时」；没有就留空

## 输出
只输出 JSON 对象：
{{"places": [{{
  "name": "地点名",
  "type": "landmark|street|food|culture|nature",
  "category": "4 字以内类别，如 历史街区 / 川菜馆 / 博物馆",
  "area": "所在区域或商圈",
  "best_time": "上午|下午|傍晚|夜间|全天|上午-下午|下午-傍晚|傍晚-夜间",
  "duration_min": 90,
  "cost_level": "免费|低|中等|较高",
  "crowd_level": "low|medium|high",
  "reason": "一句话：为什么值得去（30 字以内）",
  "tips": "",
  "tags": ["2-3 个短标签"],
  "travel_style_fit": {{"pace": "rush|slow|any", "pref": "classic|hidden|any", "exp": "scene|food|any", "social": "social|solo|any"}},
  "lat": 30.6598, "lng": 104.0633,
  "sources": [1, 3],
  "pick": true,
  "fit_reason": ""
}}]}}"""


def _parse_places(text: str) -> list[dict]:
    from backend.services.llm_service import parse_json

    data = parse_json(text)
    if isinstance(data, dict):
        data = data.get("places") or next((v for v in data.values() if isinstance(v, list)), None)
    return [p for p in (data or []) if isinstance(p, dict) and (p.get("name") or "").strip()]


def _normalize(raw: list[dict], city: str, sources: list[dict], mode: str) -> list[dict]:
    from backend.services.geo import city_center, km_between, locate, wgs84_to_gcj02

    center = city_center(city)
    places, seen = [], set()
    for p in raw:
        name = re.sub(r"\s+", "", str(p["name"]))[:40]
        if not name or name in seen or name == city:
            continue
        seen.add(name)
        try:
            duration = max(15, min(int(p.get("duration_min") or 60), 480))
        except (TypeError, ValueError):
            duration = 60
        fit = p.get("travel_style_fit") if isinstance(p.get("travel_style_fit"), dict) else {}
        refs = []
        for i in p.get("sources") or []:
            try:
                src = sources[int(i) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            if src not in refs:
                refs.append(src)
        places.append({
            "name": name,
            "type": p.get("type") if p.get("type") in _TYPES else "landmark",
            "category": str(p.get("category") or "")[:12] or "城市漫游",
            "address": str(p.get("area") or "")[:60],
            "best_time": str(p.get("best_time") or "全天")[:20],
            "duration_min": duration,
            "cost_level": p.get("cost_level") if p.get("cost_level") in _COSTS else "中等",
            "crowd_level": p.get("crowd_level") if p.get("crowd_level") in ("low", "medium", "high") else "medium",
            "description": str(p.get("reason") or "")[:200],
            "reason": str(p.get("fit_reason") or p.get("reason") or "")[:120],
            "tips": str(p.get("tips") or "")[:200],
            "tags": [str(t)[:10] for t in (p.get("tags") or [])][:4],
            "keywords": [str(t)[:10] for t in (p.get("tags") or [])][:4],
            "travel_style_fit": {k: fit[k] for k, ok in _FIT_VALUES.items() if fit.get(k) in ok},
            "selected": bool(p.get("pick")),
            "sources": [{"title": s["title"][:60], "url": s["url"]} for s in refs[:3] if s.get("url")],
            "source": "ai_discover",
            "source_label": "联网搜索 · 大模型归纳" if mode == "web" else "大模型知识 · 未联网核实，出发前请确认",
            "douyin_search_url": f"https://www.douyin.com/search/{quote(f'{name} {city}')}",
            "_llm_coords": (p.get("lat"), p.get("lng")),
        })

    def place_coords(place: dict):
        hit = locate(place["name"], city, center)
        if hit:
            return hit
        lat, lng = place["_llm_coords"]
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            return None
        # 模型给的坐标只在离城市中心不远时采用（按 WGS-84 处理并转换）
        if center and km_between(center, (lat, lng)) > 60:
            return None
        return wgs84_to_gcj02(lat, lng)

    for place, coords in zip(places, _IO_POOL.map(place_coords, places)):
        place.pop("_llm_coords", None)
        place["lat"], place["lng"] = coords if coords else (None, None)
    return places


def _ask_llm(prompt: str) -> str:
    from backend.services.llm_service import chat_completion

    return chat_completion(
        [{"role": "system", "content": "你是严谨的旅行编辑，只根据给定资料作答。只输出合法 JSON。"}, {"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=6000,
        json_mode=True,
    )


def discover_attractions(city: str, days: int, profile: dict | None = None) -> tuple[list[dict], dict]:
    """
    返回 (地点列表, 元信息)。元信息：mode = doubao / web / knowledge / none，sources = 引用过的资料，queries = 搜索词。
    """
    profile = profile or {}
    key = (city, days, profile.get("mbti") or "")
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            return [dict(p) for p in hit[1]], dict(hit[2])

    places, meta = [], {"mode": "none", "sources": [], "queries": _queries(city, days, profile)}
    t0 = time.time()

    # 1) 豆包：自带联网搜索
    if Config.HAS_DOUBAO:
        from backend.services.llm_service import _call_doubao_responses

        text = _call_doubao_responses(_discover_prompt(city, days, profile, None).replace("当前无法联网，请根据你掌握的知识", "请联网搜索最新攻略，"), use_web_search=True)
        raw = _parse_places(text)
        if raw:
            places, meta["mode"] = _normalize(raw, city, [], "web"), "doubao"

    # 2) 搜索引擎 + 大模型
    if not places and Config.HAS_LLM:
        sources = _gather_sources(city, days, profile)
        logger.info("联网搜索「%s」拿到 %d 条资料（%.1fs）", city, len(sources), time.time() - t0)
        if len(sources) >= 3:
            raw = _parse_places(_ask_llm(_discover_prompt(city, days, profile, sources)))
            if raw:
                places, meta["mode"] = _normalize(raw, city, sources, "web"), "web"
                used = {s["url"] for p in places for s in p["sources"]}
                meta["sources"] = [{"title": s["title"], "url": s["url"], "engine": s["engine"]} for s in sources if s["url"] in used]

        # 3) 搜索不可用（被墙 / 反爬）→ 大模型自身知识，明确标注未核实
        if not places:
            raw = _parse_places(_ask_llm(_discover_prompt(city, days, profile, None)))
            if raw:
                places, meta["mode"] = _normalize(raw, city, [], "knowledge"), "knowledge"

    logger.info("发现景点：%s · %d 个 · 模式 %s · %.1fs", city, len(places), meta["mode"], time.time() - t0)
    if places:
        with _CACHE_LOCK:
            _CACHE[key] = (time.time(), [dict(p) for p in places], dict(meta))
    return places, meta


# ------------------------------------------------------------ 对话里查资料 ----
def answer_sources(query: str, city: str = "", limit: int = 6) -> tuple[str, list[dict]]:
    """给对话用：搜索并返回（编号资料文本, 资料列表）"""
    must = (city,) if city and city in query else ()
    items = search(query, limit=limit, must=must)
    return format_sources(items), [{"title": it["title"], "url": it["url"], "engine": it["engine"]} for it in items]
